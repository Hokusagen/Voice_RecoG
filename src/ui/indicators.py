"""Формы, из которых собран HUD.

Главная — свечение по контуру: единственная непрерывная анимация во всём
интерфейсе. Остальное либо статично, либо проигрывается один раз при смене
состояния.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen

from ui.theme import clamp, ease_out_back, lerp, mix, with_alpha

#: На сколько отрезков режем периметр. Больше — глаже хвост, дороже кадр.
_SEGMENTS = 96

#: Ступеней яркости в хвосте. Соседние отрезки одной ступени рисуются единым
#: путём, поэтому смен пера за кадр — десятки, а не сотни. Мало ступеней —
#: на плавном спаде проступают полосы.
_LEVELS = 34


def _pen(color: QColor, width: float, cap: Qt.PenCapStyle = Qt.RoundCap) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


# ---------- свечение по контуру ----------


@lru_cache(maxsize=64)
def _outline(width: int, height: int, segments: int) -> tuple[tuple[float, float], ...]:
    """Точки, равномерно расставленные по периметру пилюли.

    Считаем аналитически, а не через QPainterPath.pointAtPercent: тот пересчитывает
    длину пути на каждом обращении, а нам нужно полторы сотни точек в кадре.
    Равномерность по длине важна — иначе свечение разгонялось бы на закруглениях.
    """
    radius = height / 2
    straight = max(0.0, width - 2 * radius)
    arc = math.pi * radius
    total = 2 * straight + 2 * arc
    if total <= 0:
        return ()

    points: list[tuple[float, float]] = []
    for index in range(segments):
        distance = total * index / segments
        if distance < straight:  # верхняя грань, слева направо
            points.append((radius + distance, 0.0))
            continue
        distance -= straight
        if distance < arc:  # правое закругление, сверху вниз
            angle = -math.pi / 2 + math.pi * (distance / arc)
            points.append(
                (width - radius + radius * math.cos(angle), radius + radius * math.sin(angle))
            )
            continue
        distance -= arc
        if distance < straight:  # нижняя грань, справа налево
            points.append((width - radius - distance, height))
            continue
        distance -= straight
        angle = math.pi / 2 + math.pi * (distance / arc)  # левое закругление, снизу вверх
        points.append((radius + radius * math.cos(angle), radius + radius * math.sin(angle)))
    return tuple(points)


def draw_perimeter_glow(
    painter: QPainter,
    rect: QRectF,
    color: QColor,
    phase: float,
    *,
    comets: int = 2,
    intensity: float = 1.0,
    base: float = 0.0,
    tail: float = 5.5,
    lead: float = 3.2,
) -> None:
    """Огонёк, бегущий по кромке пилюли, с растянутым назад хвостом.

    Яркость спадает в обе стороны от головы: вперёд быстрее (lead), назад
    медленнее (tail). Односторонний спад давал бы у головы вертикальный скачок
    яркости — при движении он читается как резко обрубленный край полосы.

    comets=0 даёт ровный ободок без движения — так выглядят завершённые
    состояния. base поднимает свечение всей кромки: им показываем громкость,
    не добавляя в кадр ещё одного движущегося объекта.
    """
    if intensity <= 0.01 and base <= 0.01:
        return

    points = _outline(int(rect.width()), int(rect.height()), _SEGMENTS)
    if len(points) < 2:
        return

    count = len(points)
    ahead = tail * lead
    steps = [0] * count
    for index in range(count):
        strength = base
        if comets:
            for comet in range(comets):
                offset = (index / count - phase - comet / comets) % 1.0
                # Больше половины круга «позади» — значит на самом деле впереди.
                signed = offset if offset <= 0.5 else offset - 1.0
                falloff = -signed * tail if signed >= 0.0 else signed * ahead
                strength = max(strength, math.exp(falloff) * intensity)
        steps[index] = int(clamp(strength) * _LEVELS)

    left, top = rect.left(), rect.top()
    highlight = mix(color, QColor(255, 255, 255), 0.55)

    painter.save()
    painter.setBrush(Qt.NoBrush)
    for step, start, end in _runs(steps):
        strength = (step + 0.5) / _LEVELS
        path = QPainterPath(QPointF(left + points[start][0], top + points[start][1]))
        for index in range(start + 1, end + 2):
            x, y = points[index % count]
            path.lineTo(QPointF(left + x, top + y))

        # Голова светлее хвоста — получается не «полоска», а скользящий блик.
        shade = mix(color, highlight, strength * strength)

        # Торцы обязательно плоские: круглые заходят друг на друга, и в местах
        # нахлёста полупрозрачная линия складывается сама с собой — контур
        # превращается в цепочку бусин.
        painter.setPen(_pen(with_alpha(shade, 0.18 * strength), 6.0, Qt.FlatCap))
        painter.drawPath(path)
        painter.setPen(_pen(with_alpha(shade, 0.95 * strength), 1.6, Qt.FlatCap))
        painter.drawPath(path)
    painter.restore()


def _runs(steps: list[int]) -> list[tuple[int, int, int]]:
    """Склеивает соседние отрезки одной яркости в участки (ступень, от, до)."""
    runs: list[tuple[int, int, int]] = []
    start = 0
    for index in range(1, len(steps) + 1):
        if index == len(steps) or steps[index] != steps[start]:
            if steps[start] > 0:
                runs.append((steps[start], start, index - 1))
            start = index
    return runs


# ---------- левый значок ----------


def draw_waveform(
    painter: QPainter, rect: QRectF, color: QColor, levels: list[float], alpha: float = 1.0
) -> None:
    """Тонкая осциллограмма по реальной громкости — единственный «живой» элемент."""
    if not levels or alpha <= 0.01:
        return

    count = len(levels)
    gap_ratio = 0.85
    bar_w = rect.width() / (count + (count - 1) * gap_ratio)
    step = bar_w * (1.0 + gap_ratio)
    center_y = rect.center().y()

    painter.save()
    painter.setPen(Qt.NoPen)
    for index, level in enumerate(levels):
        height = max(bar_w, clamp(level) * rect.height())
        painter.setBrush(QBrush(with_alpha(color, alpha * lerp(0.5, 1.0, clamp(level)))))
        bar = QRectF(rect.left() + index * step, center_y - height / 2, bar_w, height)
        painter.drawRoundedRect(bar, bar_w / 2, bar_w / 2)
    painter.restore()


def draw_dot(painter: QPainter, rect: QRectF, color: QColor, breath: float) -> None:
    """Точка с медленным вдохом-выдохом для стадий обработки."""
    painter.save()
    painter.setPen(Qt.NoPen)
    radius = rect.width() * 0.16
    painter.setBrush(QBrush(with_alpha(color, 0.18 + 0.12 * breath)))
    painter.drawEllipse(rect.center(), radius * 2.1, radius * 2.1)
    painter.setBrush(QBrush(with_alpha(color, lerp(0.6, 1.0, breath))))
    painter.drawEllipse(rect.center(), radius, radius)
    painter.restore()


# ---------- итоговые значки ----------


def draw_check(painter: QPainter, rect: QRectF, color: QColor, progress: float) -> None:
    points = [_at(rect, 0.08, 0.52), _at(rect, 0.38, 0.80), _at(rect, 0.92, 0.20)]
    _stroke(painter, points, color, rect.width() * 0.12, clamp(progress / 0.8))


def draw_cross(painter: QPainter, rect: QRectF, color: QColor, progress: float) -> None:
    width = rect.width() * 0.12
    first = clamp(progress / 0.5)
    if first > 0:
        _stroke(painter, [_at(rect, 0.16, 0.16), _at(rect, 0.84, 0.84)], color, width, first)
    second = clamp((progress - 0.4) / 0.5)
    if second > 0:
        _stroke(painter, [_at(rect, 0.84, 0.16), _at(rect, 0.16, 0.84)], color, width, second)


def draw_warning(painter: QPainter, rect: QRectF, color: QColor, progress: float) -> None:
    grow = clamp(progress / 0.65)
    if grow > 0:
        _stroke(painter, [_at(rect, 0.5, 0.06), _at(rect, 0.5, 0.62)], color, rect.width() * 0.12, grow)
    dot = clamp((progress - 0.65) / 0.35)
    if dot > 0:
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(with_alpha(color, dot)))
        painter.drawEllipse(_at(rect, 0.5, 0.88), rect.width() * 0.07, rect.width() * 0.07)
        painter.restore()


def draw_pause(painter: QPainter, rect: QRectF, color: QColor, progress: float) -> None:
    scale = ease_out_back(clamp(progress), overshoot=1.2)
    if scale <= 0.01:
        return
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(with_alpha(color, clamp(progress))))
    bar_w = rect.width() * 0.24
    height = rect.height() * 0.9 * scale
    for sign in (-1, 1):
        bar = QRectF(0, 0, bar_w, height)
        bar.moveCenter(QPointF(rect.center().x() + sign * bar_w * 1.1, rect.center().y()))
        painter.drawRoundedRect(bar, bar_w / 2, bar_w / 2)
    painter.restore()


def draw_mic(painter: QPainter, rect: QRectF, color: QColor, alpha: float = 1.0) -> None:
    if alpha <= 0.01:
        return
    painter.save()
    shade = with_alpha(color, alpha)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(shade))
    capsule = QRectF(0, 0, rect.width() * 0.40, rect.height() * 0.52)
    capsule.moveCenter(QPointF(rect.center().x(), rect.top() + rect.height() * 0.30))
    painter.drawRoundedRect(capsule, capsule.width() / 2, capsule.width() / 2)

    painter.setBrush(Qt.NoBrush)
    painter.setPen(_pen(shade, max(1.4, rect.width() * 0.09)))
    cradle = QRectF(0, 0, rect.width() * 0.72, rect.height() * 0.66)
    cradle.moveCenter(QPointF(rect.center().x(), rect.top() + rect.height() * 0.38))
    painter.drawArc(cradle, int(200 * 16), int(140 * 16))
    painter.drawLine(_at(rect, 0.5, 0.76), _at(rect, 0.5, 0.96))
    painter.restore()


# ---------- вспомогательное ----------


def _at(rect: QRectF, fx: float, fy: float) -> QPointF:
    return QPointF(rect.left() + rect.width() * fx, rect.top() + rect.height() * fy)


def _stroke(
    painter: QPainter, points: list[QPointF], color: QColor, width: float, progress: float
) -> None:
    """Рисует ломаную, пройдя долю progress от её полной длины."""
    lengths = [math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    if total <= 0 or progress <= 0:
        return

    target = total * clamp(progress)
    path = QPainterPath(points[0])
    walked = 0.0
    for (start, end), length in zip(zip(points, points[1:]), lengths):
        if walked + length <= target:
            path.lineTo(end)
            walked += length
            continue
        fraction = (target - walked) / length
        path.lineTo(
            QPointF(lerp(start.x(), end.x(), fraction), lerp(start.y(), end.y(), fraction))
        )
        break

    painter.save()
    painter.setBrush(Qt.NoBrush)
    painter.setPen(_pen(color, width))
    painter.drawPath(path)
    painter.restore()
