"""Плашка из стекла Линзы на системном композиторе Windows.

Выбор первого круга лаборатории (design/glass): материал и появление Линзы,
обход света по смене состояния, цвет итогов из «Сияния», думающий диск
Острова. Выглядит как лабораторный WebGL, но собрана из двух слоёв:

- живая середина — спрайт композитора: фон под окном, размытие и тон Apple
  в том же кадре, что и весь экран, поэтому при прокрутке она не отстаёт;
- всё остальное — шейдер D3D11 в свопчейне той же композиции: кромка Линзы,
  которая берёт фон по снимку экрана, тень, блик, цвет итога, значок и
  подпись. Снимок отстаёт на кадр-два, но у кромки фон перевёрнут и сжат, и
  продолжения снаружи у него нет — запоздание видно только на рывках колеса.

Пока форма движется (появление, смена ширины, встряска, морф диска), живая
середина спрятана, и шейдер рисует стекло целиком: середину композитору
отдаём, только когда геометрия устоялась и он успел её применить.

Окно без поверхности перенаправления: снаружи пилюли настоящий стол, а не
его копия. Из захвата оно исключено, иначе шейдер видел бы сам себя, —
поэтому, как и прежде, плашки нет в записи экрана.

Потоки: интерфейсный владеет композитором и рисует подпись средствами Qt;
поток кадров считает пружины и шлёт кадры в темпе композитора (Present с
vsync); поток захвата снимает фон под окном.
"""

from __future__ import annotations

import ctypes
import math
import os
import sys
import threading
import time
from ctypes import POINTER, Structure, byref, c_float, sizeof
from ctypes import wintypes
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np
from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter

from config import UIConfig
from core.state import Stage, Status
from ui import comp, theme
from ui.gpu import Gpu
from ui.lens_shader import HLSL
from ui.live import _GdiGrabber
from ui.motion import Spring, clamp01, ease_in_out, ease_out_cubic, smooth

# ---------- макет, px при 100% ----------

PILL_H = 56
MIN_W = theme.PILL_MIN_WIDTH
MAX_W = theme.PILL_MAX_WIDTH
LISTEN_MIN_W = 320
#: Запас окна вокруг пилюли: тень 0.035·exp(−sd/30) уходит за 1/255 к ~60 px,
#: и сбоку нужно место под встряску ошибки.
MARGIN = 64
ICON = theme.ICON_SIZE
GAP = theme.ICON_GAP
PAD = theme.PADDING_X

# ---------- числа Линзы (design/glass/lens.js) ----------

BASE_W = 250.0          # ширина с «паспортной» толщиной стекла
SWEEP_S = 0.9           # обход света по смене состояния
LIGHT0 = -math.pi / 4   # покой: свет сверху справа
FIT_SLACK = 30.0        # подпись проступает, когда до кромки ~8 px
FROST = 2.4             # радиус диска размытия шейдера; σ ≈ 0.47·r
RESULT_S = 0.52         # прорисовка итогового значка
INSERTED_HOLD_MS = 2200
#: Поле вокруг подписи в её текстуре, px макета. Ореол и размытие появления
#: берут выборки на 6 px вокруг букв; без поля они вылезали за край текстуры,
#: где выборка повторяет крайний столбец, и левый край текста тянулся полосой.
LABEL_PAD = 8

#: Думающий диск (island.js): лепестки по кругу и их глубина в долях радиуса.
LOBES = (5, 7, 4)
LOBE_AMP = (0.1, 0.07, 0.115)

#: Диагностика: окно остаётся видимым для захвата экрана, а фон снимается один
#: раз при появлении — так плашку можно снять скриншотом. Живой захват в этом
#: режиме выключен: он видел бы саму плашку.
_LOOK = bool(os.environ.get("VOICETYPER_LENS_LOOK"))

_BUSY = frozenset({Stage.LOADING, Stage.TRANSCRIBING, Stage.POLISHING})
_THINKING = frozenset({Stage.TRANSCRIBING, Stage.POLISHING})

_ICON_KIND = {
    Stage.LOADING: 1, Stage.LISTENING: 1, Stage.DONE: 2, Stage.ERROR: 3,
    Stage.WARNING: 4, Stage.PAUSED: 5, Stage.CANCELLED: 6,
}


def _rgba(color: QColor) -> tuple[float, float, float, float]:
    return color.redF(), color.greenF(), color.blueF(), color.alphaF()


def _premul(color: QColor) -> tuple[float, float, float, float]:
    """Цвет для шейдера: rgb без умножения, альфа отдельно — умножает сам шейдер."""
    return _rgba(color)


@dataclass(frozen=True)
class _Target:
    """Чего хочет интерфейс: поток кадров сам решает, как туда прийти."""

    version: int = 0
    stage: Stage = Stage.IDLE
    shown: bool = False
    width: float = BASE_W
    disc: bool = False
    thinking: bool = False
    icon: int = 0
    icon_dark: tuple = (1.0, 1.0, 1.0, 1.0)
    icon_light: tuple = (0.0, 0.0, 0.0, 1.0)
    icon_x: float = 0.0
    icon_size: float = ICON
    label_x: float = 0.0
    label_w: float = 0.0


@dataclass(frozen=True)
class _Geometry:
    """Пилюля в пикселях окна и можно ли сейчас отдать середину композитору."""

    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    h: float = 0.0
    interior: bool = False

    def key(self) -> tuple:
        return (round(self.x * 4), round(self.y * 4), round(self.w * 4), round(self.h * 4), self.interior)


class _Params(Structure):
    """Константы шейдера: порядок и смысл — cbuffer Params в ui.lens_shader."""

    _fields_ = [(name, c_float * 4) for name in (
        "view", "pill", "glass", "light", "status", "tone", "label", "label_fx", "icon", "icon_fx",
        "icon_dark", "icon_light", "title_dark", "title_light", "detail_dark", "detail_light",
        "morph", "morph_n")]


# ---------- движение ----------


class _Motion:
    """Пружины плашки — перенос frame() из lens.js, StatusFlash из kit.js и морфа island.js."""

    def __init__(self) -> None:
        self.mat = Spring(0.0, 0.45, 0.8)
        self.w = Spring(BASE_W, 0.5, 0.85)
        self.shake = Spring(0.0, 0.3, 0.35)
        self.think = Spring(0.0, 0.6, 1.0)
        self.tint = Spring(0.0, 0.4, 1.0)
        self.tone = Spring(0.0, 0.25, 1.0)
        self.green = Spring(0.0, 0.12, 1.0)
        self.red = Spring(0.0, 0.12, 1.0)
        self.flower = Spring(0.0, 0.5, 0.8)
        self.morph = Spring(0.0, 0.6, 0.72)
        self.hybrid = 0.0
        self.morph_idx = 0
        self.morph_hold = 0.0
        self.version = -1
        self.stage: Stage | None = None
        self.sweep_at = -10.0
        self.changed_at = -10.0
        self.text_at: float | None = None
        self.swap = False
        self.reveal = 3.0
        self.shake_pending = False
        self.flash_t = -1.0
        self.result_at: float | None = None
        self.label_opacity = 0.0
        self.applied_since: int | None = None

    def step(self, dt: float, now: float, tgt: _Target, light_bg: bool, applied_key, frame: int,
             view: tuple[int, int], S: float, params: _Params) -> tuple[_Geometry, bool]:
        """Шаг пружин и заполнение констант. Возвращает геометрию и «растаяла ли плашка»."""
        shown = tgt.shown
        if tgt.version != self.version:
            from_hidden = self.mat.value < 0.05
            stage_changed = tgt.stage != self.stage or from_hidden
            self.version = tgt.version
            self.stage = tgt.stage
            if shown and stage_changed:
                self.changed_at = now
                self.sweep_at = now
                if from_hidden:
                    # Из невидимого ширина сразу под текст: появление — рост линзы, не растяжение.
                    self.w.snap(tgt.width)
                    self.green.snap(0.0)
                    self.red.snap(0.0)
                fits_now = self.w.value >= tgt.width - FIT_SLACK
                if from_hidden or not fits_now or self.text_at is None:
                    self.text_at = None
                    self.swap = False
                else:
                    # Подпись сменилась в той же ширине: проступает поверх, без пустой капсулы.
                    self.text_at = now
                    self.swap = True
                self.reveal = 6.0 if tgt.stage is Stage.DONE else 3.0
                self.shake_pending = tgt.stage is Stage.ERROR
                self.result_at = now if tgt.icon in (2, 3, 4, 5, 6) else None
                if tgt.stage in (Stage.DONE, Stage.ERROR):
                    self.flash_t = 0.0
                elif tgt.stage is Stage.LISTENING:
                    self.flash_t = -1.0
                    self.green.snap(0.0)
                    self.red.snap(0.0)
            elif shown:
                # Та же стадия с новым текстом (таймер, «Загружаю» → «Прогреваю»).
                if self.text_at is not None and self.w.value < tgt.width - FIT_SLACK:
                    self.text_at = None

        # ---- материализация: на уходе быстрее и без перелёта
        if shown:
            self.mat.tune(0.45, 0.8)
        else:
            self.mat.tune(0.32, 1.0)
        m = self.mat.set(1.0 if shown else 0.0).step(dt)
        mc = clamp01(m)

        if shown:
            self.w.set(tgt.width)
        w = self.w.step(dt)
        if self.shake_pending and tgt.stage is Stage.ERROR and (
            abs(w - tgt.width) < 24.0 or now - self.changed_at > 0.35
        ):
            # Толчок ждёт, пока ширина почти придёт: на фоне сжатия качок терялся.
            self.shake.velocity += 420.0
            self.shake_pending = False
        busy_capsule = tgt.stage is Stage.LOADING and shown
        think = self.think.set(1.0 if busy_capsule else 0.0).step(dt)
        tint = self.tint.set(0.045 if tgt.stage is Stage.ERROR and shown else 0.0).step(dt)
        dx = self.shake.set(0.0).step(dt)
        tone = self.tone.set(1.0 if light_bg else 0.0).step(dt)

        # ---- цвет итога: вспышка с 100 мс, пик ~200 мс, к секунде полосы нет
        flash = 0.0
        if self.flash_t >= 0.0:
            self.flash_t += dt
            fz = max(0.0, self.flash_t - 0.1)
            flash = (1.0 - math.exp(-fz / 0.05)) * math.exp(-fz / 0.36) * 1.5
            if self.flash_t > 2.5:
                self.flash_t = -1.0
        green = self.green.set(1.0 if tgt.stage is Stage.DONE else 0.0).step(dt)
        red = self.red.set(1.0 if tgt.stage is Stage.ERROR else 0.0).step(dt)

        # ---- думающий диск: лепестки только на почти круглом теле
        self.flower.tune(0.55, 0.8) if tgt.thinking else self.flower.tune(0.28, 0.95)
        self.flower.set(1.0 if tgt.thinking and shown and w < PILL_H + 10 and mc > 0.9 else 0.0).step(dt)
        rounded = clamp01(1.0 - (w - PILL_H) / 22.0)
        f = max(0.0, self.flower.value) * rounded
        if (tgt.thinking and self.flower.value < 0.6) or (not tgt.thinking and f < 0.002):
            self.morph_idx = 0
            self.morph.snap(0.0)
            self.morph_hold = 0.0
        mp = self.morph.set(1.0).step(dt)
        if abs(mp - 1.0) < 0.01 and abs(self.morph.velocity) < 0.05:
            self.morph_hold += dt
            if self.morph_hold > 0.35:
                self.morph_idx = (self.morph_idx + 1) % len(LOBES)
                self.morph.snap(0.0)
                self.morph_hold = 0.0
        ia, ib = self.morph_idx, (self.morph_idx + 1) % len(LOBES)
        rot = 0.38 * (ia + self.morph.value) + 0.12 * now

        # ---- геометрия: лёгкий масштаб 0.96 → 1 вместе с материализацией
        scale = 0.96 + 0.04 * m
        h = PILL_H * scale * S
        ww = max(w, PILL_H) * scale * S
        cx = view[0] / 2.0 + dx * S
        cy = view[1] / 2.0

        # ---- оптика: шире — толще (размер^0.3); «думание» дышит только A
        thick = math.pow(max(w / BASE_W, 1.0), 0.3)
        breath = 1.0 + 0.15 * math.sin(2.0 * math.pi * 0.6 * now) * think
        # A идёт как m² (на уходе m³): иначе зеркальная полоса ещё ломала фон,
        # когда тело линзы уже растаяло.
        fade = mc if shown else mc * mc
        amp = 41.0 * thick * breath * fade * (1.0 - 0.25 * f) * S
        bevel = 13.0 * thick * (0.35 + 0.65 * mc) * (1.0 - 0.3 * f) * S

        sw = clamp01((now - self.sweep_at) / SWEEP_S)
        ang = LIGHT0 + 2.0 * math.pi * ease_in_out(sw)
        passing = math.sin(math.pi * sw) if sw < 1.0 else 0.0

        # ---- подпись: последней, только когда форма уже вмещает её целиком
        has_label = tgt.label_w > 0.0
        fits = w >= tgt.width - FIT_SLACK and mc > 0.8
        if shown and fits and self.text_at is None:
            self.text_at = now
        blur = 0.0
        if shown and self.text_at is not None:
            k = now - self.text_at
            gate = smooth(0.8, 0.97, mc)
            if self.swap:
                opacity = (0.4 + 0.6 * smooth(0.0, 0.18, k)) * gate
                blur = 1.5 * (1.0 - smooth(0.0, 0.2, k))
            else:
                opacity = smooth(0.0, 0.22, k) * gate
                blur = self.reveal * (1.0 - smooth(0.0, 0.28, k))
            self.label_opacity = opacity
        else:
            # На уходе подпись держит последнее содержимое и гаснет за ~70 мс.
            self.label_opacity *= math.exp(-dt / 0.03)
        label_opacity = self.label_opacity if has_label else 0.0
        icon_opacity = self.label_opacity if tgt.icon else 0.0
        result = ease_out_cubic(clamp01((now - self.result_at) / RESULT_S)) if self.result_at is not None else 1.0
        dot_breath = 0.5 + 0.5 * math.sin(now * 2.6) if tgt.stage in _BUSY else 1.0

        # ---- живая середина: только в покое и когда композитор её уже показал
        settled = (shown and mc > 0.999 and abs(self.w.velocity) < 2.0 and abs(w - tgt.width) < 0.25
                   and abs(dx) < 0.05 and abs(self.shake.velocity) < 1.0 and f < 0.001 and tint < 0.002)
        geometry = _Geometry(cx - ww / 2.0, cy - h / 2.0, ww, h, settled)
        if settled and applied_key == geometry.key():
            if self.applied_since is None:
                self.applied_since = frame
        else:
            self.applied_since = None
        if self.applied_since is not None and frame - self.applied_since >= 2:
            self.hybrid = min(1.0, self.hybrid + dt / 0.12)
        else:
            self.hybrid = 0.0

        p = params
        p.view[:] = (view[0], view[1], now, S)
        p.pill[:] = (cx, cy, ww, h)
        p.glass[:] = (m, amp, max(bevel, 0.5), self.hybrid)
        p.light[:] = (math.cos(ang), math.sin(ang), 0.2 + 0.3 * passing, passing)
        p.status[:] = (flash, clamp01(green), clamp01(red), 6.0 + 5.0 * min(1.0, flash))
        p.tone[:] = (tint, clamp01(tone), FROST * S, 1.0)
        # Целые пиксели: на дробной позиции билинейная выборка подмыливает буквы.
        pad = math.ceil(LABEL_PAD * S)
        p.label[:] = (round(cx + tgt.label_x * S) - pad, round(cy - PILL_H * S / 2.0) - pad,
                      tgt.label_w * S + 2 * pad, PILL_H * S + 2 * pad)
        p.label_fx[:] = (label_opacity, blur, 0.55, 0.0)
        p.icon[:] = (cx + tgt.icon_x * S, cy, tgt.icon_size * S, float(tgt.icon))
        p.icon_fx[:] = (result, icon_opacity, dot_breath, 0.0)
        p.icon_dark[:] = tgt.icon_dark
        p.icon_light[:] = tgt.icon_light
        p.morph[:] = (f, LOBE_AMP[ia], LOBE_AMP[ib], self.morph.value)
        p.morph_n[:] = (LOBES[ia], LOBES[ib], rot, 0.0)

        vanished = not shown and mc < 0.003 and self.label_opacity < 0.003
        return geometry, vanished


# ---------- окно ----------

_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_CLASS = "VoiceTyperLens"
_wndproc_ref = None


class _WNDCLASSEXW(Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.RegisterClassExW.argtypes = [POINTER(_WNDCLASSEXW)]
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    return user32


def _create_window(width: int, height: int) -> int:
    global _wndproc_ref
    user32 = _user32()
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    instance = kernel32.GetModuleHandleW(None)
    if _wndproc_ref is None:
        @_WNDPROC
        def wndproc(hwnd, msg, wparam, lparam):
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        _wndproc_ref = wndproc
        user32.RegisterClassExW(byref(_WNDCLASSEXW(cbSize=sizeof(_WNDCLASSEXW), lpfnWndProc=_wndproc_ref,
                                                   hInstance=instance, lpszClassName=_CLASS)))
    # NOREDIRECTIONBITMAP | TOPMOST | TOOLWINDOW | NOACTIVATE | TRANSPARENT | LAYERED:
    # всё рисует композиция, поверх всех, не отбирает фокус и пропускает мышь —
    # иначе Ctrl+V ушёл бы в плашку, а не туда, где диктуют.
    ex_style = 0x00200000 | 0x8 | 0x80 | 0x08000000 | 0x20 | 0x00080000
    hwnd = user32.CreateWindowExW(ex_style, _CLASS, "VoiceTyper", 0x80000000,  # WS_POPUP
                                  0, 0, width, height, None, None, instance, None)
    if not hwnd:
        raise OSError(f"CreateWindowExW: {ctypes.get_last_error()}")
    user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
    return hwnd


# ---------- плашка ----------


class LensHud(QObject):
    """Та же роль и тот же интерфейс, что у ui.hud.Hud, — стекло Линзы."""

    _vanished = Signal()

    @classmethod
    def create(cls, cfg: UIConfig) -> "LensHud | None":
        """Плашка или None, если система не тянет: тогда работает прежняя."""
        if sys.platform != "win32":
            return None
        try:
            return cls(cfg)
        except Exception as exc:  # noqa: BLE001 — любая поломка значит «нет стекла», а не падение
            print(f"[lens] стекло Линзы недоступно ({exc}) — работает прежняя плашка")
            return None

    def __init__(self, cfg: UIConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._scale = max(0.75, min(1.6, cfg.hud_scale))
        screens = QGuiApplication.screens()
        max_dpr = max((s.devicePixelRatio() for s in screens), default=1.0)
        # Окно и ресурсы — под самый плотный экран; на остальных пилюля просто меньше.
        top_s = self._scale * max_dpr
        self._view = (int(math.ceil((MAX_W + 2 * MARGIN) * top_s)), int(math.ceil((PILL_H + 2 * MARGIN) * top_s)))
        self._px = self._scale  # физических px на px макета для текущего экрана

        comp.ensure_dispatcher_queue()
        self._user32 = _user32()
        self._hwnd = _create_window(*self._view)
        if not _LOOK and not self._user32.SetWindowDisplayAffinity(self._hwnd, 0x11):  # WDA_EXCLUDEFROMCAPTURE
            self._user32.DestroyWindow(self._hwnd)
            raise OSError("окно не исключается из захвата — шейдер видел бы сам себя")

        self._gpu = Gpu(*self._view, HLSL, sizeof(_Params))
        self._scene = self._gpu.texture(*self._view)
        self._text = self._gpu.texture(*self._view)
        self._build_composition()

        self._telemetry: Callable[[], tuple[float, float]] = lambda: (0.0, 0.0)
        self._status = Status(stage=Stage.IDLE)
        self._lock = threading.Lock()
        self._target = _Target()
        self._raw: np.ndarray | None = None
        self._raw_fresh = False
        self._text_pixels: np.ndarray | None = None
        self._text_fresh = False
        self._light_bg = False
        self._luminance: float | None = None
        self._geometry = _Geometry()
        self._applied_key = None
        self._applied_geometry: _Geometry | None = None
        self._capture_rect = (0, 0, *self._view)
        self._visible = False
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._timer_text = ""

        self._title_font = theme.title_font()
        self._detail_font = theme.detail_font()
        self._timer_font = theme.timer_font()

        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)
        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.dismiss)
        self._vanished.connect(self._on_vanished, Qt.QueuedConnection)
        print("[lens] стекло Линзы: живая середина композитора + кромка шейдером")

    def _build_composition(self) -> None:
        from winrt.windows.foundation.numerics import Vector2
        from winrt.windows.ui.composition import Compositor
        from winrt.windows.ui.composition.interop import create_desktop_window_target

        self._compositor = compositor = Compositor()
        self._comp_target = create_desktop_window_target(compositor, self._hwnd, is_topmost=True)
        root = compositor.create_container_visual()
        root.size = Vector2(*self._view)
        self._comp_target.root = root

        # Живая середина: фон под визуалом → размытие → тон Apple (out = in·1.015 + 0.086).
        # σ — настоящая: «frost 2.4» лаборатории — радиус диска выборок, σ ≈ 0.47·r.
        gain, lift = 1.015, 0.086
        matrix = [gain, 0, 0, 0, 0, gain, 0, 0, 0, 0, gain, 0, 0, 0, 0, 1, lift, lift, lift, 0]
        blur = comp.gaussian_blur(comp.source_parameter("backdrop"), 0.472 * FROST * self._scale)
        tone = comp.color_matrix(blur.as_source, matrix)
        self._backdrop = compositor.create_backdrop_brush()
        brush, self._keep = comp.effect_brush(compositor, tone, {"backdrop": self._backdrop})
        self._keep.append(blur)
        self._interior = compositor.create_sprite_visual()
        self._interior_shape = compositor.create_rounded_rectangle_geometry()
        self._interior.clip = compositor.create_geometric_clip_with_geometry(self._interior_shape)
        self._interior.is_visible = False
        comp.set_sprite_brush(self._interior, brush)
        root.children.insert_at_top(self._interior)

        # Слой шейдера во всё окно: кромка, тень, значок и подпись.
        surface = comp.swapchain_surface(compositor, self._gpu.swapchain)
        self._surface_brush = compositor.create_surface_brush()
        comp.set_brush_surface(self._surface_brush, surface)
        overlay = compositor.create_sprite_visual()
        overlay.size = Vector2(*self._view)
        overlay.brush = self._surface_brush
        root.children.insert_at_top(overlay)
        self._root, self._overlay = root, overlay

    # ---------- внешнее управление ----------

    def set_telemetry(self, source: Callable[[], tuple[float, float]]) -> None:
        """Источник пары «громкость, секунды записи»: таймер в «Слушаю»."""
        self._telemetry = source

    def show_status(self, status: Status) -> None:
        if not self.cfg.hud_enabled:
            return
        if status.stage is Stage.IDLE:
            self.dismiss()
            return

        self._status = status
        self._auto_hide.stop()
        appearing = not self._visible
        if appearing or status.stage is Stage.LISTENING:
            # Новая диктовка могла начаться на другом мониторе.
            self._move_to_screen()
        target = self._layout(status)
        self._hide_interior()
        with self._lock:
            self._target = replace(target, version=self._target.version + 1, shown=True)
        if appearing:
            self._appear()
        if status.is_transient:
            self._auto_hide.start(self.hold_ms(status))

    def hold_ms(self, status: Status) -> int:
        """Сколько держать итог: «Готово» после диктовки — коротко, текст уже вставлен;
        прочее — с запасом на чтение, ~30 мс на знак."""
        if status.stage is Stage.DONE and status.inserted:
            return INSERTED_HOLD_MS
        hold = self.cfg.success_hold_ms
        if status.stage is Stage.DONE and status.detail:
            hold += len(status.detail) * 30
        return min(hold, self.cfg.success_hold_max_ms)

    def dismiss(self) -> None:
        self._auto_hide.stop()
        if not self._visible:
            return
        self._hide_interior()
        with self._lock:
            self._target = replace(self._target, shown=False)

    def hide(self) -> None:
        """Сразу и без анимации — для выхода из приложения."""
        self._auto_hide.stop()
        with self._lock:
            self._target = replace(self._target, shown=False)
        self._shutdown_threads()
        self._hide_window()

    def isVisible(self) -> bool:  # noqa: N802 — совместимость с QWidget-плашкой
        return self._visible

    # ---------- раскладка ----------

    def _layout(self, status: Status) -> _Target:
        stage = status.stage
        S = self._px
        thinking = stage in _THINKING
        disc = thinking or (stage is Stage.DONE and status.inserted)
        icon = 0 if thinking else _ICON_KIND.get(stage, 0)
        accent = theme.ACCENTS.get(stage, theme.ACCENTS[Stage.IDLE])
        # Над светлым цвет значка притемнён: зелёная галочка на белом иначе ~1.5:1.
        dark, light = _premul(accent), _premul(theme.mix(accent, QColor(0, 0, 0), 0.35))

        if disc:
            self._render_label("", "", "")
            size = ICON * 1.3 if icon else ICON
            return _Target(stage=stage, width=float(PILL_H), disc=True, thinking=thinking, icon=icon,
                           icon_dark=dark, icon_light=light, icon_x=0.0, icon_size=size, label_w=0.0)

        title = status.title
        detail = " ".join(status.detail.split())
        timer = self._timer_value() if stage is Stage.LISTENING else ""
        title_font, detail_font, timer_font = (self._scaled(f, S) for f in
                                               (self._title_font, self._detail_font, self._timer_font))
        tm, dm, im = QFontMetrics(title_font), QFontMetrics(detail_font), QFontMetrics(timer_font)
        timer_room = (im.horizontalAdvance("00:00") / S + 16) if stage is Stage.LISTENING else 0.0
        limit = MAX_W - 2 * PAD - ICON - GAP - 12 - timer_room
        text_w = min(limit, max(tm.horizontalAdvance(title) / S, dm.horizontalAdvance(detail) / S if detail else 0))
        column = text_w + timer_room
        block = ICON + GAP + column
        width = block + 2 * PAD + 12
        if stage is Stage.LISTENING:
            width = max(width, LISTEN_MIN_W)
        width = min(MAX_W, max(MIN_W, width))
        self._render_label(title, detail if detail != title else "", timer, text_w, column)
        return _Target(stage=stage, width=float(width), icon=icon, icon_dark=dark, icon_light=light,
                       icon_x=-block / 2.0 + ICON / 2.0, icon_size=ICON,
                       label_x=-block / 2.0 + ICON + GAP, label_w=column)

    @staticmethod
    def _scaled(font: QFont, S: float) -> QFont:
        scaled = QFont(font)
        scaled.setPixelSize(max(1, round(font.pixelSize() * S)))
        return scaled

    def _render_label(self, title: str, detail: str, timer: str, text_w: float = 0.0, column: float = 0.0) -> None:
        """Подпись в текстуру: заголовок в красном канале, вторая строка и таймер — в зелёном.

        Каналы — маски покрытия, цвет и ореол по тону фона добавляет шейдер:
        при смене светлого фона на тёмный текстуру не нужно перерисовывать.
        """
        S = self._px
        width, height = self._view
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        if title or detail or timer:
            image = QImage(pixels.data, width, height, width * 4, QImage.Format_ARGB32_Premultiplied)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            painter.setRenderHint(QPainter.Antialiasing, True)
            title_font, detail_font, timer_font = (self._scaled(f, S) for f in
                                                   (self._title_font, self._detail_font, self._timer_font))
            text_px = int(text_w * S)
            pad = math.ceil(LABEL_PAD * S)
            painter.translate(pad, pad)
            center = PILL_H * S / 2.0
            if title and detail:
                title_box = QRectF(0, center - 18 * S, text_px, 19 * S)
                detail_box = QRectF(0, center - 1 * S, text_px, 17 * S)
            else:
                title_box = detail_box = QRectF(0, 0, text_px, PILL_H * S)
            flags = Qt.AlignVCenter | Qt.AlignLeft
            if title:
                painter.setFont(title_font)
                painter.setPen(QColor(255, 0, 0))
                painter.drawText(title_box, flags, QFontMetrics(title_font).elidedText(title, Qt.ElideRight, text_px))
            if detail:
                painter.setFont(detail_font)
                painter.setPen(QColor(0, 255, 0))
                painter.drawText(detail_box, flags,
                                 QFontMetrics(detail_font).elidedText(detail, Qt.ElideRight, text_px))
            if timer:
                painter.setFont(timer_font)
                painter.setPen(QColor(0, 255, 0))
                painter.drawText(QRectF(0, 0, column * S, PILL_H * S), Qt.AlignVCenter | Qt.AlignRight, timer)
            painter.end()
        with self._lock:
            self._text_pixels = pixels
            self._text_fresh = True

    def _timer_value(self) -> str:
        _level, elapsed = self._telemetry()
        return f"{int(elapsed) // 60}:{int(elapsed) % 60:02d}"

    # ---------- окно и потоки ----------

    def _move_to_screen(self) -> None:
        screen = None
        if self.cfg.hud_follow_cursor:
            screen = QGuiApplication.screenAt(QCursor.pos())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        dpr = screen.devicePixelRatio()
        self._px = self._scale * dpr
        area = screen.availableGeometry()
        margin = self.cfg.hud_margin
        position = self.cfg.hud_position
        half_h = PILL_H * self._scale / 2.0
        half_w = (MAX_W + 2 * MARGIN) * self._scale / 2.0
        if "top" in position:
            cy = area.top() + margin + half_h
        else:
            cy = area.bottom() - margin - half_h
        if "left" in position:
            cx = area.left() + margin + half_w
        elif "right" in position:
            cx = area.right() - margin - half_w
        else:
            cx = area.center().x()
        # Qt хранит у экрана родное начало и логический размер: в физические
        # пиксели переводим смещение от начала экрана.
        origin = screen.geometry().topLeft()
        px = origin.x() + (cx - origin.x()) * dpr
        py = origin.y() + (cy - origin.y()) * dpr
        x = int(round(px - self._view[0] / 2.0))
        y = int(round(py - self._view[1] / 2.0))
        self._user32.SetWindowPos(self._hwnd, wintypes.HWND(-1), x, y, self._view[0], self._view[1],
                                  0x0010)  # SWP_NOACTIVATE
        with self._lock:
            self._capture_rect = (x, y, *self._view)

    def _appear(self) -> None:
        # Первый кадр фона — до показа: дальше его снимает поток захвата.
        grabber = _GdiGrabber()
        try:
            raw = grabber.grab(*self._capture_rect)
        finally:
            grabber.close()
        with self._lock:
            if raw is not None:
                self._raw = raw
                self._raw_fresh = True
                self._light_bg = self._is_light(raw, self._light_bg)
        self._user32.ShowWindow(self._hwnd, 4)  # SW_SHOWNOACTIVATE
        self._visible = True
        self._stop.clear()
        self._threads = [threading.Thread(target=self._render_loop, name="lens-render", daemon=True)]
        if not _LOOK:
            self._threads.append(threading.Thread(target=self._capture_loop, name="lens-capture", daemon=True))
        for thread in self._threads:
            thread.start()
        self._tick.start()

    @Slot()
    def _on_vanished(self) -> None:
        with self._lock:
            shown = self._target.shown
        if shown:
            return  # пока таяла, пришёл новый статус
        self._shutdown_threads()
        self._hide_window()

    def _shutdown_threads(self) -> None:
        self._stop.set()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=1.0)
        self._threads = []

    def _hide_window(self) -> None:
        self._tick.stop()
        self._hide_interior()
        if self._visible:
            self._user32.ShowWindow(self._hwnd, 0)  # SW_HIDE
        self._visible = False

    def _hide_interior(self) -> None:
        self._interior.is_visible = False
        self._applied_geometry = None
        with self._lock:
            self._applied_key = None

    @Slot()
    def _on_tick(self) -> None:
        """Интерфейсный поток: живая середина вслед за потоком кадров и таймер записи."""
        from winrt.windows.foundation.numerics import Vector2, Vector3

        with self._lock:
            geometry = self._geometry
            shown = self._target.shown
        if not shown:
            return
        if geometry.interior:
            if geometry != self._applied_geometry:
                self._interior.offset = Vector3(geometry.x, geometry.y, 0.0)
                self._interior.size = Vector2(geometry.w, geometry.h)
                self._interior_shape.size = Vector2(geometry.w, geometry.h)
                self._interior_shape.corner_radius = Vector2(geometry.h / 2.0, geometry.h / 2.0)
                self._interior.is_visible = True
                self._applied_geometry = geometry
                with self._lock:
                    self._applied_key = geometry.key()
        elif self._applied_geometry is not None:
            self._hide_interior()

        if self._status.stage is Stage.LISTENING:
            timer = self._timer_value()
            if timer != self._timer_text:
                self._timer_text = timer
                self._layout_keep_version(self._status)

    def _layout_keep_version(self, status: Status) -> None:
        """Перерисовка подписи без смены статуса: таймер тикает раз в секунду."""
        target = self._layout(status)
        with self._lock:
            self._target = replace(target, version=self._target.version, shown=self._target.shown)

    # ---------- фоновые потоки ----------

    @staticmethod
    def _is_light(raw: np.ndarray, was_light: bool) -> bool:
        """Светлый ли фон под стеклом — по светимости уже затонированного стекла, с гистерезисом.

        Тонкий подсчёт по прореженной середине: случайная яркая точка не должна
        перекидывать тон подписи.
        """
        h, w = raw.shape[:2]
        middle = raw[h // 3: 2 * h // 3: 2, w // 4: 3 * w // 4: 4, :3].astype(np.float32)
        luminance = float((middle @ np.array([0.0722, 0.7152, 0.2126], dtype=np.float32)).mean() / 255.0)
        glass = luminance * 1.015 + 0.086
        band = 0.05
        if was_light:
            return glass > theme.MATERIAL_THRESHOLD - band
        return glass > theme.MATERIAL_THRESHOLD + band

    def _capture_loop(self) -> None:
        grabber = _GdiGrabber()
        try:
            while not self._stop.is_set():
                with self._lock:
                    rect = self._capture_rect
                raw = grabber.grab(*rect)
                if raw is None or raw.shape[1] != self._view[0] or raw.shape[0] != self._view[1]:
                    time.sleep(0.004)
                    continue
                with self._lock:
                    light = self._is_light(raw, self._light_bg)
                    self._raw = raw
                    self._raw_fresh = True
                    self._light_bg = light
        except Exception as exc:  # noqa: BLE001
            print(f"[lens] захват сломался: {exc}")
        finally:
            grabber.close()

    def _render_loop(self) -> None:
        motion = _Motion()
        params = _Params()
        p = self._params_static(params)
        started = last = time.perf_counter()
        frame = 0
        vanished_sent = False
        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                dt = min(now - last, 0.05)
                last = now
                with self._lock:
                    target = self._target
                    raw = self._raw if self._raw_fresh else None
                    self._raw_fresh = False
                    text = self._text_pixels if self._text_fresh else None
                    self._text_fresh = False
                    light_bg = self._light_bg
                    applied = self._applied_key
                    S = self._px
                if raw is not None:
                    self._gpu.upload(self._scene, raw.ctypes.data, raw.strides[0])
                if text is not None:
                    self._gpu.upload(self._text, text.ctypes.data, text.strides[0])
                geometry, vanished = motion.step(dt, now - started, target, light_bg, applied, frame,
                                                 self._view, S, p)
                with self._lock:
                    self._geometry = geometry
                self._gpu.draw(p, [self._scene, self._text])
                frame += 1
                if vanished:
                    if not vanished_sent:
                        vanished_sent = True
                        self._vanished.emit()
                    time.sleep(0.016)
                else:
                    vanished_sent = False
        except Exception as exc:  # noqa: BLE001
            print(f"[lens] поток кадров упал: {exc}")

    def _params_static(self, params: _Params) -> _Params:
        dark, light = theme.DARK_MATERIAL, theme.LIGHT_MATERIAL
        params.title_dark[:] = _rgba(dark.title)
        params.title_light[:] = _rgba(light.title)
        params.detail_dark[:] = _rgba(dark.detail)
        params.detail_light[:] = _rgba(light.detail)
        return params
