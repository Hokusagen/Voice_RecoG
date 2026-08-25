"""Стекло с преломлением.

Размытие плюс тонировка дают матовое стекло — плоское пятно, за которым просто
не видно деталей. У настоящей стеклянной линзы работает кромка: она тоньше
середины, поэтому меньше размывает, зато заметно преломляет — фон у края
подтягивается наружу и растягивается вдоль контура. Плюс на кромке собирается
блик, а на просвет чуть расходятся цвета.

Всё это считается по снимку фона numpy-массивами. Дорогая половина работы —
геометрия: поле расстояний, нормали, толщина и координаты выборки зависят
только от размера пилюли, поэтому считаются один раз на размер и кэшируются
вместе с целочисленными индексами билинейной выборки. На каждый новый снимок
остаются размытия и выборка по готовым индексам — это позволяет пересобирать
стекло не только при появлении плашки, но и на каждом кадре.

Порядок сборки повторяет физику:

1. два размытия — сильное для толстой середины и слабое для тонкой кромки;
2. поле расстояний до контура даёт нормаль и «толщину» стекла в каждой точке;
3. у кромки выборка смещается вдоль нормали наружу — это и есть преломление;
4. каналы смещаются чуть по-разному — дисперсия;
5. тонировка, подъём насыщенности, блик по кромке и внутренняя тень.
"""

from __future__ import annotations

from collections import OrderedDict
from functools import cached_property

import numpy as np
from PySide6.QtGui import QColor, QImage, QPixmap

from ui.shadow import box_blur
from ui.theme import Material

#: Запас вокруг плашки: из него берутся пиксели, которые кромка втягивает внутрь.
MARGIN = 44

_THIN_BLUR = 2
"""Размытие кромки — она тоньше и почти не рассеивает."""

_REFRACT = 13.0
"""Максимальный сдвиг выборки на кромке, пикселей."""

_DISPERSION = 0.07
"""Расхождение каналов на кромке — красный преломляется слабее синего."""

_EDGE = 15.0
"""Ширина скошенной кромки, пикселей."""


def _blur_thick(source: np.ndarray) -> np.ndarray:
    """Сильное размытие середины — там стекло толстое.

    Сила подобрана под прежний квази-гауссиан с радиусом 6: сильнее — и фон
    превращается в ровное пятно, стекло перестаёт читаться как стекло, потому
    что сквозь него уже нечего узнавать.

    Считается на половинном разрешении: стоимость box-фильтра определяется
    числом проходов, а не радиусом, поэтому экономит не радиус, а площадь —
    вчетверо меньше пикселей. Ступенчатый апскейл через repeat под таким
    размытием не читается.
    """
    height, width = source.shape[:2]
    half_h, half_w = height // 2, width // 2
    even = source[: half_h * 2, : half_w * 2]
    half = (
        even[0::2, 0::2] + even[1::2, 0::2] + even[0::2, 1::2] + even[1::2, 1::2]
    ) * np.float32(0.25)

    blurred = np.empty_like(half)
    for channel in range(3):
        values = half[..., channel]
        for _ in range(2):
            values = box_blur(values, 1, mode="edge")
        blurred[..., channel] = values

    out = np.empty_like(source)
    out[0 : half_h * 2 : 2, 0 : half_w * 2 : 2] = blurred
    out[1 : half_h * 2 : 2, 0 : half_w * 2 : 2] = blurred
    out[0 : half_h * 2 : 2, 1 : half_w * 2 : 2] = blurred
    out[1 : half_h * 2 : 2, 1 : half_w * 2 : 2] = blurred
    if half_h * 2 != height:
        out[-1] = out[-2]
    if half_w * 2 != width:
        out[:, -1] = out[:, -2]
    return out


def _blur_thin(source: np.ndarray) -> np.ndarray:
    """Лёгкое размытие кромки: один проход box-фильтра того же сигма.

    Кромку видно в упор, поэтому разрешение не трогаем; вместо трёх проходов —
    один с полным радиусом: разница между box и квази-гауссианом на радиусе 2
    неразличима, а стоит втрое дешевле.
    """
    out = np.empty_like(source)
    for channel in range(3):
        out[..., channel] = box_blur(source[..., channel], _THIN_BLUR, mode="edge")
    return out


def _rounded_box_sdf(xx: np.ndarray, yy: np.ndarray, half_w: float, half_h: float, radius: float):
    """Расстояние со знаком до контура пилюли: внутри отрицательное."""
    qx = np.abs(xx) - (half_w - radius)
    qy = np.abs(yy) - (half_h - radius)
    outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return outside + inside - radius


class _Sampler:
    """Билинейная выборка с предрасчитанными индексами.

    Координаты выборки зависят только от геометрии пилюли, поэтому четыре
    целочисленных соседа и дробные веса считаются один раз. На кадр остаются
    четыре gather-а и три лерпа. Веса держим во float32: NumPy 2 при вычитании
    int32 из float32 раздувает результат до double, и весь конвейер после
    этого работал бы в двойной точности — вдвое больше трафика памяти ради
    разницы меньше одной градации яркости.
    """

    __slots__ = ("_i00", "_i10", "_fx", "_ofx", "_fy", "_ofy")

    def __init__(self, x: np.ndarray, y: np.ndarray, source_w: int, source_h: int) -> None:
        x = np.clip(x, 0.0, source_w - 1.001)
        y = np.clip(y, 0.0, source_h - 1.001)
        x0 = x.astype(np.int32)
        y0 = y.astype(np.int32)
        self._fx = x - x0.astype(np.float32)
        self._fy = y - y0.astype(np.float32)
        self._ofx = 1.0 - self._fx
        self._ofy = 1.0 - self._fy
        self._i00 = y0 * source_w + x0
        self._i10 = self._i00 + source_w

    def channel(self, flat: np.ndarray, index: int) -> np.ndarray:
        """Выборка одного канала. flat — снимок, вытянутый в (H*W, каналы)."""
        v00 = flat[self._i00, index]
        v01 = flat[self._i00 + 1, index]
        v10 = flat[self._i10, index]
        v11 = flat[self._i10 + 1, index]
        top = v00 * self._ofx + v01 * self._fx
        bottom = v10 * self._ofx + v11 * self._fx
        return top * self._ofy + bottom * self._fy


class _Geometry:
    """Всё, что в сборке стекла не зависит от содержимого снимка.

    Помимо толщины и готовой альфы сюда же сложены блик с внутренней тенью:
    от материала в них остаётся один скалярный множитель.
    """

    __slots__ = ("bevel", "one_minus_bevel", "alpha", "highlight", "shade_mult",
                 "thick_offset", "thick_sampler", "thin_samplers")

    def __init__(self, width: int, height: int, source_w: int, source_h: int) -> None:
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
        self.bevel = (1.0 - thickness) ** 1.7
        self.one_minus_bevel = 1.0 - self.bevel

        # Преломление: у кромки берём пиксели снаружи и втягиваем внутрь.
        offset = _REFRACT * self.bevel
        self.thin_samplers = tuple(
            _Sampler(
                src_x + normal_x * (offset * spread),
                src_y + normal_y * (offset * spread),
                source_w,
                source_h,
            )
            for spread in (1.0 + _DISPERSION, 1.0, 1.0 - _DISPERSION)
        )

        # Середина смотрит сквозь стекло без смещения. Когда пилюля и снимок
        # одной чётности, смещение целое и выборка вырождается в срез массива.
        offset_x = center_x - half_w
        offset_y = center_y - half_h
        if (
            offset_x.is_integer()
            and offset_y.is_integer()
            and offset_x >= 0
            and offset_y >= 0
            and offset_x + width <= source_w - 1
            and offset_y + height <= source_h - 1
        ):
            self.thick_offset: tuple[int, int] | None = (int(offset_y), int(offset_x))
            self.thick_sampler = None
        else:
            self.thick_offset = None
            self.thick_sampler = _Sampler(src_x, src_y, source_w, source_h)

        # Блик по кромке и внутренняя тень — от них появляется толщина. Свет
        # падает сверху: верхняя кромка вспыхивает, нижняя ловит слабый
        # отражённый свет, а под верхней ложится тень от толщины стекла.
        rim = self.bevel**2
        top_light = np.clip(-normal_y, 0.0, 1.0) ** 5 * rim
        bottom_light = np.clip(normal_y, 0.0, 1.0) ** 7 * rim * 0.45
        self.highlight = (top_light + bottom_light)[..., None]
        shade = (np.clip(-normal_y, 0.0, 1.0) ** 2 * np.clip(self.bevel - rim, 0.0, 1.0))[..., None]
        self.shade_mult = 1.0 - shade * 0.22

        # Сглаженный край: поле расстояний даёт готовую полупрозрачную кромку.
        self.alpha = (np.clip(0.5 - distance, 0.0, 1.0) * 255.0).astype(np.uint8)


#: Живых размеров немного: ширина анимируется с шагом в восемь пикселей, высота
#: меняется только в момент появления. Дюжины хватает, чтобы не пересчитывать.
_GEOMETRY_LIMIT = 12
_geometry_cache: OrderedDict[tuple[int, int, int, int], _Geometry] = OrderedDict()


def _geometry(width: int, height: int, source_w: int, source_h: int) -> _Geometry:
    key = (width, height, source_w, source_h)
    cached = _geometry_cache.get(key)
    if cached is None:
        cached = _Geometry(width, height, source_w, source_h)
        _geometry_cache[key] = cached
        if len(_geometry_cache) > _GEOMETRY_LIMIT:
            _geometry_cache.popitem(last=False)
    else:
        _geometry_cache.move_to_end(key)
    return cached


def _material_key(glass: Material) -> tuple:
    """Ключ кэша по цветам, а не по id: живой режим на переходах между тёмным
    и светлым стеклом создаёт временные смеси, чей id нельзя запоминать."""
    return (glass.scrim_top.rgba(), glass.scrim_bottom.rgba(), glass.accent_darken)


#: Тонировочные таблицы зависят только от высоты пилюли и материала.
_tint_cache: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


def _tint_tables(glass: Material, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Вертикальный градиент тонировки: (1 - альфа) и уже умноженный цвет."""
    key = (height, *_material_key(glass))
    cached = _tint_cache.get(key)
    if cached is None:
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
        cached = (1.0 - tint_alpha, tint_color * tint_alpha)
        _tint_cache[key] = cached
    return cached


class Backdrop:
    """Снимок фона под плашкой и собранные из него стёкла разных размеров."""

    def __init__(self, raw: np.ndarray) -> None:
        self._raw = raw
        self._thick = _blur_thick(raw)
        self._thin = _blur_thin(raw)
        self._cache: dict[tuple[int, int, int], QPixmap] = {}

    @cached_property
    def luminance(self) -> float:
        """Светимость по формуле яркости: по ней выбирается светлое или тёмное
        стекло. Считаем по размытой середине — случайная яркая точка на фоне
        не должна перекидывать материал."""
        weights = np.array([0.0722, 0.7152, 0.2126], dtype=np.float32)  # BGR
        return float((self._thick * weights).sum(axis=-1).mean() / 255.0)

    def render(self, width: int, height: int, glass: Material) -> QPixmap | None:
        """Готовое стекло размером width x height. Считается один раз на размер."""
        key = (width, height, *_material_key(glass))
        cached = self._cache.get(key)
        if cached is None:
            image = self.build_image(width, height, glass)
            if image is None:
                return None
            cached = QPixmap.fromImage(image)
            self._cache[key] = cached
        return cached

    # ---------- сборка ----------

    def build_image(self, width: int, height: int, glass: Material) -> QImage | None:
        """Собирает стекло в QImage — без кэша, пригодно для пересборки на кадр."""
        source_h, source_w = self._raw.shape[:2]
        if width < 8 or height < 8 or width + 2 > source_w or height + 2 > source_h:
            return None

        geometry = _geometry(width, height, source_w, source_h)

        if geometry.thick_offset is not None:
            top, left = geometry.thick_offset
            thick = self._thick[top : top + height, left : left + width]
        else:
            flat_thick = self._thick.reshape(-1, 3)
            thick = np.stack(
                [geometry.thick_sampler.channel(flat_thick, index) for index in range(3)],
                axis=-1,
            )

        # Кромка тонкая — почти не рассеивает; середина толстая — размывает.
        flat_thin = self._thin.reshape(-1, 3)
        channels = [
            sampler.channel(flat_thin, index) * geometry.bevel
            + thick[..., index] * geometry.one_minus_bevel
            for index, sampler in enumerate(geometry.thin_samplers)
        ]
        color = np.stack(channels, axis=-1)

        color = _saturate(color, 1.22)
        one_minus_alpha, tint_add = _tint_tables(glass, height)
        color = color * one_minus_alpha + tint_add
        # 96 у тёмного стекла, 118 у светлого; линейно между ними, чтобы блик
        # не прыгал на переходах живого материала.
        strength = 96.0 + glass.accent_darken * 100.0
        color = color + geometry.highlight * strength
        color = color * geometry.shade_mult

        buffer = np.empty((height, width, 4), dtype=np.uint8)
        buffer[..., :3] = np.clip(color, 0, 255).astype(np.uint8)
        buffer[..., 3] = geometry.alpha

        image = QImage(buffer.data, width, height, width * 4, QImage.Format_ARGB32)
        return image.copy()


def _saturate(color: np.ndarray, amount: float) -> np.ndarray:
    """Стекло чуть подкрашивает то, что за ним, — иначе фон выглядит вялым."""
    grey = color.mean(axis=-1, keepdims=True)
    return grey + (color - grey) * amount


def _ramp(start: int, end: int, ramp: np.ndarray) -> np.ndarray:
    return start + (end - start) * ramp


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
