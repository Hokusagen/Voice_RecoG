"""Палитра, метрики и кривые сглаживания HUD.

Оформление держится на двух вещах: полупрозрачное стекло с размытой подложкой
и одно бегущее по контуру свечение. Цвет свечения говорит о стадии, яркость и
скорость — об активности. Никаких спиннеров, точек и бликов: чем меньше в кадре
независимых движений, тем спокойнее плашка читается краем глаза.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

from core.state import Stage


def _c(hex_rgb: str, alpha: int = 255) -> QColor:
    color = QColor(hex_rgb)
    color.setAlpha(alpha)
    return color


# ---------- стекло ----------

SHADOW = _c("#000000", 96)


@dataclass(frozen=True)
class Material:
    """Один вариант стекла: чем и как затонирована размытая подложка."""

    scrim_top: QColor
    scrim_bottom: QColor
    sheen: QColor
    edge_top: QColor
    edge_bottom: QColor
    title: QColor
    detail: QColor
    text_shadow: QColor
    """Подложка под буквами. Позволяет держать стекло прозрачнее: читаемость
    добирается контуром вокруг текста, а не плотностью всей плашки."""

    accent_darken: float = 0.0
    """Насколько притемнить акцентный цвет, чтобы он не выцветал на светлом."""


#: Тёмное стекло — поверх тёмных окон и обоев.
DARK_MATERIAL = Material(
    scrim_top=_c("#171b26", 38),
    scrim_bottom=_c("#0a0c12", 58),
    sheen=_c("#ffffff", 34),
    edge_top=_c("#ffffff", 112),
    edge_bottom=_c("#ffffff", 18),
    title=_c("#f7f8fb", 250),
    detail=_c("#d6dae4", 210),
    text_shadow=_c("#04060a", 185),
)

#: Светлое стекло — поверх светлых документов и редакторов. Без него плашка
#: над белой страницей выглядит просто тёмным прямоугольником, а не стеклом.
LIGHT_MATERIAL = Material(
    scrim_top=_c("#ffffff", 84),
    scrim_bottom=_c("#eef0f4", 108),
    sheen=_c("#ffffff", 60),
    edge_top=_c("#ffffff", 224),
    edge_bottom=_c("#2a3040", 34),
    title=_c("#0f1219", 248),
    detail=_c("#3c4252", 226),
    text_shadow=_c("#ffffff", 190),
    accent_darken=0.22,
)

#: Порог светимости подложки, за которым переключаемся на светлое стекло.
MATERIAL_THRESHOLD = 0.58


def material(luminance: float | None) -> Material:
    """Выбирает стекло по средней светимости того, что под плашкой."""
    if luminance is None:
        return DARK_MATERIAL
    return LIGHT_MATERIAL if luminance >= MATERIAL_THRESHOLD else DARK_MATERIAL

#: Ведущий цвет стадии.
ACCENTS: dict[Stage, QColor] = {
    Stage.IDLE: _c("#9aa2b4"),
    Stage.LOADING: _c("#79b0ff"),
    Stage.LISTENING: _c("#ff5f6d"),
    Stage.TRANSCRIBING: _c("#79b0ff"),
    Stage.POLISHING: _c("#b79cff"),
    Stage.DONE: _c("#4fdca6"),
    Stage.WARNING: _c("#ffb648"),
    Stage.ERROR: _c("#ff6b74"),
    Stage.CANCELLED: _c("#9aa2b4"),
    Stage.PAUSED: _c("#9aa2b4"),
}


def accent(stage: Stage, glass: "Material | None" = None) -> QColor:
    color = ACCENTS.get(stage, ACCENTS[Stage.IDLE])
    if glass is not None and glass.accent_darken:
        return mix(color, QColor(0, 0, 0), glass.accent_darken)
    return color


#: Скорость бега свечения по контуру, оборотов в секунду. Ноль — свечение
#: стоит ровным ободком.
GLOW_SPEED: dict[Stage, float] = {
    Stage.LOADING: 0.26,
    Stage.LISTENING: 0.13,
    Stage.TRANSCRIBING: 0.30,
    Stage.POLISHING: 0.30,
}


# ---------- метрики ----------

PILL_HEIGHT = 56
PILL_MIN_WIDTH = 250
PILL_MAX_WIDTH = 620

PADDING_X = 24
ICON_SIZE = 22
ICON_GAP = 16

SHADOW_BLUR = 24
SHADOW_OFFSET_Y = 10

REVEAL_SLIDE = 22


# ---------- тайминги, мс ----------

REVEAL_MS = 340
HIDE_MS = 260
WIDTH_MS = 300
RESULT_MS = 520
FRAME_MS = 16


# ---------- шрифты ----------

#: Пары «обычное начертание — плотное».
#:
#: Segoe UI стоит первым не по привычке: он вручную отхинтован под мелкие
#: кегли Windows, и на 11–14 пикселях штрихи попадают ровно в пиксельную
#: сетку. Вариативные Inter, Onest, Golos и Manrope инструкций хинтинга не
#: несут, поэтому на тех же кеглях расползаются серой кашей — проверено
#: рендером всех четырёх от 11 до 15 пикселей. Они лежат в assets/fonts и
#: доступны через ui.font, но по умолчанию не берутся.
#:
#: Плотные начертания Segoe UI живут отдельными семействами: просить вес у
#: обычного — значит получить синтетическое утолщение вместо нарисованного.
FONT_FAMILIES = (
    ("Segoe UI", "Segoe UI Semibold"),
    ("Inter", "Inter"),
    ("Onest", "Onest"),
    ("Golos Text", "Golos Text"),
    ("Manrope", "Manrope"),
    ("Tahoma", "Tahoma"),
    ("Arial", "Arial"),
)

_ui_family = ""
_bold_family = ""
_bold_is_family = False
_registered = False


def _assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[2]
    return base / "assets" / "fonts"


def _register_bundled() -> None:
    global _registered
    if _registered:
        return
    _registered = True

    directory = _assets_dir()
    if not directory.is_dir():
        return
    for path in sorted(directory.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(path)) < 0:
            print(f"[theme] шрифт не загрузился: {path.name}")


def init_fonts(preferred: str = "auto") -> str:
    """Подключает шрифты и выбирает семейство. Возвращает выбранное."""
    global _ui_family, _bold_family, _bold_is_family
    _register_bundled()

    available = set(QFontDatabase.families())
    order = list(FONT_FAMILIES)
    if preferred and preferred.lower() != "auto":
        order.insert(0, (preferred, preferred))

    for regular, bold in order:
        if regular not in available:
            continue
        _ui_family = regular
        _bold_is_family = bold != regular and bold in available
        _bold_family = bold if _bold_is_family else regular
        return regular

    _ui_family = _bold_family = ""
    _bold_is_family = False
    return "системный по умолчанию"


def _font(pixel_size: int, *, bold: bool = False) -> QFont:
    family = _bold_family if bold else _ui_family
    font = QFont(family) if family else QFont()
    font.setPixelSize(pixel_size)
    if bold and not _bold_is_family:
        font.setWeight(QFont.DemiBold)
    # Трекинг не трогаем: дробный сдвиг заставляет Qt ставить глифы между
    # пикселями, и отхинтованный шрифт теряет ровно то, ради чего его брали.
    font.setHintingPreference(QFont.PreferFullHinting)
    return font


def title_font() -> QFont:
    """Заголовок: плотное начертание — иначе тонет в просвечивающем фоне."""
    return _font(14, bold=True)


def detail_font() -> QFont:
    """Вторая строка: обычное начертание, иерархию держат вес и цвет.

    Двенадцать пикселей вместо одиннадцати: строка идёт на пониженной
    непрозрачности сквозь стекло, и лишний пиксель заметно спасает читаемость.
    """
    return _font(12)


def timer_font() -> QFont:
    """Цифры таймера — табличные, иначе строка дёргается при смене секунды."""
    font = _font(12)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError, ValueError):
        # Возможность появилась в Qt 6.7; без неё цифры просто пропорциональные.
        pass
    return font


# ---------- сглаживание ----------


def ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def ease_out_back(t: float, overshoot: float = 1.7) -> float:
    c = overshoot + 1.0
    return 1.0 + c * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(a: QColor, b: QColor, t: float) -> QColor:
    t = clamp(t)
    return QColor(
        int(lerp(a.red(), b.red(), t)),
        int(lerp(a.green(), b.green(), t)),
        int(lerp(a.blue(), b.blue(), t)),
        int(lerp(a.alpha(), b.alpha(), t)),
    )


def with_alpha(color: QColor, alpha: float) -> QColor:
    out = QColor(color)
    out.setAlpha(int(clamp(alpha) * 255))
    return out
