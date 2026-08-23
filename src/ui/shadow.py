"""Мягкая тень под HUD.

QGraphicsDropShadowEffect не дружит с прозрачным окном верхнего уровня, а
несколько вложенных прямоугольников дают заметные ступеньки. Здесь силуэт
размывается честным box-фильтром (три прохода ≈ гауссиан) и кэшируется:
пересчёт нужен только при смене размера пилюли.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap


def box_blur(values: np.ndarray, radius: int, mode: str = "constant") -> np.ndarray:
    """Скользящее среднее по обеим осям через префиксные суммы — O(n).

    mode="constant" дополняет нулями: так и нужно тени, которая обязана
    сходить на нет за своими границами. Для фотографической подложки нули
    означают чёрный, и по краям снимка появляется тёмная кайма — там нужен
    mode="edge".
    """
    if radius < 1:
        return values
    size = 2 * radius + 1
    out = values
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius + 1, radius)
        cumulative = np.cumsum(np.pad(out, pad, mode=mode), axis=axis, dtype=np.float32)
        if axis == 0:
            out = (cumulative[size:, :] - cumulative[:-size, :]) / size
        else:
            out = (cumulative[:, size:] - cumulative[:, :-size]) / size
    return out


@lru_cache(maxsize=128)
def _render(width: int, height: int, radius: int, blur: int, rgba: int) -> QPixmap:
    pad = blur * 3
    canvas_w, canvas_h = width + pad * 2, height + pad * 2

    silhouette = QImage(canvas_w, canvas_h, QImage.Format_ARGB32)
    silhouette.fill(Qt.transparent)
    painter = QPainter(silhouette)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(0, 0, 0, 255)))
    painter.drawRoundedRect(QRectF(pad, pad, width, height), radius, radius)
    painter.end()

    stride = silhouette.bytesPerLine() // 4
    pixels = np.frombuffer(silhouette.constBits(), dtype=np.uint8).reshape(canvas_h, stride, 4)
    alpha = pixels[:, :canvas_w, 3].astype(np.float32)

    # Три прохода box-фильтра радиусом blur/3 дают почти гауссово размытие.
    step = max(1, blur // 3)
    for _ in range(3):
        alpha = box_blur(alpha, step)

    color = QColor.fromRgba(rgba)
    buffer = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
    buffer[..., 0] = color.blue()
    buffer[..., 1] = color.green()
    buffer[..., 2] = color.red()
    buffer[..., 3] = np.clip(alpha * (color.alpha() / 255.0), 0, 255).astype(np.uint8)

    image = QImage(buffer.data, canvas_w, canvas_h, canvas_w * 4, QImage.Format_ARGB32)
    # copy() отвязывает QImage от временного массива numpy.
    return QPixmap.fromImage(image.copy())


def pill_shadow(width: float, height: float, radius: float, blur: int, color: QColor) -> QPixmap:
    return _render(int(width), int(height), int(radius), int(blur), color.rgba())


def shadow_padding(blur: int) -> int:
    return blur * 3
