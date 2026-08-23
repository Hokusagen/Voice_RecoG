"""Стекло с преломлением.

Размытие плюс тонировка дают матовое стекло — плоское пятно, за которым просто
не видно деталей. У настоящей стеклянной линзы работает кромка: она тоньше
середины, поэтому меньше размывает, зато заметно преломляет — фон у края
подтягивается наружу и растягивается вдоль контура. Плюс на кромке собирается
блик, а на просвет чуть расходятся цвета.

Всё это считается по снимку фона numpy-массивами. Считать дорого, но снимок
делается один раз при появлении плашки, а результат кэшируется по размеру, так
что на кадр отрисовки не приходится ничего: готовая картинка просто выводится.

Порядок сборки повторяет физику:

1. два размытия — сильное для толстой середины и слабое для тонкой кромки;
2. поле расстояний до контура даёт нормаль и «толщину» стекла в каждой точке;
3. у кромки выборка смещается вдоль нормали наружу — это и есть преломление;
4. каналы смещаются чуть по-разному — дисперсия;
5. тонировка, подъём насыщенности, блик по кромке и внутренняя тень.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QColor, QImage, QPixmap

from ui.shadow import box_blur
from ui.theme import Material

#: Запас вокруг плашки: из него берутся пиксели, которые кромка втягивает внутрь.
MARGIN = 44

_THICK_BLUR = 6
"""Размытие середины — там стекло толстое.

Сильнее — и фон превращается в ровное пятно: стекло перестаёт читаться как
стекло, потому что сквозь него уже нечего узнавать.
"""

_THIN_BLUR = 2
"""Размытие кромки — она тоньше и почти не рассеивает."""

_REFRACT = 13.0
"""Максимальный сдвиг выборки на кромке, пикселей."""

_DISPERSION = 0.07
"""Расхождение каналов на кромке — красный преломляется слабее синего."""

_EDGE = 15.0
"""Ширина скошенной кромки, пикселей."""


def _blur_rgb(source: np.ndarray, radius: int) -> np.ndarray:
    out = np.empty_like(source)
    step = max(1, radius // 3)
    for channel in range(3):
        values = source[..., channel]
        for _ in range(3):
            values = box_blur(values, step, mode="edge")
        out[..., channel] = values
    return out


def _rounded_box_sdf(xx: np.ndarray, yy: np.ndarray, half_w: float, half_h: float, radius: float):
    """Расстояние со знаком до контура пилюли: внутри отрицательное."""
    qx = np.abs(xx) - (half_w - radius)
    qy = np.abs(yy) - (half_h - radius)
    outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return outside + inside - radius


def _sample(source: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Билинейная выборка: без неё смещённая кромка идёт ступеньками."""
    height, width = source.shape[:2]
    x = np.clip(x, 0.0, width - 1.001)
    y = np.clip(y, 0.0, height - 1.001)

    x0 = x.astype(np.int32)
    y0 = y.astype(np.int32)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]

    top = source[y0, x0] * (1.0 - fx) + source[y0, x0 + 1] * fx
    bottom = source[y0 + 1, x0] * (1.0 - fx) + source[y0 + 1, x0 + 1] * fx
    return top * (1.0 - fy) + bottom * fy


class Backdrop:
    """Снимок фона под плашкой и собранные из него стёкла разных размеров."""

    def __init__(self, raw: np.ndarray) -> None:
        self._raw = raw
        self._thick = _blur_rgb(raw, _THICK_BLUR)
        self._thin = _blur_rgb(raw, _THIN_BLUR)
        self._cache: dict[tuple[int, int, int], QPixmap] = {}

        # Светимость по формуле яркости: по ней выбирается светлое или тёмное
        # стекло. Считаем по размытой середине — случайная яркая точка на фоне
        # не должна перекидывать материал.
        weights = np.array([0.0722, 0.7152, 0.2126], dtype=np.float32)  # BGR
        self.luminance = float((self._thick * weights).sum(axis=-1).mean() / 255.0)

    def render(self, width: int, height: int, glass: Material) -> QPixmap | None:
        """Готовое стекло размером width x height. Считается один раз на размер."""
        key = (width, height, id(glass))
        cached = self._cache.get(key)
        if cached is None:
            cached = self._build(width, height, glass)
            self._cache[key] = cached
        return cached

    # ---------- сборка ----------

    def _build(self, width: int, height: int, glass: Material) -> QPixmap | None:
        source_h, source_w = self._raw.shape[:2]
        if width < 8 or height < 8 or width + 2 > source_w or height + 2 > source_h:
            return None

        half_w, half_h = width / 2.0, height / 2.0
        radius = half_h
        center_x, center_y = source_w / 2.0, source_h / 2.0

        # Сетка в координатах снимка: плашка всегда в его центре.
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        src_x = xx + (center_x - half_w)
        src_y = yy + (center_y - half_h)
        local_x = xx - half_w + 0.5
        local_y = yy - half_h + 0.5

        distance = _rounded_box_sdf(local_x, local_y, half_w, half_h, radius)

        # Нормаль к контуру — градиент поля расстояний, нормированный на длину.
        grad_y, grad_x = np.gradient(distance)
        length = np.hypot(grad_x, grad_y)
        np.maximum(length, 1e-5, out=length)
        normal_x = grad_x / length
        normal_y = grad_y / length

        # thickness: 0 у самой кромки, 1 глубже _EDGE пикселей внутрь.
        thickness = np.clip(-distance / _EDGE, 0.0, 1.0)
        bevel = (1.0 - thickness) ** 1.7

        # Преломление: у кромки берём пиксели снаружи и втягиваем внутрь.
        offset = _REFRACT * bevel
        channels = []
        for index, spread in enumerate((1.0 + _DISPERSION, 1.0, 1.0 - _DISPERSION)):
            shift = offset * spread
            thin = _sample(self._thin, src_x + normal_x * shift, src_y + normal_y * shift)
            thick = _sample(self._thick, src_x, src_y)
            # Кромка тонкая — почти не рассеивает; середина толстая — размывает.
            channels.append(thin[..., index] * bevel + thick[..., index] * (1.0 - bevel))
        color = np.stack(channels, axis=-1)

        color = _saturate(color, 1.22)
        color = _tint(color, glass, height)
        color = _specular(color, normal_x, normal_y, bevel, glass)

        # Сглаженный край: поле расстояний даёт готовую полупрозрачную кромку.
        alpha = np.clip(0.5 - distance, 0.0, 1.0) * 255.0

        buffer = np.empty((height, width, 4), dtype=np.uint8)
        buffer[..., :3] = np.clip(color, 0, 255).astype(np.uint8)
        buffer[..., 3] = alpha.astype(np.uint8)

        image = QImage(buffer.data, width, height, width * 4, QImage.Format_ARGB32)
        return QPixmap.fromImage(image.copy())


def _saturate(color: np.ndarray, amount: float) -> np.ndarray:
    """Стекло чуть подкрашивает то, что за ним, — иначе фон выглядит вялым."""
    grey = color.mean(axis=-1, keepdims=True)
    return grey + (color - grey) * amount


def _tint(color: np.ndarray, glass: Material, height: int) -> np.ndarray:
    """Вертикальный градиент тонировки поверх преломлённого фона."""
    ramp = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    top, bottom = glass.scrim_top, glass.scrim_bottom

    tint_color = np.stack(
        [
            _ramp(top.blue(), bottom.blue(), ramp),
            _ramp(top.green(), bottom.green(), ramp),
            _ramp(top.red(), bottom.red(), ramp),
        ],
        axis=-1,
    )[..., 0, :]
    tint_alpha = _ramp(top.alpha(), bottom.alpha(), ramp) / 255.0
    return color * (1.0 - tint_alpha) + tint_color * tint_alpha


def _ramp(start: int, end: int, ramp: np.ndarray) -> np.ndarray:
    return start + (end - start) * ramp


def _specular(
    color: np.ndarray,
    normal_x: np.ndarray,
    normal_y: np.ndarray,
    bevel: np.ndarray,
    glass: Material,
) -> np.ndarray:
    """Блик по кромке и внутренняя тень — от них появляется толщина.

    Свет падает сверху, поэтому верхняя кромка вспыхивает; нижняя ловит слабый
    отражённый свет, а сразу под верхней кромкой ложится тень от толщины стекла.
    """
    rim = bevel**2

    top_light = np.clip(-normal_y, 0.0, 1.0) ** 5 * rim
    bottom_light = np.clip(normal_y, 0.0, 1.0) ** 7 * rim * 0.45
    highlight = (top_light + bottom_light)[..., None]

    strength = 118.0 if glass.accent_darken else 96.0
    color = color + highlight * strength

    # Тень от толщины: узкая полоса сразу под верхней кромкой.
    shade = (np.clip(-normal_y, 0.0, 1.0) ** 2 * np.clip(bevel - rim, 0.0, 1.0))[..., None]
    return color * (1.0 - shade * 0.22)


def from_image(image: QImage) -> Backdrop | None:
    """Готовит снимок к работе: QImage -> массив float32 в порядке BGR."""
    image = image.convertToFormat(QImage.Format_RGB32)
    width, height = image.width(), image.height()
    if width < 16 or height < 16:
        return None
    stride = image.bytesPerLine() // 4
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(height, stride, 4)
    return Backdrop(pixels[:, :width, :3].astype(np.float32))


def edge_color(glass: Material, top: bool) -> QColor:
    return glass.edge_top if top else glass.edge_bottom
