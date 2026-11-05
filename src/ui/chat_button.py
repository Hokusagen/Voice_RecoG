"""Постоянная кнопка чата: один клик без раскрытия системного трея."""
import math

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QPushButton

from config import UIConfig


class ChatButton(QPushButton):
    open_requested = Signal()

    def __init__(self, cfg: UIConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Открыть или продолжить разговор")
        self.setAccessibleName("Чат с Дарви")
        self.setFixedSize(56, 42)
        self.clicked.connect(self.open_requested)
        screen = QApplication.primaryScreen()
        screen.availableGeometryChanged.connect(self.reposition)
        self.reposition()

    def paintEvent(self, _event) -> None:  # noqa: N802 — имя из Qt
        # Третий вариант прошлого сравнения, в его геометрии 48 px. Рисуем
        # векторно: нити остаются резкими при масштабировании Windows, а сборке
        # не нужен отдельный файл, который PyInstaller мог бы не включить.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(4, -3)
        r = QRectF(1, 9, 46, 30)
        shape = QPainterPath()
        shape.addRoundedRect(r, 15, 15)
        gradient = QLinearGradient(r.topLeft(), r.topRight())
        gradient.setColorAt(0, QColor("#0b8fd6"))
        gradient.setColorAt(1, QColor("#6b3fe0"))
        p.fillPath(shape, gradient)
        p.save()
        p.setClipPath(shape)
        inner = r.adjusted(-r.width() * 0.12, 3.6, r.width() * 0.12, -3.6)
        for i in (0, 4, 1, 3, 2):
            spread = (i / 4 - 0.5) * 2
            amplitude = 0.36 * (1 - 0.2 * abs(spread))
            phase = 0.25 + spread * 1.7 / 2
            path = QPainterPath()
            for j in range(121):
                u = j / 120
                envelope = math.sin(math.pi * u) ** 0.8
                x = inner.left() + inner.width() * u
                y = inner.center().y() - inner.height() * envelope * amplitude * math.sin(2 * math.pi * u + phase)
                if j == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            p.setPen(QPen(QColor(255, 255, 255, 255 if i == 2 else 110), 3.2 if i == 2 else 1.3))
            p.drawPath(path)
        p.restore()

        # Отклик только на действие: в покое кнопка не двигается и не требует
        # таймера. Подложка остаётся частью иконки, без второй рамки вокруг неё.
        if self.isDown():
            p.fillPath(shape, QColor(0, 0, 0, 35))
        elif self.underMouse() or self.hasFocus():
            p.fillPath(shape, QColor(255, 255, 255, 22))
        rim = QLinearGradient(r.topLeft(), r.bottomLeft())
        for position, opacity in ((0, 150), (0.5, 25), (1, 60)):
            rim.setColorAt(position, QColor(255, 255, 255, opacity))
        p.setPen(QPen(rim, 1.25))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.625, 0.625, -0.625, -0.625), 14.375, 14.375)
        p.end()

    def enterEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        super().leaveEvent(event)
        self.update()

    def reposition(self, *_args) -> None:
        area = QApplication.primaryScreen().availableGeometry()
        corner = self.cfg.card_corner or "bottom-right"
        x = area.left() + 20 if corner.endswith("left") else area.right() - self.width() - 20
        y = area.top() + 20 if corner.startswith("top") else area.bottom() - self.height() - 20
        self.move(x, y)
