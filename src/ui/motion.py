"""Пружины и кривые для движения плашки.

Перенос Spring из design/glass/harness.js без изменений: в лаборатории
движение подобрано на этих числах, и любая другая интеграция дала бы другой
перелёт. При смене цели на лету пружина сохраняет скорость — так у Apple.
"""

from __future__ import annotations

import math


class Spring:
    """Пружина в терминах SwiftUI: response — период, с; damping — доля критического."""

    __slots__ = ("value", "target", "velocity", "response", "damping")

    def __init__(self, value: float = 0.0, response: float = 0.45, damping: float = 0.72) -> None:
        self.value = value
        self.target = value
        self.velocity = 0.0
        self.response = response
        self.damping = damping

    def set(self, target: float) -> "Spring":
        self.target = target
        return self

    def snap(self, value: float) -> "Spring":
        self.value = self.target = value
        self.velocity = 0.0
        return self

    def tune(self, response: float, damping: float) -> "Spring":
        self.response = response
        self.damping = damping
        return self

    def step(self, dt: float) -> float:
        omega = 2.0 * math.pi / self.response
        k = omega * omega
        c = 2.0 * self.damping * omega
        # Шаг не длиннее 1/240 с: на редких кадрах явная схема иначе разносит.
        n = max(1, math.ceil(dt * 240.0))
        h = dt / n
        for _ in range(n):
            a = -k * (self.value - self.target) - c * self.velocity
            self.velocity += a * h
            self.value += self.velocity * h
        return self.value


def clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def smooth(a: float, b: float, x: float) -> float:
    t = clamp01((x - a) / (b - a))
    return t * t * (3.0 - 2.0 * t)


def ease_in_out(x: float) -> float:
    """Кубическая: свет трогается и останавливается мягко — поворот предмета, а не бег точки."""
    return 4.0 * x * x * x if x < 0.5 else 1.0 - (-2.0 * x + 2.0) ** 3 / 2.0


def ease_out_cubic(x: float) -> float:
    return 1.0 - (1.0 - x) ** 3
