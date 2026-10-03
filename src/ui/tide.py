"""Прилив голоса: три независимых пласта жидкости в канале пилюли.

Каждый пласт — своя струна (волновое уравнение с затуханием): голос толкает
её в своей точке, которая медленно бродит по длине, — каждый слог даёт
импульс, волна бежит к торцам и отражается от них. Пласты друг о друге не
знают: связанные пружиной, они двигались слишком согласованно и гладко
(заказчик: «зависимости — это игра света и цвета, а не формы»). Их связь —
в шейдере: где ленты пересекаются, свет складывается, а цвета смешиваются.

Длина пилюли здесь — канал, по которому бежит волна: чем длиннее, тем дольше
импульс идёт до торца.

Единицы: x — доля длины канала 0…1, время — секунды, смещение — условное;
шейдер переводит его в долю высоты через tanh, так что крупный всплеск
мягко упирается, а не прошивает стекло.
"""

from __future__ import annotations

import math

import numpy as np

NODES = 48
LAYERS = 3

#: Скорость волны, длин канала в секунду: у каждого пласта своя, чтобы гребни
#: расходились, а не шли строем.
SPEED = (0.95, 0.55, 1.3)
#: Затухание, 1/с: импульс проходит канал раз-другой и гаснет.
DAMPING = (1.6, 1.9, 2.2)
#: Возврат к уровню покоя, 1/с². Концы канала свободные, и у сдвига всего пласта
#: целиком нет возвращающей силы: толчки голоса всегда вверх, и без этой пружины
#: пласт уплывал, а в паузах не оседал.
RESTORE = (26.0, 18.0, 34.0)
#: Импульс слога: на нарастание огибающей слога и на ровное «помешивание» фразой.
ONSET_GAIN = (60.0, 45.0, 38.0)
STIR_GAIN = 7.0
#: Точка толчка бродит у каждого пласта по-своему: частоты и сдвиг фазы.
WANDER = ((0.41, 0.17, 1.0), (0.29, 0.23, 2.6), (0.53, 0.13, 4.1))


class Tide:
    def __init__(self) -> None:
        self.x = np.linspace(0.0, 1.0, NODES)
        self.dx = 1.0 / (NODES - 1)
        self.u = np.zeros((LAYERS, NODES))
        self.v = np.zeros((LAYERS, NODES))
        self.time = 0.0
        self.previous = 0.0

    def reset(self) -> None:
        self.u[:] = 0.0
        self.v[:] = 0.0
        self.previous = 0.0

    def step(self, dt: float, phrase: float, syllable: float) -> None:
        if dt <= 0.0:
            return
        self.time += dt
        t = self.time
        rise = max(0.0, syllable - self.previous) / dt
        self.previous = syllable
        stir = phrase * STIR_GAIN * math.sin(2.0 * math.pi * 1.4 * t)
        forces = []
        for k in range(LAYERS):
            a, b, phase = WANDER[k]
            source = 0.5 + 0.34 * math.sin(a * t + phase) * math.cos(b * t + 1.0 + phase)
            kernel = np.exp(-((self.x - source) / 0.09) ** 2)
            forces.append(kernel * (rise * ONSET_GAIN[k] + stir))

        # Явная схема устойчива при c·h/dx < 1: c до 1.3, dx ≈ 0.021 — шаг не длиннее
        # ~0.016 с; подшаги по 6 мс с запасом.
        steps = max(1, math.ceil(dt / 0.006))
        h = dt / steps
        inv_dx2 = 1.0 / (self.dx * self.dx)
        for _ in range(steps):
            for k in range(LAYERS):
                u = self.u[k]
                # Свободные концы: производная по x на торцах ноль — волна отражается.
                padded = np.concatenate(([u[1]], u, [u[-2]]))
                laplacian = (padded[2:] - 2.0 * u + padded[:-2]) * inv_dx2
                accel = SPEED[k] ** 2 * laplacian - DAMPING[k] * self.v[k] - RESTORE[k] * u + forces[k]
                self.v[k] += accel * h
                self.u[k] += self.v[k] * h

    def heights(self) -> np.ndarray:
        """Смещения всех пластов подряд: LAYERS·NODES чисел для шейдера."""
        return self.u.reshape(-1).astype(np.float32)

    def speeds(self) -> np.ndarray:
        return self.v.reshape(-1).astype(np.float32)
