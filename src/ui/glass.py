"""Снятие фона под HUD.

Windows 10 умеет размывать фон окна только через недокументированный
SetWindowCompositionAttribute, и работает это по прямоугольнику окна: у пилюли
появились бы рваные углы, пропала бы мягкая тень и не осталось бы места для
преломления на кромке. Поэтому фон снимаем сами — один раз в момент появления,
пока окно ещё скрыто.

Здесь живёт запасной путь с одним снимком: повторно снимать нельзя — в кадр
попал бы сам HUD. Живой режим (ui/live.py) исключает окно из захвата и потому
может снимать фон каждый кадр.
"""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from ui.liquid import MARGIN, Backdrop, from_image


def capture(pill: QRect) -> Backdrop | None:
    """Снимает участок вокруг плашки и готовит из него стекло.

    Вернёт None, если снять не удалось, — вызывающий код должен уметь
    обойтись сплошной заливкой.
    """
    screen = QApplication.screenAt(pill.center()) or QApplication.primaryScreen()
    if screen is None:
        return None

    # Запас нужен дважды: размытию — чтобы кромка снимка не смешивалась с
    # пустотой, преломлению — чтобы было откуда брать пиксели снаружи плашки.
    region = pill.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)
    inside = region.intersected(screen.geometry())
    if inside != region:
        # У края экрана запаса не хватит, и кромка поедет. Лучше отказаться от
        # стекла, чем показать плашку с рваным краем.
        region = inside
        if region.width() < pill.width() + 8 or region.height() < pill.height() + 8:
            return None

    try:
        grabbed = screen.grabWindow(0, region.x(), region.y(), region.width(), region.height())
    except Exception as exc:
        print(f"[glass] не удалось снять фон: {exc}")
        return None
    if grabbed.isNull():
        return None

    return from_image(grabbed.toImage())
