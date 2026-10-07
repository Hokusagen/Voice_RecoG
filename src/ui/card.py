"""Карточка ответа Дарви: вопрос голосом — ответ в углу экрана, поверх работы.

Решения — design/DARVI-SKILLS.md, «Где живёт Дарви на экране» (6.10.2026):
Дарви живёт в углу, и карточка раскрывается от него; фокус она не забирает —
в своём окне работаешь дальше, а кнопки нажимаются мышью; стекло плотнее, чем у
пилюли, потому что на нём читают абзацы, а не одну строку. Движение одно:
высота растёт пружиной вслед за текстом, который приходит потоком.

Окно сразу размером с самую большую карточку, а видимая карточка растёт внутри
него. Менять размер окна каждый кадр — заметно дёргается; а прозрачные пиксели
многослойного окна Windows пропускает к окнам под ним, так что пустая часть
окна мыши не мешает.

Стекло — снимок фона, размытый уменьшением, под плотной вуалью. Снимок делается
до показа, пока окна нет на экране, и дальше не обновляется: под вуалью такой
плотности отставание от прокрутки почти не видно. Живое стекло композитора —
у плашки (ui/lens_hud.py); переносить на него карточку — когда её вид устоится.
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

import numpy as np
from PySide6.QtCore import QRect, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCursor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextFrameFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from config import UIConfig
from core.ask import clean_answer
from ui import theme
from ui.motion import Spring

RADIUS = 18
PAD = 16
GAP = 10

#: Отступ от края рабочей области: столько же, сколько у окон с тенью.
MARGIN = 20

#: Самая высокая карточка — доля рабочей высоты экрана. Длиннее — прокрутка:
#: карточка подсказывает поверх работы, а не закрывает её целиком.
MAX_SHARE = 0.6

#: Как часто перерисовывать текст, пока он приходит: по токену — рябь, а раз в
#: 70 мс текст ложится строками и высота растёт ровно.
RENDER_MS = 70

#: Размытие снимка — уменьшением в столько раз и обратным растяжением.
BLUR_DIV = 14

#: Плотная вуаль поверх размытого фона: светлая над светлым, тёмная над тёмным.
VEIL_LIGHT = QColor(250, 250, 252, 214)
VEIL_DARK = QColor(22, 25, 33, 206)

#: Шрифт кода по порядку: что найдётся первым. Сам импортёр Markdown берёт
#: Courier New, а таблицу стилей документа, где стоял Consolas, не читает.
CODE_FAMILIES = ["Consolas", "Menlo", "Courier New"]


class AnswerCard(QWidget):
    insert_requested = Signal(str)
    """«Вставить»: текст ответа без разметки — в окно, где курсор."""

    recheck_requested = Signal()
    """«Проверить в интернете»: тот же вопрос заново с поиском."""

    closed = Signal()
    """Человек закрыл карточку крестиком — разговор окончен."""

    def __init__(self, cfg: UIConfig) -> None:
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.cfg = cfg
        self._scale = max(0.75, float(cfg.hud_scale or 1.0))

        self._question = ""
        self._raw = ""
        self._fresh = True
        """Следующий кусок потока начинает новый ответ — прежний стираем не
        раньше, чем придёт первое слово нового: пустая карточка хуже старой."""

        self._done = False
        self._sources: list[str] = []
        self._code_bg = QColor(0, 0, 0, 13)
        self._backdrop: QImage | None = None
        self._light = False
        self._top = False
        self._max_h = 0

        self._height = Spring(0.0, response=0.42, damping=0.86)
        self._tick = QTimer(self)
        self._tick.setInterval(16)
        self._tick.timeout.connect(self._on_tick)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(RENDER_MS)
        self._render_timer.timeout.connect(self._render)
        self._hiding = False

        self._build()

    # ---------- сборка ----------

    def _build(self) -> None:
        # Содержимое стоит по полной высоте ответа, а показывается через окошко
        # размером с карточку: дочерние виджеты обрезает только родитель, и без
        # него текст растущей карточки висел бы над ней в пустоте.
        self._clip = QWidget(self)
        self._body = QWidget(self._clip)
        layout = QVBoxLayout(self._body)
        layout.setContentsMargins(PAD, PAD - 4, PAD - 6, PAD)
        layout.setSpacing(GAP)

        head = QHBoxLayout()
        head.setSpacing(6)
        self._question_label = QLabel()
        self._question_label.setWordWrap(True)
        self._question_label.setFont(_sized(theme.detail_font(), 12, self._scale))
        self._question_label.setTextInteractionFlags(Qt.NoTextInteraction)
        head.addWidget(self._question_label, 1)
        self._close = QPushButton("✕")
        self._close.setCursor(Qt.PointingHandCursor)
        self._close.setFixedSize(int(24 * self._scale), int(24 * self._scale))
        self._close.clicked.connect(self._on_close)
        head.addWidget(self._close, 0, Qt.AlignTop)
        layout.addLayout(head)

        self._text = QTextBrowser()
        self._text.setFrameShape(QTextBrowser.NoFrame)
        self._text.setOpenExternalLinks(True)
        self._text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._text.setFont(_sized(theme.detail_font(), 14, self._scale))
        self._text.document().setDocumentMargin(0)
        self._text.viewport().setAutoFillBackground(False)
        layout.addWidget(self._text, 1)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setFont(_sized(theme.detail_font(), 12, self._scale))
        self._status.setOpenExternalLinks(True)
        self._status.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self._status.hide()
        layout.addWidget(self._status)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self._insert = self._action("Вставить", self._on_insert)
        self._copy = self._action("Копировать", self._on_copy)
        self._recheck = self._action("Проверить в интернете", self._on_recheck)
        for button in (self._insert, self._copy, self._recheck):
            actions.addWidget(button)
        actions.addStretch(1)
        self._actions = QWidget()
        self._actions.setLayout(actions)
        actions.setContentsMargins(0, 0, 0, 0)
        self._actions.hide()
        layout.addWidget(self._actions)

    def _action(self, label: str, slot) -> QPushButton:
        button = QPushButton(label)
        button.setCursor(Qt.PointingHandCursor)
        button.setFont(_sized(theme.detail_font(), 12, self._scale))
        button.clicked.connect(slot)
        button.setProperty("label", label)
        return button

    def _apply_material(self) -> None:
        """Цвета текста и кнопок под вуаль: над светлым — тёмные, над тёмным — светлые."""
        glass = theme.LIGHT_MATERIAL if self._light else theme.DARK_MATERIAL
        text, muted = _css(glass.title), _css(glass.detail)
        line = "rgba(0,0,0,0.12)" if self._light else "rgba(255,255,255,0.16)"
        hover = "rgba(0,0,0,0.06)" if self._light else "rgba(255,255,255,0.08)"
        link = "#1d5fd6" if self._light else "#8ab4ff"
        self._question_label.setStyleSheet(f"color: {muted}; background: transparent;")
        self._status.setStyleSheet(f"color: {muted}; background: transparent;")
        self._text.setStyleSheet(
            f"QTextBrowser {{ color: {text}; background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ width: 6px; background: transparent; }}"
            f"QScrollBar::handle:vertical {{ background: {line}; border-radius: 3px; min-height: 24px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        button = (
            f"QPushButton {{ color: {text}; background: transparent; border: 1px solid {line};"
            f" border-radius: 8px; padding: 3px 10px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
            f"QPushButton:disabled {{ color: {muted}; }}"
        )
        for widget in (self._insert, self._copy, self._recheck):
            widget.setStyleSheet(button)
        self._close.setStyleSheet(
            f"QPushButton {{ color: {muted}; background: transparent; border: none; border-radius: 12px; }}"
            f"QPushButton:hover {{ background: {hover}; color: {text}; }}"
        )
        self._status_link = link
        self._link = QColor(link)
        self._code_bg = QColor(0, 0, 0, 13) if self._light else QColor(255, 255, 255, 18)

    # ---------- что показывать ----------

    @Slot(str, bool)
    def start(self, question: str, searching: bool) -> None:
        """Вопрос ушёл модели. Карточка ещё не появляется: пустой она не нужна.

        Видимая карточка до первого слова держит прежний ответ вместе с его
        вопросом: подписать старый ответ новым вопросом — хуже, чем подождать.
        Меняется только строка состояния, если модель пошла искать.
        """
        self._question = question
        self._fresh = True
        self._recheck.setEnabled(False)
        if searching and self.isVisible() and not self._hiding:
            self._set_status("ищу в интернете…")

    @Slot(str)
    def feed(self, piece: str) -> None:
        """Очередной кусок ответа из потока."""
        if self._fresh:
            self._fresh = False
            self._raw = ""
            self._done = False
            self._sources = []
            self._question_label.setText(self._question)
            # Кнопки недописанному ответу не нужны: «Вставить» вставил бы обрывок.
            self._actions.hide()
            self._set_status("")
            self._text.verticalScrollBar().setValue(0)
        self._raw += piece
        if not self.isVisible() or self._hiding:
            self._appear()
        if not self._render_timer.isActive():
            self._render_timer.start()

    @Slot(list)
    def finish(self, sources: list[str]) -> None:
        """Ответ дописан: показываем источники и кнопки."""
        self._done = True
        self._sources = list(sources)
        self._recheck.setEnabled(True)
        self._recheck.setVisible(not self._sources)
        if self._sources:
            shown = self._sources[:4]
            hosts = [_domain(url) for url in shown]
            links = " · ".join(
                f'<a href="{url}" style="color: {self._status_link}; text-decoration: none;">'
                f"{_source_label(url, hosts.count(host) > 1)}</a>"
                for url, host in zip(shown, hosts)
            )
            self._set_status("Источники: " + links)
        else:
            self._set_status("")
        self._actions.show()
        self._render()

    @Slot(str)
    def fail(self, reason: str) -> None:
        """Ответа не будет. Видимая карточка сохраняет прежний ответ."""
        self._fresh = False
        self._recheck.setEnabled(True)
        if self.isVisible():
            self._set_status(f"не вышло: {reason}")

    def dismiss(self) -> None:
        """Убрать карточку, не заканчивая разговор: человек вернулся к работе."""
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        self._height.set(0.0)
        self._tick.start()

    # ---------- кнопки ----------

    def _plain(self) -> str:
        return self._text.document().toPlainText().strip()

    def _on_insert(self) -> None:
        self.insert_requested.emit(self._plain())
        self._flash(self._insert, "Вставлено")

    def _on_copy(self) -> None:
        from core.paster import write_text

        try:
            write_text(self._plain())
        except Exception as exc:  # noqa: BLE001 — буфер бывает занят другим окном
            print(f"[card] не скопировалось: {exc}")
            return
        self._flash(self._copy, "Скопировано")

    def _on_recheck(self) -> None:
        self._recheck.setEnabled(False)
        self._set_status("ищу в интернете…")
        self.recheck_requested.emit()

    def _on_close(self) -> None:
        self.dismiss()
        self.closed.emit()

    def _flash(self, button: QPushButton, text: str) -> None:
        button.setText(text)
        QTimer.singleShot(1400, lambda: button.setText(button.property("label")))

    def _set_status(self, html: str) -> None:
        self._status.setText(html)
        self._status.setVisible(bool(html))
        self._retarget()

    # ---------- геометрия и движение ----------

    def _appear(self) -> None:
        self._hiding = False
        screen = QApplication.screenAt(QCursor.pos()) if self.cfg.hud_follow_cursor else None
        screen = screen or QApplication.primaryScreen()
        area = screen.availableGeometry()
        width = int(self.cfg.card_width * self._scale)
        self._max_h = int(area.height() * MAX_SHARE)
        corner = (self.cfg.card_corner or "bottom-right").lower()
        self._top = corner.startswith("top")
        x = area.left() + MARGIN if corner.endswith("left") else area.right() - MARGIN - width
        y = area.top() + MARGIN if self._top else area.bottom() - MARGIN - self._max_h
        self.setGeometry(x, y, width, self._max_h)

        # Снимок — пока окна нет на экране, иначе в стекло попадёт оно само.
        self._backdrop, self._light = _blurred(screen, QRect(x, y, width, self._max_h))
        self._apply_material()
        self._question_label.setText(self._question)
        self._height.snap(0.0)
        self._place()
        self.show()
        _no_activate(self)
        self._retarget()
        self._tick.start()

    def _render(self) -> None:
        bar = self._text.verticalScrollBar()
        keep = bar.value()
        self._text.setMarkdown(clean_answer(self._raw))
        _shape(self._text.document(), self._code_bg, self._link, int(round(8 * self._scale)))
        bar.setValue(keep)
        self._retarget()

    def _retarget(self) -> None:
        if not self.isVisible() or self._hiding:
            return
        wanted = self._wanted_height()
        # Полоса прокрутки — только у карточки, упёршейся в потолок. Иначе
        # мелькнувшая на полкадра полоса сужает текст, он становится на строку
        # выше расчёта — и полоса остаётся навсегда.
        capped = wanted > self._max_h
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if capped else Qt.ScrollBarAlwaysOff)
        self._height.set(float(min(wanted, self._max_h)))
        if not self._tick.isActive():
            self._tick.start()

    def _wanted_height(self) -> int:
        """Высота, при которой виден весь ответ; потолок — забота вызывающего."""
        inner = self.width() - 2 * PAD
        # Мерить копию: ширину своего документа QTextBrowser выставляет сам по
        # окну просмотра, а оно до первой раскладки ещё не знает своего размера.
        doc = self._text.document().clone(self)
        doc.setTextWidth(self.width() - PAD - (PAD - 6))
        text_h = int(doc.size().height())
        doc.deleteLater()
        total = PAD - 4 + max(self._question_label.heightForWidth(inner - 30), self._close.height())
        total += GAP + text_h + 4
        if self._status.isVisible():
            total += GAP + self._status.heightForWidth(inner)
        if self._actions.isVisible():
            total += GAP + self._actions.sizeHint().height()
        total += PAD
        return total

    def _card_rect(self) -> QRect:
        height = max(0, min(self._max_h, int(round(self._height.value))))
        if self._top:
            return QRect(0, 0, self.width(), height)
        return QRect(0, self._max_h - height, self.width(), height)

    def _place(self) -> None:
        rect = self._card_rect()
        # Растёт карточка, а не сжимается текст внутри неё: содержимое — по
        # высоте цели пружины, прижато к верху, лишнее срезает окошко.
        self._clip.setGeometry(rect)
        self._body.setGeometry(0, 0, self.width(), max(rect.height(), int(self._height.target)))
        self._clip.setVisible(rect.height() > 2 * PAD)

    def _on_tick(self) -> None:
        self._height.step(0.016)
        settled = abs(self._height.value - self._height.target) < 0.5 and abs(self._height.velocity) < 0.5
        if settled:
            self._height.snap(self._height.target)
        self._place()
        self.update()
        if settled:
            self._tick.stop()
            if self._hiding:
                self._hiding = False
                self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802 — имя из Qt
        rect = self._card_rect()
        if rect.height() < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.setClipPath(path)
        if self._backdrop is not None:
            painter.drawImage(rect, self._backdrop, rect)
        painter.fillRect(rect, VEIL_LIGHT if self._light else VEIL_DARK)
        painter.setClipping(False)
        glass = theme.LIGHT_MATERIAL if self._light else theme.DARK_MATERIAL
        painter.setPen(QPen(glass.edge_bottom if self._light else glass.edge_top.darker(160), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)


# ---------- помощники ----------


def _sized(font, pixels: int, scale: float):
    font.setPixelSize(max(9, int(round(pixels * scale))))
    return font


def _css(color: QColor) -> str:
    return f"rgba({color.red()},{color.green()},{color.blue()},{color.alphaF():.2f})"


def _domain(url: str) -> str:
    host = urlparse(url).netloc
    return host[4:] if host.startswith("www.") else host or url


def _shape(doc: QTextDocument, code_bg: QColor, link: QColor, gap: int) -> None:
    """Отступы абзацев, вид кода и цвет ссылок после setMarkdown.

    Импортёр Markdown в Qt берёт отступ абзаца из размера шрифта в пунктах, а
    у шрифта карточки размер задан в пикселях: пунктов нет — и абзацы
    слипаются. Код он не переносит по словам, и в узкой карточке строки уходят
    за край; к тому же без подложки код не отличить от текста. Ссылки он красит
    тёмно-синим #003173 мимо таблицы стилей — на тёмной вуали их не видно.
    """
    runs: list[tuple[int, int]] = []
    spans: list[tuple[int, int, bool]] = []
    block = doc.begin()
    while block.isValid():
        fmt = block.blockFormat()
        code = fmt.hasProperty(QTextFormat.BlockCodeFence) or fmt.nonBreakableLines()
        if code:
            fmt.setNonBreakableLines(False)
            fmt.setTopMargin(0)
            fmt.setBottomMargin(0)
            start, end = block.position(), block.position() + block.length() - 1
            # У блока кода признак моноширинного шрифта импортёр ставит в
            # False, хотя шрифт Courier New, — код узнаём по самому блоку.
            spans.append((start, end, False))
            if runs and runs[-1][1] + 1 == start:
                runs[-1] = (runs[-1][0], end)
            else:
                runs.append((start, end))
        else:
            piece = block.begin()
            while not piece.atEnd():
                fragment = piece.fragment()
                char = fragment.charFormat()
                if char.isAnchor() or char.fontFixedPitch():
                    spans.append((fragment.position(), fragment.position() + fragment.length(), char.isAnchor()))
                piece += 1
            # Пункты одного списка — плотнее, абзацы — с воздухом.
            following = block.next()
            same_list = block.textList() is not None and following.isValid() and following.textList() is block.textList()
            fmt.setTopMargin(0)
            fmt.setBottomMargin(gap // 3 if same_list else gap)
        QTextCursor(block).setBlockFormat(fmt)
        block = block.next()

    # Цвет и шрифт — до рамок: рамка вставляет свои абзацы и сдвигает позиции.
    linked, coded = QTextCharFormat(), QTextCharFormat()
    linked.setForeground(link)
    coded.setFontFamilies(CODE_FAMILIES)
    for start, end, is_link in spans:
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        cursor.mergeCharFormat(linked if is_link else coded)

    # Код — в рамку с подложкой и полями: у блока своих полей нет, а у рамки есть.
    frame = QTextFrameFormat()
    frame.setBackground(code_bg)
    frame.setPadding(gap)
    frame.setBorder(0)
    frame.setBottomMargin(gap)
    for start, end in reversed(runs):
        cursor = QTextCursor(doc)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        cursor.insertFrame(frame)
    if not runs:
        return
    # Рамке Qt нужен пустой абзац до и после неё. Их не убрать, но можно
    # сплющить: иначе над кодом и под ним по лишней пустой строке.
    block = doc.begin()
    while block.isValid():
        if not block.text() and block.layout() is not None and _beside_frame(block, doc):
            fmt = block.blockFormat()
            fmt.setLineHeight(0.0, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
            fmt.setTopMargin(0)
            fmt.setBottomMargin(0)
            QTextCursor(block).setBlockFormat(fmt)
        block = block.next()


def _beside_frame(block, doc: QTextDocument) -> bool:
    """Пустой абзац самого документа рядом с рамкой кода — служебный."""
    if QTextCursor(block).currentFrame() is not doc.rootFrame():
        return False
    for near in (block.previous(), block.next()):
        if near.isValid() and QTextCursor(near).currentFrame() is not doc.rootFrame():
            return True
    return False


def _source_label(url: str, shared_host: bool) -> str:
    """Подпись источника: домен, а если с одного домена несколько страниц, —
    и хвост пути, иначе «pytorch.org · pytorch.org» ничего не различает."""
    host = _domain(url)
    if not shared_host:
        return host
    tail = next((part for part in reversed(urlparse(url).path.split("/")) if part), "")
    tail = tail.rsplit(".", 1)[0] if tail.endswith((".html", ".htm")) else tail
    if len(tail) > 28:
        tail = tail[:27] + "…"
    return f"{host}/…/{tail}" if tail else host


def _blurred(screen, region: QRect) -> tuple[QImage | None, bool]:
    """Снимок фона под карточкой, размытый уменьшением, и светлый ли он."""
    try:
        grabbed = screen.grabWindow(0, region.x(), region.y(), region.width(), region.height())
    except Exception as exc:  # noqa: BLE001 — без снимка карточка обойдётся вуалью
        print(f"[card] не удалось снять фон: {exc}")
        return None, False
    if grabbed.isNull():
        return None, False
    image = grabbed.toImage().convertToFormat(QImage.Format_RGB32)
    small = image.scaled(
        max(1, image.width() // BLUR_DIV), max(1, image.height() // BLUR_DIV),
        Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
    )
    # Средняя светимость по уменьшенному снимку: этого хватает, чтобы выбрать
    # вуаль, и не стоит прохода по миллиону пикселей.
    raw = np.frombuffer(small.constBits(), dtype=np.uint8, count=small.sizeInBytes())
    pixels = raw.reshape(small.height(), small.bytesPerLine())[:, : small.width() * 4].reshape(-1, 4)
    luma = (0.0722 * pixels[:, 0] + 0.7152 * pixels[:, 1] + 0.2126 * pixels[:, 2]).mean() / 255.0
    blurred = small.scaled(region.width(), region.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return blurred, bool(luma >= theme.MATERIAL_THRESHOLD)


def _no_activate(widget: QWidget) -> None:
    """Клик по карточке не должен уводить фокус из окна, где работает человек.

    Флага Qt WindowDoesNotAcceptFocus хватает для клавиатуры, но не для мыши:
    без WS_EX_NOACTIVATE нажатие кнопки активирует окно карточки, и «Вставить»
    вставило бы текст в неё саму.
    """
    if sys.platform != "win32":
        return
    import ctypes

    gwl_exstyle, ws_ex_noactivate = -20, 0x08000000
    user32 = ctypes.windll.user32
    hwnd = int(widget.winId())
    style = user32.GetWindowLongW(hwnd, gwl_exstyle)
    user32.SetWindowLongW(hwnd, gwl_exstyle, style | ws_ex_noactivate)
