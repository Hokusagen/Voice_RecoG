"""Иконка в системном трее.

Кадры анимации отрисовываются один раз при первом показе состояния и дальше
только перелистываются: Shell_NotifyIcon дёргается шестнадцать раз в секунду,
а рисование не повторяется вовсе.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from core.state import Stage
from ui import theme

_SIZE = 64
_FRAMES = 20
_FRAME_MS = 80

#: Состояния с анимацией; остальные рисуются одним кадром. Движение здесь
#: только одно — медленное дыхание прозрачностью, в тон спокойной плашке.
_ANIMATED = frozenset({Stage.LOADING, Stage.LISTENING, Stage.TRANSCRIBING, Stage.POLISHING})


def _painter(pixmap: QPixmap) -> QPainter:
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    return painter


def _render(stage: Stage, phase: float) -> QIcon:
    """Кадр иконки. phase — положение в цикле анимации от 0 до 1.

    Форма почти не меняется: состояние показывает цвет, работу — медленное
    дыхание прозрачностью. Крутящихся дуг здесь нет намеренно — иконка не
    должна тянуть на себя взгляд, пока человек работает.
    """
    pixmap = QPixmap(_SIZE, _SIZE)
    pixmap.fill(Qt.transparent)
    painter = _painter(pixmap)
    color = theme.accent(stage)
    box = QRectF(10, 10, _SIZE - 20, _SIZE - 20)

    if stage is Stage.PAUSED:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(theme.with_alpha(color, 0.75)))
        for sign in (-1, 1):
            bar = QRectF(0, 0, 11, 34)
            bar.moveCenter(QPointF(box.center().x() + sign * 10, box.center().y()))
            painter.drawRoundedRect(bar, 5, 5)

    elif stage in (Stage.DONE, Stage.WARNING, Stage.ERROR):
        pen = QPen(color, 7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        if stage is Stage.DONE:
            painter.drawPolyline([QPointF(18, 33), QPointF(28, 43), QPointF(46, 21)])
        elif stage is Stage.ERROR:
            painter.drawLine(QPointF(21, 21), QPointF(43, 43))
            painter.drawLine(QPointF(43, 21), QPointF(21, 43))
        else:
            painter.drawLine(QPointF(32, 18), QPointF(32, 37))
            painter.drawLine(QPointF(32, 46), QPointF(32, 46))

    else:
        # Дыхание: полная непрозрачность в покое, мягкая пульсация в работе.
        breath = 1.0 if stage is Stage.IDLE else 0.55 + 0.45 * (
            0.5 + 0.5 * math.sin(phase * 2 * math.pi)
        )
        _draw_mic(painter, box, theme.with_alpha(color, breath))

    painter.end()
    return QIcon(pixmap)


def _draw_mic(painter: QPainter, box: QRectF, color: QColor) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(color))
    capsule = QRectF(0, 0, box.width() * 0.36, box.height() * 0.50)
    capsule.moveCenter(QPointF(box.center().x(), box.top() + box.height() * 0.33))
    painter.drawRoundedRect(capsule, capsule.width() / 2, capsule.width() / 2)

    pen = QPen(color, 5)
    pen.setCapStyle(Qt.RoundCap)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(pen)
    cradle = QRectF(0, 0, box.width() * 0.66, box.height() * 0.62)
    cradle.moveCenter(QPointF(box.center().x(), box.top() + box.height() * 0.40))
    painter.drawArc(cradle, int(200 * 16), int(140 * 16))
    painter.drawLine(
        QPointF(box.center().x(), box.top() + box.height() * 0.76),
        QPointF(box.center().x(), box.bottom()),
    )


def app_icon(size: int = 256) -> QIcon:
    """Иконка приложения для ярлыка Windows — тот же микрофон, что в трее.

    Рисунок задан числами под _SIZE, поэтому крупный вариант получается
    масштабированием, а не вторым набором координат: иначе ярлык и трей
    разъехались бы при первой же правке рисунка.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = _painter(pixmap)
    painter.scale(size / _SIZE, size / _SIZE)
    _draw_mic(painter, QRectF(10, 10, _SIZE - 20, _SIZE - 20), theme.accent(Stage.IDLE))
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    pause_toggled = Signal(bool)
    history_picked = Signal(str)
    settings_requested = Signal()
    restart_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._stage = Stage.IDLE
        self._frame = 0
        self._cache: dict[Stage, list[QIcon]] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_MS)
        self._timer.timeout.connect(self._advance)

        self._build_menu()
        self.set_stage(Stage.IDLE)
        self.activated.connect(self._on_activated)

    # ---------- меню ----------

    def _build_menu(self) -> None:
        # Переключатели живут в окне настроек: подменю трея в Windows
        # закрывается от любого промаха мимо, выбирать в нём неудобно. Здесь
        # только то, что нужно на ходу.
        menu = QMenu()

        self._status_action = QAction("Загружаю…", menu)
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)

        self._quota_action = QAction("", menu)
        self._quota_action.setEnabled(False)
        self._quota_action.setVisible(False)
        menu.addAction(self._quota_action)
        menu.addSeparator()

        self._pause_action = QAction("Пауза", menu, checkable=True)
        self._pause_action.toggled.connect(self.pause_toggled)
        menu.addAction(self._pause_action)

        self._history_menu = menu.addMenu("История")
        self._history_menu.setEnabled(False)

        settings = QAction("Настройки…", menu)
        settings.triggered.connect(self.settings_requested)
        menu.addAction(settings)

        menu.addSeparator()
        restart_action = QAction("Перезапустить", menu)
        restart_action.triggered.connect(self.restart_requested)
        menu.addAction(restart_action)

        quit_action = QAction("Выход", menu)
        quit_action.triggered.connect(self.quit_requested)
        menu.addAction(quit_action)

        self._menu = menu
        self.setContextMenu(menu)

    def set_history(self, entries) -> None:
        self._history_menu.clear()
        entries = list(entries)
        self._history_menu.setEnabled(bool(entries))
        for entry in entries:
            action = QAction(entry.label(), self._history_menu)
            action.setToolTip(entry.text)
            action.triggered.connect(lambda _checked, t=entry.text: self.history_picked.emit(t))
            self._history_menu.addAction(action)

    def set_summary(self, text: str) -> None:
        self._status_action.setText(text)

    def set_quota(self, text: str) -> None:
        """Остатки лимитов облака; пустая строка прячет пункт."""
        self._quota_action.setText(text)
        self._quota_action.setVisible(bool(text))

    # ---------- состояние иконки ----------

    def set_stage(self, stage: Stage) -> None:
        if stage is self._stage:
            return
        self._stage = stage
        self._frame = 0
        frames = self._frames_for(stage)
        self.setIcon(frames[0])
        if len(frames) > 1:
            self._timer.start()
        else:
            self._timer.stop()

    def _frames_for(self, stage: Stage) -> list[QIcon]:
        cached = self._cache.get(stage)
        if cached is None:
            count = _FRAMES if stage in _ANIMATED else 1
            cached = [_render(stage, index / count) for index in range(count)]
            self._cache[stage] = cached
        return cached

    def _advance(self) -> None:
        frames = self._frames_for(self._stage)
        self._frame = (self._frame + 1) % len(frames)
        self.setIcon(frames[self._frame])

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Одиночный клик по трею случается слишком легко, чтобы вешать на него
        # паузу: диктовка отключилась бы незаметно для пользователя. Поэтому
        # левый клик открывает то же меню, что и правый, — переключатели
        # режимов оказываются на один клик ближе.
        if reason == QSystemTrayIcon.DoubleClick:
            self._pause_action.toggle()
        elif reason == QSystemTrayIcon.Trigger:
            self._menu.popup(QCursor.pos())
