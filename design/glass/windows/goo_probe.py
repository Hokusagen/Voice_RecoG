"""Жидкий силуэт целиком в DWM: пилюля + капля -> VisualSurface -> размытие -> порог по альфе
(GammaTransfer 18a-7) -> маска для размытого живого фона. Проверяем по GDI-снимку:
сглаженная ли кромка, есть ли перемычка между близкими формами, видна ли капля за контуром пилюли.

    python goo_probe.py           — измерение и выход
    python goo_probe.py --show    — капля отрывается и возвращается 20 с (смотреть глазами)
"""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

import numpy as np
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"D:\Anton\Job\Pet_projects\VoiceRecognize\src")
SHOW = "--show" in sys.argv
app = QApplication([])

from winrt.windows.foundation.numerics import Vector2, Vector3  # noqa: E402
from winrt.windows.ui import Color  # noqa: E402
from winrt.windows.ui.composition import AnimationIterationBehavior, Compositor  # noqa: E402
from winrt.windows.ui.composition.interop import create_desktop_window_target  # noqa: E402
from datetime import timedelta  # noqa: E402

import comp_blur as cb  # noqa: E402
from fx_accept2 import Fx  # noqa: E402  (заодно поднимает очередь диспетчера)
from ui.live import _GdiGrabber  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)
BX, BY, BW, BH = 200, 200, 760, 300


class Back(QWidget):
    """Белый фон с красными полосами слева (там видно размытие); зоны замеров белые."""

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        for x in range(20, 150, 24):
            p.fillRect(x, 0, 8, self.height(), QColor("#e53935"))
        p.setPen(QColor("#111111"))
        p.setFont(QFont("Segoe UI", 12))
        p.drawText(20, 40, "живой фон под стеклом")


back = Back()
back.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
back.setGeometry(BX, BY, BW, BH)
back.show()

# ---------- окно композиции ----------
import wda_matrix as wm  # noqa: E402  (класс окна WdaMatrix)

W, H = 760, 170
WX, WY = BX, BY + 65
hwnd = wm.user32.CreateWindowExW(wm.WS_EX_NOREDIRECTIONBITMAP | wm.WS_EX_TOPMOST | wm.WS_EX_TOOLWINDOW | wm.WS_EX_NOACTIVATE
                              | wm.WS_EX_LAYERED | wm.WS_EX_TRANSPARENT, "WdaMatrix", "goo", wm.WS_POPUP,
                              WX, WY, W, H, None, None, wm.HINST, None)
wm.user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)

from fx_accept2 import compositor  # noqa: E402
target = create_desktop_window_target(compositor, hwnd, is_topmost=True)
root = compositor.create_container_visual()
root.size = Vector2(W, H)
target.root = root

# Формы: белые, на прозрачном; дерево не подключено к окну — только источник поверхности.
PILL_W, PILL_H = 400.0, 56.0
PX, PY = 150.0, (H - PILL_H) / 2  # левый верх пилюли: x 150..550, y 57..113
shapes = compositor.create_shape_visual()
shapes.size = Vector2(W, H)
white = compositor.create_color_brush_with_color(Color(a=255, r=255, g=255, b=255))
pill_geo = compositor.create_rounded_rectangle_geometry()
pill_geo.size = Vector2(PILL_W, PILL_H)
pill_geo.corner_radius = Vector2(PILL_H / 2, PILL_H / 2)
pill_geo.offset = Vector2(PX, PY)
pill_shape = compositor.create_sprite_shape_with_geometry(pill_geo)
pill_shape.fill_brush = white
drop_geo = compositor.create_ellipse_geometry()
R = 16.0
drop_geo.radius = Vector2(R, R)
drop_geo.center = Vector2(PX + PILL_W + 6 + R, H / 2)  # зазор 6 px
drop_shape = compositor.create_sprite_shape_with_geometry(drop_geo)
drop_shape.fill_brush = white
shapes.shapes.append(pill_shape)
shapes.shapes.append(drop_shape)

surface = compositor.create_visual_surface()
surface.source_visual = shapes
surface.source_size = Vector2(W, H)
blobs_brush = compositor.create_surface_brush_with_surface(surface)

GAIN, BIAS = 18.0, -7.0
blur_back = Fx("1FEB6D69-2FE6-4AC9-8C58-1D7F93E7A6A5", [("f", 18.0), ("u", 1), ("u", 1)], 0, {}, "BlurBack")
blur_back.sources = [cb.source_parameter("backdrop")]
dark = Fx("B56C8CFA-F634-41EE-BEE0-FFA617106004", [("f", -0.5)], 0, {}, "Dark")
dark.sources = [blur_back.as_source]
blur_blobs = Fx("1FEB6D69-2FE6-4AC9-8C58-1D7F93E7A6A5", [("f", 8.0), ("u", 1), ("u", 0)], 0, {}, "BlurBlobs")
blur_blobs.sources = [cb.source_parameter("blobs")]
thresh = Fx("409444C4-C419-41A0-B0C1-8CD0C0A18E42",
            [("f", 1), ("f", 1), ("f", 0), ("b", True), ("f", 1), ("f", 1), ("f", 0), ("b", True),
             ("f", 1), ("f", 1), ("f", 0), ("b", True), ("f", GAIN), ("f", 1), ("f", BIAS), ("b", False), ("b", True)],
            0, {}, "Goo")
thresh.sources = [blur_blobs.as_source]
out = Fx("C80ECFF0-3FD5-4F05-8328-C5D1724B4F0A", [], 0, {}, "Mask")
out.sources = [dark.as_source, thresh.as_source]
brush, status, keep = cb.effect_brush(compositor, out, {"backdrop": compositor.create_backdrop_brush(),
                                                        "blobs": blobs_brush})
KEEP = [blur_back, dark, blur_blobs, thresh, out, keep, surface, shapes]
sprite = compositor.create_sprite_visual()
sprite.size = Vector2(W, H)
cb.set_sprite_brush(sprite, brush)
root.children.insert_at_top(sprite)
print(f"кисть собрана, LoadStatus={status}")

grab = _GdiGrabber()
state = {}


def shot():
    raw = grab.grab(WX, WY, W, H)
    return raw[..., :3].astype(np.float32).mean(axis=2)


def measure(tag):
    g = shot()
    cy = int(H / 2)
    row = g[cy]
    # Левая кромка пилюли по центральной строке: x ~ 150.
    edge = row[140:162]
    mid = ((edge > 190) & (edge < 245)).sum()
    gap_x = int(PX + PILL_W + 3)  # середина зазора 6 px
    drop_c = row[int(PX + PILL_W + 6 + R)]
    inside = row[350]
    print(f"[{tag}] внутри пилюли {inside:.0f} | пиксели полутона на левой кромке: {mid} "
          f"(профиль {np.round(edge[4:16]).astype(int).tolist()}) | зазор {row[gap_x]:.0f} | центр капли {drop_c:.0f}")
    return g


def step1():
    state["near"] = measure("капля в 6 px")
    # Отводим каплю на 70 px — перемычка должна порваться.
    drop_geo.center = Vector2(PX + PILL_W + 70 + R, H / 2)
    QTimer.singleShot(500, step2)


def step2():
    g = shot()
    row = g[int(H / 2)]
    gap_x = int(PX + PILL_W + 35)
    print(f"[капля в 70 px] середина зазора {row[gap_x]:.0f} | центр капли {row[int(PX + PILL_W + 70 + R)]:.0f}")
    img = np.ascontiguousarray(grab.grab(WX, WY, W, H))
    QImage(img.data, W, H, W * 4, QImage.Format_RGB32).copy().save(str(HERE / "goo_probe.png"))
    if SHOW:
        animate()
        QTimer.singleShot(20000, app.quit)
    else:
        app.quit()


def animate():
    """Капля отрывается и возвращается — считает композитор, Python спит."""
    anim = compositor.create_vector2_key_frame_animation()
    anim.insert_key_frame(0.0, Vector2(PX + PILL_W - R, H / 2))
    anim.insert_key_frame(0.5, Vector2(PX + PILL_W + 90 + R, H / 2))
    anim.insert_key_frame(1.0, Vector2(PX + PILL_W - R, H / 2))
    anim.duration = timedelta(milliseconds=2400)
    anim.iteration_behavior = AnimationIterationBehavior.FOREVER
    drop_geo.start_animation("Center", anim)


wm.user32.ShowWindow(hwnd, 4)
QTimer.singleShot(900, step1)
app.exec()
