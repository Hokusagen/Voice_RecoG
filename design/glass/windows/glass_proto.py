"""Прототип плашки на системном композиторе Windows (Windows.UI.Composition).

Стекло — живой фон под окном, размытый самим композитором (BackdropBrush +
GaussianBlur, см. comp_blur.py): кадр стекла собирается вместе со всем экраном,
отставать нечему, и «Эффекты прозрачности» Windows не нужны. Все движения —
пружины и ключевые кадры, которые считает композитор, а не Python: Python лишь
ставит цели, так что плашка не дёргается, даже когда процесс занят.

Текст рисует Qt в прозрачном окне поверх: в композиции для текста нужен
Direct2D, а для пробы движка он не важен.

    venv\\Scripts\\python.exe glass_proto.py          — гоняет состояния по кругу
    venv\\Scripts\\python.exe glass_proto.py --hold   — держит «Слушаю»: прокручивайте под ним
"""

from __future__ import annotations

import argparse
import ctypes
import math
import sys
import time
from ctypes import wintypes
from datetime import timedelta
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

parser = argparse.ArgumentParser()
parser.add_argument("--hold", action="store_true", help="держать «Слушаю» для проверки прокруткой")
parser.add_argument("--minutes", type=float, default=6.0)
args = parser.parse_args()

app = QApplication(sys.argv)

from winrt.windows.foundation.numerics import Vector2, Vector3  # noqa: E402
from winrt.windows.ui import Color  # noqa: E402
from winrt.windows.ui.composition import (  # noqa: E402
    AnimationIterationBehavior,
    CompositionMappingMode,
    Compositor,
)
from winrt.windows.ui.composition.interop import create_desktop_window_target  # noqa: E402

import comp_blur  # noqa: E402

# ---------- окно под композицию ----------

user32 = ctypes.WinDLL("user32", use_last_error=True)


class _DQO(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("threadType", ctypes.c_int), ("apartmentType", ctypes.c_int)]


_dispatcher = ctypes.c_void_p()
ctypes.WinDLL("CoreMessaging").CreateDispatcherQueueController(
    _DQO(ctypes.sizeof(_DQO), 2, 0), ctypes.byref(_dispatcher)  # текущий поток, COM уже поднял Qt
)

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t


@WNDPROC
def _wndproc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
    ]


_kernel32 = ctypes.WinDLL("kernel32")
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_hinst = _kernel32.GetModuleHandleW(None)
user32.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
user32.RegisterClassExW(ctypes.byref(_WNDCLASSEXW(cbSize=ctypes.sizeof(_WNDCLASSEXW), lpfnWndProc=_wndproc,
                                                   hInstance=_hinst, lpszClassName="VoiceTyperGlassProto")))
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]

WIN_W, WIN_H = 760, 170
CX, CY = WIN_W / 2.0, WIN_H / 2.0
area = QGuiApplication.primaryScreen().availableGeometry()
WIN_X = area.center().x() - WIN_W // 2
WIN_Y = area.bottom() - 96 - 28 - WIN_H // 2  # центр пилюли там же, где у нынешней плашки

# Без поверхности перенаправления (всё рисует композиция), поверх всех, без
# фокуса и прозрачное для мыши — как нынешний HUD.
_EX = 0x00200000 | 0x8 | 0x80 | 0x08000000 | 0x20 | 0x00080000
hwnd = user32.CreateWindowExW(_EX, "VoiceTyperGlassProto", "glass", 0x80000000,
                              WIN_X, WIN_Y, WIN_W, WIN_H, None, None, _hinst, None)
user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)

# ---------- сцена ----------

compositor = Compositor()
target = create_desktop_window_target(compositor, hwnd, is_topmost=False)
root = compositor.create_container_visual()
root.relative_size_adjustment = Vector2(1, 1)
target.root = root

p = compositor.create_property_set()
for _name, _value in (("W", 250.0), ("H", 56.0), ("Reveal", 0.0), ("Level", 0.0), ("Swell", 0.0),
                      ("Bob", 0.0), ("Shake", 0.0), ("Glow", 0.0), ("GlowVoice", 0.0)):
    p.insert_scalar(_name, _value)


def expr(text: str):
    animation = compositor.create_expression_animation_with_expression(text)
    animation.set_reference_parameter("p", p)
    return animation


HEIGHT = "(p.H + p.Swell * p.Level)"
SIZE = f"Vector2(p.W, {HEIGHT})"


def pill_geometry(inset: float = 0.0):
    geometry = compositor.create_rounded_rectangle_geometry()
    if inset:
        geometry.offset = Vector2(inset, inset)
    geometry.start_animation("Size", expr(f"Vector2(p.W - {2 * inset}, {HEIGHT} - {2 * inset})"))
    geometry.start_animation("CornerRadius", expr(f"Vector2(({HEIGHT} - {2 * inset}) / 2, ({HEIGHT} - {2 * inset}) / 2)"))
    return geometry


def clipped_sprite():
    sprite = compositor.create_sprite_visual()
    sprite.start_animation("Size", expr(SIZE))
    sprite.clip = compositor.create_geometric_clip_with_geometry(pill_geometry())
    return sprite


pill = compositor.create_container_visual()
pill.start_animation("Size", expr(SIZE))
pill.start_animation("Offset", expr(
    f"Vector3({CX} - p.W / 2 + p.Shake, {CY} - {HEIGHT} / 2 + (1 - p.Reveal) * 14 - p.Bob * 2.2, 0)"))
pill.start_animation("CenterPoint", expr(f"Vector3(p.W / 2, {HEIGHT} / 2, 0)"))
pill.start_animation("Scale", expr("Vector3(0.9 + 0.1 * p.Reveal, 0.9 + 0.1 * p.Reveal, 1)"))
root.children.insert_at_top(pill)

# Стекло: живой фон под окном, размытый композитором.
glass = clipped_sprite()
backdrop = compositor.create_backdrop_brush()
_blur_brush, _keep_blur = comp_blur.blurred_backdrop_brush(compositor, backdrop, deviation=18.0)
comp_blur.set_sprite_brush(glass, _blur_brush)
pill.children.insert_at_top(glass)


def white(alpha: int) -> Color:
    return Color(a=alpha, r=255, g=255, b=255)


def gradient(stops, vertical: bool = True):
    brush = compositor.create_linear_gradient_brush()
    brush.mapping_mode = CompositionMappingMode.RELATIVE
    brush.start_point = Vector2(0.5, 0.0) if vertical else Vector2(0.0, 0.5)
    brush.end_point = Vector2(0.5, 1.0) if vertical else Vector2(1.0, 0.5)
    for offset, color in stops:
        brush.color_stops.append(compositor.create_color_gradient_stop_with_offset_and_color(offset, color))
    return brush


# Дымчатая тонировка: белый текст читается и над белым документом.
lower = compositor.create_shape_visual()
lower.start_animation("Size", expr(SIZE))
tint = compositor.create_sprite_shape_with_geometry(pill_geometry())
tint.fill_brush = gradient([(0.0, Color(a=138, r=22, g=23, b=30)), (1.0, Color(a=160, r=14, g=15, b=20))])
lower.shapes.append(tint)
pill.children.insert_at_top(lower)

# Свет стадии внутри стекла — вместо бегущей по кромке кометы.
light = clipped_sprite()
light_brush = compositor.create_radial_gradient_brush()
light_brush.mapping_mode = CompositionMappingMode.RELATIVE
light_brush.ellipse_center = Vector2(0.5, 0.55)
light_brush.ellipse_radius = Vector2(0.42, 1.35)
light_core = compositor.create_color_gradient_stop_with_offset_and_color(0.0, Color(a=255, r=255, g=95, b=109))
light_edge = compositor.create_color_gradient_stop_with_offset_and_color(1.0, Color(a=0, r=255, g=95, b=109))
light_brush.color_stops.append(light_core)
light_brush.color_stops.append(light_edge)
light.brush = light_brush
light.start_animation("Opacity", expr("Clamp(p.Glow + p.GlowVoice * p.Level, 0, 1)"))
pill.children.insert_at_top(light)

# Блик сверху и волосяная кромка: толщина стекла без рамки-гирлянды.
upper = compositor.create_shape_visual()
upper.start_animation("Size", expr(SIZE))
sheen = compositor.create_sprite_shape_with_geometry(pill_geometry())
sheen.fill_brush = gradient([(0.0, white(40)), (0.5, white(0))])
rim = compositor.create_sprite_shape_with_geometry(pill_geometry(inset=0.5))
rim.stroke_brush = gradient([(0.0, white(125)), (0.5, white(38)), (1.0, white(70))])
rim.stroke_thickness = 1.0
upper.shapes.append(sheen)
upper.shapes.append(rim)
pill.children.insert_at_top(upper)

# Появление и исчезновение — прозрачностью всей пилюли.
pill.start_animation("Opacity", expr("Clamp(p.Reveal, 0, 1)"))

# ---------- движения: цели ставит Python, считает композитор ----------

_in_out = compositor.create_cubic_bezier_easing_function(Vector2(0.45, 0.0), Vector2(0.55, 1.0))
_ease_in = compositor.create_cubic_bezier_easing_function(Vector2(0.5, 0.0), Vector2(0.9, 0.4))


def spring(name: str, value: float, damping: float = 0.72, period_ms: float = 55.0, owner=None) -> None:
    animation = compositor.create_spring_scalar_animation()
    animation.final_value = float(value)
    animation.damping_ratio = damping
    animation.period = timedelta(milliseconds=period_ms)
    (owner or p).start_animation(name, animation)


def frames(name: str, points, ms: float, forever: bool = False, easing=None, owner=None) -> None:
    animation = compositor.create_scalar_key_frame_animation()
    for progress, value in points:
        if easing is None:
            animation.insert_key_frame(progress, float(value))
        else:
            animation.insert_key_frame_with_easing_function(progress, float(value), easing)
    animation.duration = timedelta(milliseconds=ms)
    if forever:
        animation.iteration_behavior = AnimationIterationBehavior.FOREVER
    (owner or p).start_animation(name, animation)


def light_color(color: QColor, ms: float = 260.0) -> None:
    for stop, alpha in ((light_core, 255), (light_edge, 0)):
        animation = compositor.create_color_key_frame_animation()
        animation.insert_key_frame(1.0, Color(a=alpha, r=color.red(), g=color.green(), b=color.blue()))
        animation.duration = timedelta(milliseconds=ms)
        stop.start_animation("Color", animation)


def drift(active: bool) -> None:
    """Свет медленно переливается вдоль пилюли — единственное движение, пока ждём."""
    if active:
        animation = compositor.create_vector2_key_frame_animation()
        animation.insert_key_frame_with_easing_function(0.0, Vector2(0.28, 0.55), _in_out)
        animation.insert_key_frame_with_easing_function(0.5, Vector2(0.72, 0.55), _in_out)
        animation.insert_key_frame_with_easing_function(1.0, Vector2(0.28, 0.55), _in_out)
        animation.duration = timedelta(milliseconds=2600)
        animation.iteration_behavior = AnimationIterationBehavior.FOREVER
        light_brush.start_animation("EllipseCenter", animation)
    else:
        light_brush.stop_animation("EllipseCenter")
        animation = compositor.create_vector2_key_frame_animation()
        animation.insert_key_frame(1.0, Vector2(0.5, 0.55))
        animation.duration = timedelta(milliseconds=300)
        light_brush.start_animation("EllipseCenter", animation)


# ---------- текст поверх (Qt) ----------

ACCENT = {
    "listening": QColor("#ff5f6d"),
    "transcribing": QColor("#79b0ff"),
    "polishing": QColor("#b79cff"),
    "done": QColor("#4fdca6"),
    "error": QColor("#ff6b74"),
}


class Label(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setGeometry(WIN_X, WIN_Y, WIN_W, WIN_H)
        self.title_font = QFont("Segoe UI", 10)
        self.title_font.setPixelSize(14)
        self.title_font.setWeight(QFont.DemiBold)
        self.detail_font = QFont("Segoe UI")
        self.detail_font.setPixelSize(13)
        self.title, self.detail, self.icon, self.color = "", "", None, QColor("white")
        self.opacity = 0.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.valueChanged.connect(self._set_opacity)

    def _set_opacity(self, value) -> None:
        self.opacity = float(value)
        self.update()

    def fade(self, to: float, ms: int = 180) -> None:
        self._fade.stop()
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.opacity)
        self._fade.setEndValue(to)
        self._fade.start()

    def width_for(self, title: str, detail: str) -> float:
        width = 26 + 14 + 10 + QFontMetrics(self.title_font).horizontalAdvance(title) + 26
        if detail:
            width += 10 + QFontMetrics(self.detail_font).horizontalAdvance(detail)
        return max(200.0, min(620.0, width))

    def paintEvent(self, _event) -> None:
        if self.opacity <= 0.01 or not self.title:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setOpacity(self.opacity)
        title_w = QFontMetrics(self.title_font).horizontalAdvance(self.title)
        detail_w = QFontMetrics(self.detail_font).horizontalAdvance(self.detail) if self.detail else 0
        group = 14 + 10 + title_w + (10 + detail_w if self.detail else 0)
        x = CX - group / 2
        self._paint_icon(painter, QPointF(x + 7, CY))
        x += 24
        painter.setFont(self.title_font)
        painter.setPen(QColor(255, 255, 255, 240))
        painter.drawText(QRectF(x, CY - 12, title_w + 2, 24), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        if self.detail:
            painter.setFont(self.detail_font)
            painter.setPen(QColor(255, 255, 255, 165))
            painter.drawText(QRectF(x + title_w + 10, CY - 12, detail_w + 2, 24),
                             Qt.AlignVCenter | Qt.AlignLeft, self.detail)

    def _paint_icon(self, painter: QPainter, c: QPointF) -> None:
        if self.icon == "dot":
            painter.setPen(Qt.NoPen)
            painter.setBrush(self.color)
            painter.drawEllipse(c, 4.0, 4.0)
        elif self.icon == "check":
            pen = QPen(self.color, 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath(QPointF(c.x() - 5, c.y()))
            path.lineTo(c.x() - 1.5, c.y() + 3.8)
            path.lineTo(c.x() + 5.5, c.y() - 4.2)
            painter.drawPath(path)
        elif self.icon == "cross":
            pen = QPen(self.color, 2.0, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
            painter.drawLine(QPointF(c.x() + 4, c.y() - 4), QPointF(c.x() - 4, c.y() + 4))


label = Label()

# ---------- голос ----------

_voice = {"level": 0.0, "mic": False}


def _loudness(rms: float) -> float:
    if rms <= 1e-5:
        return 0.0
    return max(0.0, min(1.0, (20.0 * math.log10(rms) + 48.0) / 36.0))


try:
    import sounddevice as sd

    def _on_audio(indata, _frames, _time, _status):
        _voice["level"] = _loudness(float(np.sqrt(np.mean(indata[:, 0] ** 2))))

    _stream = sd.InputStream(samplerate=16000, channels=1, blocksize=480, dtype="float32", callback=_on_audio)
    _stream.start()
    _voice["mic"] = True
except Exception as exc:  # без микрофона — синтетический голос
    print(f"[proto] микрофон недоступен ({exc}), голос синтетический")

# ---------- состояния ----------

_state = {"name": None, "since": time.monotonic(), "cycle": 0}


def show() -> None:
    frames("Reveal", [(0.0, 0.0)], 1)  # сброс на случай прерванного исчезновения
    spring("Reveal", 1.0, damping=0.62, period_ms=60)
    label.fade(1.0, 220)


def hide() -> None:
    frames("Reveal", [(1.0, 0.0)], 240, easing=_ease_in)
    label.fade(0.0, 160)
    spring("Swell", 0.0)
    drift(False)


def enter(name: str) -> None:
    previous = _state["name"]
    _state.update(name=name, since=time.monotonic())
    color = ACCENT.get(name, QColor("white"))
    texts = {
        "listening": ("Слушаю", "0:00", "dot"),
        "transcribing": ("Распознаю", "", "dot"),
        "polishing": ("Причёсываю", "", "dot"),
        "done": ("Готово", "Проверка связи: раз, два, три.", "check"),
        "error": ("Не распознал", "попробуйте сказать чётче", "cross"),
    }
    title, detail, icon = texts[name]
    label.title, label.detail, label.icon, label.color = title, detail, icon, color
    label.update()
    spring("W", label.width_for(title, detail), damping=0.66, period_ms=62)
    light_color(color)

    listening = name == "listening"
    busy = name in ("transcribing", "polishing")
    spring("Swell", 7.0 if listening else 0.0, damping=0.8)
    spring("GlowVoice", 0.62 if listening else 0.0, damping=0.9)
    if not listening:
        spring("Level", 0.0, damping=0.9)
    drift(busy)
    if busy:
        frames("Bob", [(0.0, 0.0), (0.5, 1.0), (1.0, 0.0)], 2800, forever=True, easing=_in_out)
        spring("Glow", 0.42, damping=0.9)
    else:
        p.stop_animation("Bob")
        spring("Bob", 0.0, damping=0.9)
    if listening:
        spring("Glow", 0.12, damping=0.9)
    elif name == "done":
        frames("Glow", [(0.0, 0.75), (1.0, 0.16)], 900)
    elif name == "error":
        frames("Glow", [(0.0, 0.7), (1.0, 0.2)], 900)
        frames("Shake", [(0.0, 0), (0.15, -7), (0.35, 6), (0.55, -4), (0.75, 2), (1.0, 0)], 420)
    if previous is None:
        show()


def tick_voice() -> None:
    if _state["name"] != "listening":
        return
    if _voice["mic"]:
        level = _voice["level"]
    else:
        t = time.monotonic()
        level = max(0.0, 0.55 + 0.35 * math.sin(t * 7.3) * math.sin(t * 1.7))
    spring("Level", level, damping=0.85, period_ms=42)
    seconds = int(time.monotonic() - _state["since"])
    text = f"{seconds // 60}:{seconds % 60:02d}"
    if label.detail != text:
        label.detail = text
        label.update()


SCRIPT = [("listening", 7000), ("transcribing", 1600), ("polishing", 1600), ("result", 2800), ("hidden", 1500)]


def run_script(index: int = 0) -> None:
    name, ms = SCRIPT[index % len(SCRIPT)]
    if name == "result":
        name = "done" if _state["cycle"] % 2 == 0 else "error"
        _state["cycle"] += 1
    if name == "hidden":
        hide()
        _state["name"] = None
    else:
        enter(name)
    QTimer.singleShot(ms, lambda: run_script(index + 1))


user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE: стекло ниже, текст поверх
label.show()

_voice_timer = QTimer()
_voice_timer.timeout.connect(tick_voice)
_voice_timer.start(33)

if args.hold:
    enter("listening")
else:
    QTimer.singleShot(400, run_script)
QTimer.singleShot(int(args.minutes * 60_000), app.quit)

print(f"[proto] плашка внизу по центру · микрофон: {'да' if _voice['mic'] else 'нет'} · "
      f"режим: {'держу «Слушаю»' if args.hold else 'состояния по кругу'} · сам закроюсь через {args.minutes:g} мин")
if sys.stdout:
    sys.stdout.flush()
app.exec()
