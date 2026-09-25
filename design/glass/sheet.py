from pathlib import Path
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtCore import Qt
import sys
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
names = sys.argv[1].split(",")
specs = sys.argv[2].split(",")
W, H = 1040 // 2, 420 // 2
sheet = QImage(W * len(specs), H * len(names), QImage.Format_RGB32)
sheet.fill(QColor("#000"))
p = QPainter(sheet)
p.setRenderHint(QPainter.SmoothPixmapTransform)
for r, name in enumerate(names):
    for c, spec in enumerate(specs):
        img = QImage(str(Path("shots") / name / f"{spec}.png"))
        if not img.isNull():
            p.drawImage(c * W, r * H, img.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
    p.setPen(QColor("#ff0"))
    p.setFont(QFont("Segoe UI", 14, QFont.Bold))
    p.drawText(8, r * H + 22, name)
p.end()
sheet.save(sys.argv[3])
print("ok", sys.argv[3])
