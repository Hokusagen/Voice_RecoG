"""Постоянная кнопка чата: один клик без раскрытия системного трея."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QPushButton

from config import UIConfig


class ChatButton(QPushButton):
    open_requested = Signal()

    def __init__(self, cfg: UIConfig) -> None:
        super().__init__("Чат с Дарви")
        self.cfg = cfg
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Открыть или продолжить разговор")
        self.setStyleSheet(
            "QPushButton { color: #edf2ff; background: #252c3e; border: 1px solid #596681;"
            " border-radius: 16px; padding: 9px 18px; font-size: 13px; }"
            "QPushButton:hover { background: #354360; }"
        )
        self.clicked.connect(self.open_requested)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        screen.availableGeometryChanged.connect(self.reposition)
        self.reposition()

    def reposition(self, *_args) -> None:
        area = QApplication.primaryScreen().availableGeometry()
        corner = self.cfg.card_corner or "bottom-right"
        x = area.left() + 20 if corner.endswith("left") else area.right() - self.width() - 20
        y = area.top() + 20 if corner.startswith("top") else area.bottom() - self.height() - 20
        self.move(x, y)
