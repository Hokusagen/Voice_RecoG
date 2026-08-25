"""Экранный индикатор состояния.

Безрамочное окно поверх всех остальных, прозрачное для мыши и не забирающее
фокус — последнее критично: если бы HUD активировался, Ctrl+V уходил бы в него,
а не в окно, куда человек диктует.

Оформление: стекло с размытой подложкой и одно свечение, бегущее по кромке.
Цвет свечения — стадия, скорость и яркость — активность. Непрерывное движение
в кадре ровно одно; всё остальное либо стоит, либо проигрывается один раз при
смене состояния.
"""

from __future__ import annotations

import math
import sys
from collections import deque
from typing import Callable

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QApplication, QWidget

from config import UIConfig
from core.state import Stage, Status
from ui import glass, indicators, live, theme
from ui.liquid import MARGIN, Backdrop
from ui.shadow import pill_shadow, shadow_padding

#: Сколько последних значений громкости показывает осциллограмма. Новое
#: попадает в центр, старые расходятся к краям — волна расходится от середины.
_BARS = 7
_LEVEL_HISTORY = (_BARS + 1) // 2

#: Стадии, на которых идёт работа: точка дышит, свечение бежит.
_BUSY = frozenset({Stage.LOADING, Stage.TRANSCRIBING, Stage.POLISHING})

#: Стадии с одноразово прорисовываемым значком.
_RESULT = frozenset({Stage.DONE, Stage.WARNING, Stage.ERROR, Stage.CANCELLED, Stage.PAUSED})

#: Запас маски живого окна вокруг пилюли: свечение кромки рисуется пером в
#: шесть пикселей по её контуру и выступает наружу на половину толщины.
_MASK_PAD = 5


def _win32_click_through(widget: QWidget) -> None:
    """Дублирует флаги Qt расширенными стилями Win32.

    Qt.WindowTransparentForInput на Windows иногда теряется при пересоздании
    окна; WS_EX_NOACTIVATE вдобавок гарантирует, что окно не отберёт фокус
    у окна, в которое сейчас вставляется текст.
    """
    if sys.platform != "win32":
        return
    import ctypes

    gwl_exstyle = -20
    ws_ex_transparent = 0x00000020
    ws_ex_toolwindow = 0x00000080
    ws_ex_layered = 0x00080000
    ws_ex_noactivate = 0x08000000

    user32 = ctypes.windll.user32
    get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    get_long.restype = ctypes.c_ssize_t
    set_long.restype = ctypes.c_ssize_t
    get_long.argtypes = [ctypes.c_void_p, ctypes.c_int]
    set_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]

    handle = ctypes.c_void_p(int(widget.winId()))
    style = get_long(handle, gwl_exstyle)
    set_long(
        handle,
        gwl_exstyle,
        style | ws_ex_transparent | ws_ex_toolwindow | ws_ex_layered | ws_ex_noactivate,
    )


def _draw_pill_shadow(painter: QPainter, pill: QRectF) -> None:
    # Размер округляется до 8 пикселей: под размытием в 20 пикселей разница
    # не видна, зато кэш не пересчитывает тень на каждом кадре анимации.
    width = max(8, round(pill.width() / 8) * 8)
    height = max(8, round(pill.height() / 8) * 8)
    pixmap = pill_shadow(width, height, pill.height() / 2, theme.SHADOW_BLUR, theme.SHADOW)

    pad = shadow_padding(theme.SHADOW_BLUR)
    painter.drawPixmap(
        int(pill.center().x() - width / 2 - pad),
        int(pill.center().y() - height / 2 - pad + theme.SHADOW_OFFSET_Y),
        pixmap,
    )


class _ShadowWindow(QWidget):
    """Тень живого HUD — отдельное полупрозрачное окно под пилюлей.

    Живое окно непрозрачно и обрезано маской по контуру пилюли: всё, что оно
    рисует, лежит поверх копии рабочего стола, а копия при прокрутке отстаёт
    от настоящего стола на кадр-два. Тени нужна прозрачность на большой
    площади, поэтому она вынесена в собственное окно, которое DWM компонует
    поверх живого стола без задержки. В захват экрана оно попадает (Windows
    исключает только непрозрачные окна) — в записи будет видна одна тень.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._pill = QRectF()
        self._reveal = 0.0

    def sync(self, pill: QRectF, reveal: float) -> None:
        if pill == self._pill and abs(reveal - self._reveal) < 0.002:
            return
        self._pill = QRectF(pill)
        self._reveal = reveal
        self.update()

    def paintEvent(self, _event) -> None:
        if self._reveal <= 0.005 or self._pill.isEmpty():
            return
        painter = QPainter(self)
        painter.setOpacity(theme.clamp(self._reveal))
        _draw_pill_shadow(painter, self._pill)


class Hud(QWidget):
    def __init__(self, cfg: UIConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self._scale = max(0.75, min(1.6, cfg.hud_scale))

        self._status = Status(stage=Stage.IDLE)
        self._telemetry: Callable[[], tuple[float, float]] = lambda: (0.0, 0.0)

        self._reveal = 0.0
        self._pill_width = float(theme.PILL_MIN_WIDTH)
        self._result = 0.0

        self._clock = 0.0
        self._phase = 0.0
        self._levels: deque[float] = deque([0.0] * _LEVEL_HISTORY, maxlen=_LEVEL_HISTORY)
        self._bars = [0.0] * _BARS
        self._backdrop: Backdrop | None = None
        self._material = theme.DARK_MATERIAL
        # Живое стекло: фоновый поток пересобирает размытие из свежего снимка
        # экрана. None — прежний режим с одним снимком при появлении.
        self._live = live.LiveEngine() if cfg.liquid_live and live.available() else None
        self._shadow: _ShadowWindow | None = None
        if self._live is not None:
            self._shadow = _ShadowWindow()
            self.destroyed.connect(self._shadow.deleteLater)
        # Переход между тёмным и светлым стеклом вслед за живым фоном:
        # 0 — тёмное, 1 — светлое, дробное — кроссфейд.
        self._material_t = 0.0
        self._material_light = False
        self._lum_smooth: float | None = None
        self._mask_key: tuple | None = None

        self._title_font = theme.title_font()
        self._detail_font = theme.detail_font()
        self._timer_font = theme.timer_font()
        self._title_metrics = QFontMetrics(self._title_font)
        self._detail_metrics = QFontMetrics(self._detail_font)
        self._timer_metrics = QFontMetrics(self._timer_font)

        self._setup_window()
        self._setup_animations()

        self._frames = QTimer(self)
        self._frames.setInterval(theme.FRAME_MS)
        self._frames.timeout.connect(self._on_frame)

        self._auto_hide = QTimer(self)
        self._auto_hide.setSingleShot(True)
        self._auto_hide.timeout.connect(self.dismiss)

    # ---------- настройка окна ----------

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.WindowDoesNotAcceptFocus
        )
        if self._live is None:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        else:
            # Живой режим: Windows отказывается исключать из захвата окна с
            # попиксельной прозрачностью, поэтому окно непрозрачно, обрезано
            # маской по контуру пилюли, а под стекло подкладывается снимок
            # рабочего стола. Тень рисует отдельное окно (_ShadowWindow).
            self.setAttribute(Qt.WA_NoSystemBackground, True)
            self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        pad = shadow_padding(theme.SHADOW_BLUR)
        width = int(theme.PILL_MAX_WIDTH * self._scale) + pad * 2
        height = int(theme.PILL_HEIGHT * self._scale) + pad * 2 + theme.REVEAL_SLIDE
        self.resize(width, height)

    def _apply_click_through(self) -> None:
        _win32_click_through(self)
        if self._shadow is not None:
            _win32_click_through(self._shadow)

        if self._live is not None and not live.exclude_from_capture(int(self.winId())):
            # Без исключения из захвата живой цикл снимал бы сам себя.
            print("[live] окно не исключилось из захвата — живое стекло выключено")
            self._live.stop()
            self._live = None

    def _setup_animations(self) -> None:
        self._reveal_anim = self._make_anim(b"reveal", theme.REVEAL_MS, QEasingCurve.OutCubic)
        self._reveal_anim.finished.connect(self._on_reveal_finished)
        self._width_anim = self._make_anim(b"pillWidth", theme.WIDTH_MS, QEasingCurve.OutCubic)
        self._result_anim = self._make_anim(b"result", theme.RESULT_MS, QEasingCurve.OutCubic)

    def _make_anim(self, prop: bytes, duration: int, curve: QEasingCurve.Type) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(duration)
        animation.setEasingCurve(curve)
        return animation

    # ---------- анимируемые свойства ----------

    def _get_reveal(self) -> float:
        return self._reveal

    def _set_reveal(self, value: float) -> None:
        self._reveal = value
        self.update()

    def _get_pill_width(self) -> float:
        return self._pill_width

    def _set_pill_width(self, value: float) -> None:
        self._pill_width = value
        self.update()

    def _get_result(self) -> float:
        return self._result

    def _set_result(self, value: float) -> None:
        self._result = value
        self.update()

    reveal = Property(float, _get_reveal, _set_reveal)
    pillWidth = Property(float, _get_pill_width, _set_pill_width)
    result = Property(float, _get_result, _set_result)

    # ---------- внешнее управление ----------

    def set_telemetry(self, source: Callable[[], tuple[float, float]]) -> None:
        """Источник пары «громкость, секунды записи» для живой осциллограммы."""
        self._telemetry = source

    def show_status(self, status: Status) -> None:
        if not self.cfg.hud_enabled:
            return
        if status.stage is Stage.IDLE:
            self.dismiss()
            return

        self._status = status
        self._auto_hide.stop()

        if status.stage in _RESULT:
            self._restart(self._result_anim, 0.0, 1.0)
        else:
            self._result_anim.stop()
            self._result = 0.0

        target = float(self._target_width(status))
        if not self.isVisible():
            self._pill_width = target
            self._appear()
        else:
            self._restart(self._width_anim, self._pill_width, target)
            # Плашка могла уже уезжать после предыдущего результата — тогда
            # анимация исчезновения доиграла бы и спрятала свежий статус.
            if self._reveal < 0.999 or self._reveal_anim.state() == QPropertyAnimation.Running:
                self._reveal_anim.stop()
                self._reveal_anim.setEasingCurve(QEasingCurve.OutCubic)
                self._reveal_anim.setDuration(theme.REVEAL_MS)
                self._restart(self._reveal_anim, self._reveal, 1.0)
            if status.stage is Stage.LISTENING:
                # Новая диктовка могла начаться на другом мониторе.
                self._move_to_screen()

        if status.is_transient:
            self._auto_hide.start(self.hold_ms(status))
        self.update()

    def hold_ms(self, status: Status) -> int:
        """Сколько держать результат на экране.

        Фиксированного времени не хватает: короткое «Отменено» висит зря, а
        длинную распознанную фразу не успеваешь прочитать. Поэтому к базе
        добавляем время на чтение — примерно тридцать миллисекунд на знак,
        это спокойный темп чтения с экрана.
        """
        hold = self.cfg.success_hold_ms
        if status.stage is Stage.DONE and status.detail:
            hold += len(status.detail) * 30
        return min(hold, self.cfg.success_hold_max_ms)

    def dismiss(self) -> None:
        self._auto_hide.stop()
        if not self.isVisible():
            return
        self._reveal_anim.stop()
        self._reveal_anim.setEasingCurve(QEasingCurve.InCubic)
        self._reveal_anim.setDuration(theme.HIDE_MS)
        self._restart(self._reveal_anim, self._reveal, 0.0)

    # ---------- внутренние переходы ----------

    def _appear(self) -> None:
        self._move_to_screen()
        self._levels = deque([0.0] * _LEVEL_HISTORY, maxlen=_LEVEL_HISTORY)
        self._bars = [0.0] * _BARS
        # Подложку снимаем до show(): иначе в кадр попадёт сама плашка.
        self._grab_backdrop()

        if self._live is not None:
            self._update_mask(self._pill_rect())
        if self._shadow is not None:
            self._shadow.sync(self._pill_rect(), self._reveal)
            self._shadow.show()
        self.show()
        if self._shadow is not None:
            # Оба окна поверх всех; пилюля обязана быть выше собственной тени.
            self.raise_()
        self._apply_click_through()
        if self._live is not None:
            self._live.start()
        self._frames.start()
        self._reveal_anim.stop()
        self._reveal_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._reveal_anim.setDuration(theme.REVEAL_MS)
        self._restart(self._reveal_anim, self._reveal, 1.0)

    def _grab_backdrop(self) -> None:
        """Снимает фон под самой широкой плашкой — сузиться она сможет и потом."""
        pill = self._pill_rect(reveal=1.0, width=theme.PILL_MAX_WIDTH * self._scale)
        if self._live is not None:
            # Живой режим: первый кадр, пока окно скрыто. Дальше фон обновляет
            # фоновый поток, а этот Backdrop нужен для выбора материала и как
            # стекло на самые первые кадры появления.
            size = (int(pill.width()), int(pill.height()))
            self._backdrop = self._live.seed(self._capture_rect(pill, size), size)
        else:
            region = QRect(
                self.x() + int(pill.left()),
                self.y() + int(pill.top()),
                int(pill.width()),
                int(pill.height()),
            )
            self._backdrop = glass.capture(region)
        self._lum_smooth = self._backdrop.luminance if self._backdrop is not None else None
        self._material = theme.material(self._lum_smooth)
        self._material_light = self._material is theme.LIGHT_MATERIAL
        self._material_t = 1.0 if self._material_light else 0.0

    def _capture_rect(self, pill: QRectF, glass_size: tuple[int, int]) -> QRect:
        """Полоса захвата: пилюля с запасом на преломление, в экранных координатах."""
        width = glass_size[0] + 2 * MARGIN
        height = glass_size[1] + 2 * MARGIN
        center_x = self.x() + pill.center().x()
        center_y = self.y() + pill.center().y()
        return QRect(round(center_x - width / 2.0), round(center_y - height / 2.0), width, height)

    def _on_reveal_finished(self) -> None:
        if self._reveal <= 0.01:
            self._frames.stop()
            self.hide()

    def hideEvent(self, event) -> None:
        # Единственная точка останова живого цикла: сюда приводят и штатное
        # исчезновение, и прямой hide() снаружи (демо пересоздаёт плашку).
        if self._live is not None:
            self._live.stop()
        if self._shadow is not None:
            self._shadow.hide()
        super().hideEvent(event)

    @staticmethod
    def _restart(animation: QPropertyAnimation, start: float, end: float) -> None:
        animation.stop()
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def _move_to_screen(self) -> None:
        screen = None
        if self.cfg.hud_follow_cursor:
            screen = QApplication.screenAt(QCursor.pos())
        screen = screen or QApplication.primaryScreen()
        if screen is None:
            return

        area = screen.availableGeometry()
        margin = self.cfg.hud_margin
        position = self.cfg.hud_position
        pad = shadow_padding(theme.SHADOW_BLUR)

        if "top" in position:
            y = area.top() + margin - pad
        else:
            y = area.bottom() - margin - self.height() + pad

        if "left" in position:
            x = area.left() + margin
        elif "right" in position:
            x = area.right() - margin - self.width()
        else:
            x = area.center().x() - self.width() // 2

        self.move(int(x), int(y))
        if self._shadow is not None:
            self._shadow.setGeometry(self.geometry())

    # ---------- кадры ----------

    def _on_frame(self) -> None:
        self._clock += theme.FRAME_MS / 1000.0
        speed = theme.GLOW_SPEED.get(self._status.stage, 0.0)
        self._phase = (self._phase + speed * theme.FRAME_MS / 1000.0) % 1.0

        level, _elapsed = self._telemetry()
        self._levels.appendleft(_loudness(level) if self._status.stage is Stage.LISTENING else 0.0)
        self._settle_bars()

        if self._live is not None and self.isVisible():
            # Фоновому потоку — актуальная геометрия: ширина и центр пилюли
            # меняются анимациями каждый кадр.
            self._adapt_material()
            pill = self._pill_rect()
            size = (max(8, round(pill.width() / 8) * 8), max(8, round(pill.height())))
            self._live.set_inputs(self._capture_rect(pill, size), size, self._material)
            self._update_mask(pill)
            if self._shadow is not None:
                self._shadow.sync(pill, self._reveal)
        self.update()

    def _adapt_material(self) -> None:
        """Материал следует за живой светимостью фона.

        Без этого плашка, появившаяся над тёмным окном, после прокрутки к
        белой странице оставалась бы со светлым текстом на белом. Светимость
        сглаживается, порог берётся с гистерезисом, а переход — короткий
        кроссфейд: резкое переключение читалось бы как мигание.
        """
        luminance = self._live.luminance()
        if luminance is not None:
            self._lum_smooth = (
                luminance
                if self._lum_smooth is None
                else self._lum_smooth + (luminance - self._lum_smooth) * 0.25
            )
        if self._lum_smooth is None:
            return

        band = 0.05
        if self._material_light and self._lum_smooth < theme.MATERIAL_THRESHOLD - band:
            self._material_light = False
        elif not self._material_light and self._lum_smooth > theme.MATERIAL_THRESHOLD + band:
            self._material_light = True

        target = 1.0 if self._material_light else 0.0
        if self._material_t == target:
            return
        step = theme.FRAME_MS / 250.0
        if self._material_t < target:
            self._material_t = min(target, self._material_t + step)
        else:
            self._material_t = max(target, self._material_t - step)
        self._material = theme.material_blend(self._material_t)

    def _update_mask(self, pill: QRectF) -> None:
        """Обрезает живое окно по контуру пилюли, с запасом на свечение.

        Всё, что окно рисует, лежит поверх копии рабочего стола, а копия
        отстаёт от него на кадр-два; маска оставляет от копии только полосу
        под размытым стеклом, где отставание не разглядеть.
        """
        rect = pill.adjusted(-_MASK_PAD, -_MASK_PAD, _MASK_PAD, _MASK_PAD)
        key = (round(rect.x()), round(rect.y()), round(rect.width()), round(rect.height()))
        if key == self._mask_key:
            return
        self._mask_key = key
        path = QPainterPath()
        path.addRoundedRect(QRectF(*key), key[3] / 2.0, key[3] / 2.0)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _settle_bars(self) -> None:
        """Сглаживает полосы: вверх быстро, вниз плавно — как у аппаратных VU."""
        history = list(self._levels)
        center = _BARS // 2
        for index in range(_BARS):
            target = history[min(abs(index - center), len(history) - 1)]
            current = self._bars[index]
            self._bars[index] = current + (target - current) * (0.5 if target > current else 0.12)

    # ---------- отрисовка ----------

    def paintEvent(self, _event) -> None:
        if self._live is None and self._reveal <= 0.005:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        if self._live is not None:
            # Непрозрачное окно обязано закрасить всё внутри маски, причём
            # фон — в полную силу: прозрачность появления касается только
            # пилюли, иначе на время анимации темнел бы весь её прямоугольник.
            strip, strip_pos, _glass_image, _size = self._live.latest()
            painter.fillRect(self.rect(), Qt.black)
            if strip is not None and strip_pos is not None:
                painter.drawImage(strip_pos[0] - self.x(), strip_pos[1] - self.y(), strip)
            if self._reveal <= 0.005:
                return

        painter.setOpacity(theme.clamp(self._reveal))

        pill = self._pill_rect()
        radius = pill.height() / 2
        path = QPainterPath()
        path.addRoundedRect(pill, radius, radius)

        if self._live is None:
            # В живом режиме тень рисует собственное окно (_ShadowWindow).
            _draw_pill_shadow(painter, pill)
        self._paint_glass(painter, path, pill)
        self._paint_glow(painter, pill)
        self._paint_icon(painter, pill)
        self._paint_text(painter, pill)

    def _pill_rect(self, reveal: float | None = None, width: float | None = None) -> QRectF:
        reveal = theme.clamp(self._reveal if reveal is None else reveal)
        width = self._pill_width * self._scale if width is None else width
        height = theme.PILL_HEIGHT * self._scale

        # Появление: плашка всплывает снизу и слегка «набирает» масштаб.
        slide = (1.0 - reveal) * theme.REVEAL_SLIDE
        pop = theme.lerp(0.96, 1.0, theme.ease_out_back(reveal, overshoot=1.1))

        rect = QRectF(0, 0, width * pop, height * pop)
        rect.moveCenter(QPointF(self.width() / 2, self.height() / 2 + slide))
        return rect

    def _paint_glass(self, painter: QPainter, path: QPainterPath, pill: QRectF) -> None:
        if self._paint_liquid(painter, pill):
            return

        # Запасной вариант, если снять фон не удалось: обычная тонировка.
        painter.save()
        painter.setClipPath(path)
        scrim = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        scrim.setColorAt(0.0, self._material.scrim_top)
        scrim.setColorAt(1.0, self._material.scrim_bottom)
        painter.fillRect(pill, scrim)

        sheen = QLinearGradient(pill.topLeft(), QPointF(pill.left(), pill.center().y()))
        sheen.setColorAt(0.0, self._material.sheen)
        sheen.setColorAt(1.0, theme.with_alpha(self._material.sheen, 0.0))
        painter.fillRect(pill, sheen)
        painter.restore()

        edge = QLinearGradient(pill.topLeft(), pill.bottomLeft())
        edge.setColorAt(0.0, self._material.edge_top)
        edge.setColorAt(1.0, self._material.edge_bottom)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(edge, 1.0))
        painter.drawPath(path)

    def _paint_liquid(self, painter: QPainter, pill: QRectF) -> bool:
        """Выводит заранее собранное стекло. False — если его нет."""
        if self._live is not None:
            _strip, _pos, image, _size = self._live.latest()
            if image is not None:
                painter.drawImage(pill, image, QRectF(image.rect()))
                return True
            # Фоновый поток ещё не выдал первый кадр — на пару кадров
            # появления хватает статичного стекла из снимка-затравки.

        if self._backdrop is None:
            return False

        # Кэшируем с шагом в восемь пикселей и растягиваем до точной ширины:
        # преломлённая кромка при таком запасе тянется меньше чем на три
        # процента, а пересчётов во время анимации ширины — единицы.
        cached_w = max(8, round(pill.width() / 8) * 8)
        cached_h = max(8, round(pill.height()))
        pixmap = self._backdrop.render(cached_w, cached_h, self._material)
        if pixmap is None:
            return False

        painter.drawPixmap(pill, pixmap, QRectF(pixmap.rect()))
        return True

    def _paint_glow(self, painter: QPainter, pill: QRectF) -> None:
        stage = self._status.stage
        color = theme.accent(stage, self._material)
        speed = theme.GLOW_SPEED.get(stage, 0.0)

        if stage is Stage.LISTENING:
            # Громкость поднимает яркость всей кромки — информация без ещё
            # одного самостоятельного движения в кадре.
            level = max(self._bars) if self._bars else 0.0
            indicators.draw_perimeter_glow(
                painter, pill, color, self._phase, intensity=0.45 + 0.55 * level,
                base=0.10 + 0.22 * level, tail=4.0,
            )
        elif speed:
            indicators.draw_perimeter_glow(painter, pill, color, self._phase, intensity=0.85)
        elif stage in _RESULT:
            # Завершённые состояния: ободок ровно проявляется и гаснет вместе
            # с плашкой, ничего не бегает.
            indicators.draw_perimeter_glow(
                painter, pill, color, 0.0, comets=0, base=0.32 * theme.clamp(self._result)
            )

    def _paint_icon(self, painter: QPainter, pill: QRectF) -> None:
        size = theme.ICON_SIZE * self._scale
        box = QRectF(0, 0, size, size)
        box.moveCenter(
            QPointF(pill.left() + theme.PADDING_X * self._scale + size / 2, pill.center().y())
        )

        stage = self._status.stage
        color = theme.accent(stage, self._material)

        if stage is Stage.LISTENING:
            indicators.draw_waveform(painter, box, color, self._bars)
        elif stage in _BUSY:
            breath = 0.5 + 0.5 * math.sin(self._clock * 2.6)
            indicators.draw_dot(painter, box, color, breath)
        elif stage is Stage.DONE:
            indicators.draw_check(painter, box, color, self._result)
        elif stage is Stage.WARNING:
            indicators.draw_warning(painter, box, color, self._result)
        elif stage is Stage.ERROR:
            indicators.draw_cross(painter, box, color, self._result)
        elif stage is Stage.PAUSED:
            indicators.draw_pause(painter, box, color, self._result)
        elif stage is Stage.CANCELLED:
            indicators.draw_mic(painter, box, color, theme.clamp(self._result))

    def _paint_text(self, painter: QPainter, pill: QRectF) -> None:
        left = pill.left() + (theme.PADDING_X + theme.ICON_SIZE + theme.ICON_GAP) * self._scale
        right = pill.right() - theme.PADDING_X * self._scale

        timer_text = self._timer_text()
        if timer_text:
            width = self._timer_metrics.horizontalAdvance(timer_text)
            self._draw_text(
                painter,
                QRectF(right - width, pill.top(), width, pill.height()),
                timer_text,
                self._timer_font,
                self._material.detail,
                Qt.AlignRight,
            )
            right -= width + 16 * self._scale

        available = max(40.0, right - left)
        title = self._status.title
        detail = " ".join(self._status.detail.split())

        if title and detail:
            center = pill.center().y()
            title_box = QRectF(left, center - 18 * self._scale, available, 19 * self._scale)
            detail_box = QRectF(left, center - 1 * self._scale, available, 17 * self._scale)
        else:
            title_box = QRectF(left, pill.top(), available, pill.height())
            detail_box = title_box

        if title:
            self._draw_text(
                painter,
                title_box,
                self._title_metrics.elidedText(title, Qt.ElideRight, int(available)),
                self._title_font,
                self._material.title,
            )
        if detail and detail != title:
            self._draw_text(
                painter,
                detail_box,
                self._detail_metrics.elidedText(detail, Qt.ElideRight, int(available)),
                self._detail_font,
                self._material.detail,
            )

    def _draw_text(
        self,
        painter: QPainter,
        box: QRectF,
        text: str,
        font: QFont,
        color: QColor,
        align: Qt.AlignmentFlag = Qt.AlignLeft,
    ) -> None:
        """Рисует строку с мягкой подложкой под буквами.

        Подложка позволяет держать стекло сильно прозрачным: контраст добирается
        вокруг самих букв, а не затемнением всей плашки.
        """
        painter.setFont(font)
        flags = Qt.AlignVCenter | align

        painter.setPen(self._material.text_shadow)
        painter.drawText(box.translated(0.0, 1.0), flags, text)

        painter.setPen(color)
        painter.drawText(box, flags, text)

    # ---------- метрики текста ----------

    def _timer_text(self) -> str:
        if self._status.stage is not Stage.LISTENING:
            return ""
        _level, elapsed = self._telemetry()
        return f"{int(elapsed) // 60}:{int(elapsed) % 60:02d}"

    def _target_width(self, status: Status) -> int:
        if status.stage is Stage.LISTENING:
            # Фиксированная ширина: иначе плашка дёргалась бы каждую секунду
            # вместе с таймером.
            return 320
        detail = " ".join(status.detail.split())
        text = max(
            self._title_metrics.horizontalAdvance(status.title),
            self._detail_metrics.horizontalAdvance(detail),
        )
        total = text + theme.PADDING_X * 2 + theme.ICON_SIZE + theme.ICON_GAP + 12
        return int(min(theme.PILL_MAX_WIDTH, max(theme.PILL_MIN_WIDTH, total)))


def _loudness(rms: float) -> float:
    """Переводит RMS в 0..1 по логарифмической шкале.

    Речь занимает примерно от -48 до -12 дБFS; линейная шкала прижала бы всё
    к нулю, и полосы почти не шевелились бы.
    """
    if rms <= 1e-5:
        return 0.0
    return theme.clamp((20.0 * math.log10(rms) + 48.0) / 36.0)
