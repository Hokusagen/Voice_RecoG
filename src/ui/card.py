"""Карточка ответа Дарви: вопрос голосом — ответ в углу экрана, поверх работы.

Решения — design/DARVI-SKILLS.md, «Где живёт Дарви на экране» (6.10.2026):
Дарви живёт в углу, и карточка раскрывается от него; фокус она не забирает —
в своём окне работаешь дальше, а кнопки нажимаются мышью; стекло плотнее, чем у
пилюли, потому что на нём читают абзацы, а не одну строку. Движение одно:
высота растёт пружиной вслед за текстом, который приходит потоком.

В карточке весь разговор, а не последний ответ (отзыв 7.10: «хочется посмотреть,
что там было раньше»): первый вопрос — темой в шапке, уточнения с ответами —
ниже одной лентой. Выше потолка лента листается, и новый вопрос встаёт к
верхнему краю, чтобы ответ читался с начала.

Ширину тянут мышью за свободный край, как у обычного окна: край у угла стоит
на месте, а ширина запоминается в ui.card_width (отзыв на живой прогон 7.10:
карточка на полсантиметра закрывала соседний чат).

Окно сразу размером с самую большую карточку — во всю допустимую высоту и
ширину, — а видимая карточка растёт и тянется внутри него. Менять размер окна
каждый кадр — заметно дёргается; а прозрачные пиксели многослойного окна
Windows пропускает к окнам под ним, так что пустая часть окна мыши не мешает.

Стекло — снимок фона, размытый уменьшением, под плотной вуалью. Снимок делается
до показа, пока окна нет на экране, и дальше не обновляется: под вуалью такой
плотности отставание от прокрутки почти не видно. Живое стекло композитора —
у плашки (ui/lens_hud.py); переносить на него карточку — когда её вид устоится.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from urllib.parse import urlparse

import numpy as np
from PySide6.QtCore import QRect, QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
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

#: Самая широкая карточка — та же доля рабочей ширины: шире строки читаются
#: хуже, а работа под карточкой закрыта почти вся.
MAX_WIDTH_SHARE = 0.6

#: Самая узкая карточка, px до масштаба; уже неё не дают и кнопки под ответом.
MIN_WIDTH = 320

#: Полоса, за которую тянут ширину: половина снаружи карточки, половина
#: внутри — как невидимая рамка, за которую тянут окна Windows 10.
GRIP = 10

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

#: Метка абзацев, которые карточка вставляет в ленту сама: вопросов, распорок
#: перед ответами и строк под ними. Их вид задан при вставке — _shape не трогает.
_ROLE = QTextFormat.UserProperty + 1

SEARCHING = "ищу в интернете…"


@dataclass
class _Turn:
    """Ход разговора, как его показывает карточка."""

    question: str
    answer: str = ""
    """Markdown ответа, как пришёл из потока."""

    sources: list[str] = field(default_factory=list)
    note: str = ""
    """Строка под ответом вместо источников: «ищу в интернете…», «не вышло: …»."""

    failed: bool = False
    """Ответа не будет: модель его не помнит, и следующий вопрос встанет на это место."""


class AnswerCard(QWidget):
    insert_requested = Signal(str)
    """«Вставить»: последний ответ без разметки — в окно, где курсор."""

    recheck_requested = Signal()
    """«Проверить в интернете»: последний вопрос заново с поиском."""

    closed = Signal()
    """Человек закрыл карточку крестиком — разговор окончен."""

    resized = Signal(int)
    """Ширину дотянули и отпустили мышь: новая ширина, px до масштаба. В
    ui.card_width она уже записана — осталось сохранить настройки."""

    def __init__(self, cfg: UIConfig) -> None:
        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.cfg = cfg
        self._scale = max(0.75, float(cfg.hud_scale or 1.0))

        self._conversation = ""
        self._turns: list[_Turn] = []
        self._pending: int | None = None
        """Ход, ответ на который ещё идёт."""

        self._waiting = False
        """Первое слово ответа на _pending ещё не пришло."""

        self._previous: _Turn | None = None
        """Перепроверяемый ход, каким он был: его ответ виден до первого слова
        нового и возвращается, если перепроверка не удалась."""

        self._deferred: tuple[str, int, str, bool] | None = None
        """Вопрос, который покажется с первым словом ответа: карточка скрыта
        или разговор новый. Пустой карточка не нужна, а прежний разговор на
        экране лучше нового без ответа."""

        self._pin: int | None = None
        """Ход, чей вопрос держим у верхнего края, пока человек не листал сам."""

        self._anchors: list[int] = []
        """Где в документе начинается каждый ход."""

        self._code_bg = QColor(0, 0, 0, 13)
        self._backdrop: QImage | None = None
        self._light = False
        self._top = False
        self._right = True
        self._max_h = 0
        self._width = 0
        """Ширина карточки, px с масштабом; окно всегда шириной _max_w."""

        self._min_w = 0
        self._max_w = 0

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
        # Своя наименьшая высота у поля — под стрелки полосы прокрутки, 53 px,
        # почти три строки. Высоту карточки считает _wanted_height по тексту,
        # и на ответе в строку раскладка, не влезая в свой минимум, сплющивала
        # бы кнопки и шапку.
        self._text.setMinimumHeight(1)
        layout.addWidget(self._text, 1)
        bar = self._text.verticalScrollBar()
        bar.actionTriggered.connect(self._unpin)
        bar.rangeChanged.connect(self._hold_pin)

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

        self._grip = _Grip(self)
        self._grip.hide()
        # Поля кнопок задаёт таблица стилей, а по кнопкам считается самая
        # узкая карточка: стиль нужен до первого показа.
        self._apply_material()

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
        self._muted = QColor(glass.detail)
        self._link = QColor(link)
        self._code_bg = QColor(0, 0, 0, 13) if self._light else QColor(255, 255, 255, 18)

    # ---------- что показывать ----------

    @Slot(str, int, str, bool)
    def start(self, conversation: str, turn: int, question: str, searching: bool) -> None:
        """Вопрос ушёл модели. turn — номер хода с единицы; у перепроверки —
        номер хода, который она заменит.

        Открытая карточка того же разговора показывает вопрос сразу: видно, как
        его расслышали, пока модель думает или ищет. Скрытая карточка и новый
        разговор ждут первого слова ответа.
        """
        if conversation == self._conversation and self.is_open():
            self._deferred = None
            self._begin(turn - 1, question, searching)
        else:
            self._deferred = (conversation, turn - 1, question, searching)

    @Slot(str)
    def feed(self, piece: str) -> None:
        """Очередной кусок ответа из потока."""
        if self._deferred is not None:
            conversation, index, question, searching = self._deferred
            self._deferred = None
            if conversation != self._conversation:
                self._conversation, self._turns = conversation, []
            self._begin(index, question, searching)
        if self._pending is None:
            return
        turn = self._turns[self._pending]
        if self._waiting:
            # Первое слово: прежний ответ перепроверяемого хода и «ищу в
            # интернете…» уступают место новому ответу.
            self._waiting = False
            turn.answer, turn.sources, turn.note = "", [], ""
        turn.answer += piece
        if not self.is_open():
            self._appear()
        elif not self._render_timer.isActive():
            self._render_timer.start()

    @Slot(list)
    def finish(self, sources: list[str]) -> None:
        """Ответ дописан: источники под ним и кнопки."""
        self._deferred = None
        if self._pending is None:
            return
        if self._waiting and self._previous is not None:
            # Перепроверка вернула пустой ответ — прежний лучше пустого.
            self._turns[self._pending] = replace(self._previous, note="")
        else:
            turn = self._turns[self._pending]
            turn.sources, turn.note = list(sources), ""
        self._pending, self._previous, self._waiting = None, None, False
        self._render()

    @Slot(str)
    def fail(self, reason: str) -> None:
        """Ответа не будет.

        Скрытая карточка не появляется — ошибку покажет плашка. У открытой ход
        получает строку «не вышло», а перепроверка возвращает прежний ответ.
        """
        self._deferred = None
        note = f"не вышло: {reason}"
        if self._pending is None:
            # Перепроверка упала, не дойдя до вопроса, — а кнопка уже
            # написала под ответом «ищу в интернете…».
            if self._turns and self._turns[-1].note == SEARCHING:
                self._turns[-1].note = note
                self._render()
            return
        if self._previous is not None:
            self._turns[self._pending] = replace(self._previous, note=note)
        else:
            turn = self._turns[self._pending]
            turn.note, turn.failed = note, True
        self._pending, self._previous, self._waiting = None, None, False
        self._render()

    def dismiss(self) -> None:
        """Убрать карточку, не заканчивая разговор: человек вернулся к работе."""
        if not self.is_open():
            return
        self._grip.release()
        self._hiding = True
        self._height.set(0.0)
        self._tick.start()

    def is_open(self) -> bool:
        """Карточка на экране и не уходит: вопрос сейчас продолжит её разговор."""
        return self.isVisible() and not self._hiding

    def _begin(self, index: int, question: str, searching: bool) -> None:
        """Ход index ждёт ответа: новый вопрос в конце ленты или перепроверка.

        Ход с тем же вопросом и готовым ответом — перепроверка: ответ виден,
        пока не придёт первое слово нового. Неудачный ход на этом месте
        уступает его новому вопросу — модель того хода не помнит.
        """
        index = min(index, len(self._turns))
        current = self._turns[index] if index < len(self._turns) else None
        del self._turns[index:]
        note = SEARCHING if searching else ""
        recheck = current is not None and current.question == question and bool(current.answer) and not current.failed
        self._previous = current if recheck else None
        self._turns.append(replace(current, note=note) if recheck else _Turn(question, note=note))
        self._pending, self._waiting, self._pin = index, True, index
        if self.is_open():
            self._render()

    # ---------- кнопки ----------

    def _plain(self) -> str:
        """Последний ответ без разметки: кнопки под лентой — для него."""
        if not self._turns:
            return ""
        doc = QTextDocument()
        doc.setMarkdown(clean_answer(self._turns[-1].answer))
        return doc.toPlainText().strip()

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
        if self._turns:
            # Сразу, а не когда до задачи дойдёт очередь конвейера.
            self._turns[-1].note = SEARCHING
            self._render()
        self.recheck_requested.emit()

    def _on_close(self) -> None:
        # Разговор окончен: хвост ответа, если он ещё идёт, карточку не вернёт.
        self._pending = self._previous = self._deferred = None
        self._waiting = False
        self._conversation = ""
        self.dismiss()
        self.closed.emit()

    def _flash(self, button: QPushButton, text: str) -> None:
        button.setText(text)
        QTimer.singleShot(1400, lambda: button.setText(button.property("label")))

    # ---------- геометрия и движение ----------

    def _appear(self) -> None:
        self._hiding = False
        screen = QApplication.screenAt(QCursor.pos()) if self.cfg.hud_follow_cursor else None
        screen = screen or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self._max_h = int(area.height() * MAX_SHARE)
        self._min_w = self._narrowest()
        self._max_w = max(self._min_w, min(int(area.width() * MAX_WIDTH_SHARE), area.width() - 2 * MARGIN))
        self._width = max(self._min_w, min(self._max_w, int(self.cfg.card_width * self._scale)))
        corner = (self.cfg.card_corner or "bottom-right").lower()
        self._top = corner.startswith("top")
        self._right = not corner.endswith("left")
        x = area.right() - MARGIN - self._max_w if self._right else area.left() + MARGIN
        y = area.top() + MARGIN if self._top else area.bottom() - MARGIN - self._max_h
        self.setGeometry(x, y, self._max_w, self._max_h)

        # Снимок — пока окна нет на экране, иначе в стекло попадёт оно само.
        # Снимается всё окно: карточку могут растянуть, и под новой шириной
        # тоже нужен фон, а снять его заново уже нельзя.
        column = QRect(self._max_w - self._width if self._right else 0, 0, self._width, self._max_h)
        self._backdrop, self._light = _blurred(screen, QRect(x, y, self._max_w, self._max_h), column)
        self._apply_material()
        self._render()  # цвета ленты зависят от фона под карточкой
        self._height.snap(0.0)
        self._place()
        self.show()
        _no_activate(self)
        self._retarget()
        self._tick.start()

    def _render(self) -> None:
        """Лента разговора целиком: вопросы, ответы, строки под ними.

        Собирается заново при каждой перерисовке: сама сборка пяти ходов —
        меньше миллисекунды, перерисовка двух длинных ходов с раскладкой — 6 мс
        (замер 8.10). Вырезать из документа старый хвост вместе с рамками кода
        сложнее и хрупче.
        """
        self._render_timer.stop()
        doc = self._text.document()
        bar = self._text.verticalScrollBar()
        keep = bar.value()
        gap = int(round(8 * self._scale))
        self._anchors = []  # до очистки: прижим не должен искать старые места
        doc.clear()
        cursor = QTextCursor(doc)
        cursor.beginEditBlock()
        for index, turn in enumerate(self._turns):
            if index:
                cursor.insertBlock(_block("question", top=2 * gap, bottom=gap // 2), self._small())
                cursor.insertText(turn.question)
                cursor.insertBlock(_block("spacer"), QTextCharFormat())
            else:
                cursor.setBlockFormat(_block("spacer"))
            if turn.answer:
                cursor.insertFragment(self._fragment(turn.answer))
            footer = self._footer(turn)
            if footer:
                cursor.insertBlock(_block("footer", bottom=gap), self._small())
                for text, href in footer:
                    cursor.insertText(text, self._small(href))
        # _shape — внутри той же правки: иначе каждый поправленный абзац
        # раскладывается заново, и одна только _shape стоила 5.8 мс из 10.9.
        _shape(doc, self._code_bg, self._link, gap)
        cursor.endEditBlock()
        # Начала ходов — после _shape: рамки кода сдвигают всё, что ниже них.
        self._anchors = [0] if self._turns else []
        block = doc.begin()
        while block.isValid():
            if block.blockFormat().property(_ROLE) == "question":
                self._anchors.append(block.position())
            block = block.next()
        self._question_label.setText(self._turns[0].question if self._turns else "")
        self._update_actions()
        doc.size()  # раскладка целиком, чтобы прокрутка знала новую длину
        if self._pin is None:
            bar.setValue(keep)
        else:
            self._hold_pin()
        self._retarget()

    def _fragment(self, markdown: str) -> QTextDocumentFragment:
        """Ответ, разобранный из Markdown, — кусок для вставки в ленту.

        Вставленный кусок сливает свой первый абзац с тем, куда его вставили,
        и абзац теряет вид: заголовок становится текстом, первая строка кода —
        строкой без подложки. Поэтому в начало куска кладётся пустой абзац —
        сливается он, с распоркой нулевой высоты.
        """
        piece = QTextDocument()
        piece.setDefaultFont(self._text.document().defaultFont())
        piece.setMarkdown(clean_answer(markdown))
        QTextCursor(piece).insertBlock()
        return QTextDocumentFragment(piece)

    def _footer(self, turn: _Turn) -> list[tuple[str, str]]:
        """Строка под ответом кусками (текст, ссылка): что с ним или откуда он."""
        if turn.note:
            return [(turn.note, "")]
        shown = turn.sources[:4]
        if not shown:
            return []
        hosts = [_domain(url) for url in shown]
        line = [("Источники: ", "")]
        for index, (url, host) in enumerate(zip(shown, hosts)):
            if index:
                line.append((" · ", ""))
            line.append((_source_label(url, hosts.count(host) > 1), url))
        return line

    def _small(self, href: str = "") -> QTextCharFormat:
        """Мелкий приглушённый текст ленты: уточнения и строки под ответами."""
        fmt = QTextCharFormat()
        fmt.setProperty(QTextFormat.FontPixelSize, max(9, int(round(12 * self._scale))))
        fmt.setForeground(self._link if href else self._muted)
        if href:
            fmt.setAnchor(True)
            fmt.setAnchorHref(href)
        return fmt

    def _update_actions(self) -> None:
        """Кнопки — у готового последнего ответа: к нему они и относятся.

        Недописанному ответу кнопки не нужны — «Вставить» вставило бы обрывок.
        Перепроверяемый ответ до первого слова нового цел, и кнопки при нём
        остаются, чтобы карточка не прыгала.
        """
        last = self._turns[-1] if self._turns else None
        rechecking = self._waiting and self._previous is not None
        ready = last is not None and bool(last.answer.strip()) and not last.failed
        ready = ready and (self._pending is None or rechecking)
        self._actions.setVisible(ready)
        if ready:
            self._recheck.setVisible(not last.sources)
            self._recheck.setEnabled(self._pending is None)

    def _unpin(self, _action: int) -> None:
        """Человек листает сам: новый вопрос у края больше не держим."""
        self._pin = None

    def _hold_pin(self, *_range) -> None:
        """Вопрос хода _pin — у верхнего края, насколько хватает длины ленты.

        Зовётся и на каждое изменение длины прокрутки: лента растёт, пока
        идёт ответ, и окно просмотра растёт вместе с карточкой.
        """
        if self._pin is None or self._pin >= len(self._anchors):
            return
        doc = self._text.document()
        block = doc.findBlock(self._anchors[self._pin])
        top = doc.documentLayout().blockBoundingRect(block).top()
        bar = self._text.verticalScrollBar()
        bar.setValue(min(int(top), bar.maximum()))

    def _retarget(self, snap: bool = False) -> None:
        """Высота — под содержимое. snap — сразу, без пружины: когда тянут край,
        пружина отставала бы от руки."""
        if not self.isVisible() or self._hiding:
            return
        wanted = self._wanted_height()
        # Полоса прокрутки — только у карточки, упёршейся в потолок. Иначе
        # мелькнувшая на полкадра полоса сужает текст, он становится на строку
        # выше расчёта — и полоса остаётся навсегда.
        capped = wanted > self._max_h
        self._text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if capped else Qt.ScrollBarAlwaysOff)
        target = float(min(wanted, self._max_h))
        if snap:
            self._height.snap(target)
            self._place()
            self.update()
            return
        self._height.set(target)
        if not self._tick.isActive():
            self._tick.start()

    def _wanted_height(self) -> int:
        """Высота, при которой виден весь разговор; потолок — забота вызывающего."""
        inner = self._width - 2 * PAD
        text_h = self._text_height(self._width - PAD - (PAD - 6))
        total = PAD - 4 + max(self._question_label.heightForWidth(inner - 30), self._close.height())
        total += GAP + text_h + 4
        if not self._actions.isHidden():
            total += GAP + self._actions.sizeHint().height()
        total += PAD
        return total

    def _text_height(self, width: int) -> int:
        """Высота текста ответа при ширине width."""
        doc = self._text.document()
        # Ширину своего документа QTextBrowser выставляет сам по окну
        # просмотра. Если текст уже разложен на нужную ширину — мерка готова;
        # нет (до первой раскладки или под полосой прокрутки) — мерить копию.
        if abs(doc.textWidth() - width) < 0.5:
            return int(doc.size().height())
        copy = doc.clone(self)
        # Копия теряет вид первого абзаца — распорки нулевой высоты, — и
        # короткий ответ мерился бы на строку выше: пустая строка под ним.
        QTextCursor(copy).setBlockFormat(doc.begin().blockFormat())
        copy.setTextWidth(width)
        height = int(copy.size().height())
        copy.deleteLater()
        return height

    def _narrowest(self) -> int:
        """Уже этой ширины кнопки под ответом не помещаются в ряд."""
        buttons = (self._insert, self._copy, self._recheck)
        row = sum(button.sizeHint().width() for button in buttons) + 6 * (len(buttons) - 1)
        return max(int(MIN_WIDTH * self._scale), row + PAD + (PAD - 6))

    def _card_rect(self) -> QRect:
        height = max(0, min(self._max_h, int(round(self._height.value))))
        x = self._max_w - self._width if self._right else 0
        y = 0 if self._top else self._max_h - height
        return QRect(x, y, self._width, height)

    def _place(self) -> None:
        rect = self._card_rect()
        # Растёт карточка, а не сжимается текст внутри неё: содержимое — по
        # высоте цели пружины, прижато к верху, лишнее срезает окошко.
        self._clip.setGeometry(rect)
        self._body.setGeometry(0, 0, rect.width(), max(rect.height(), int(self._height.target)))
        shown = rect.height() > 2 * PAD
        self._clip.setVisible(shown)
        edge = rect.left() if self._right else rect.right() + 1
        self._grip.setGeometry(edge - GRIP // 2, rect.top(), GRIP, rect.height())
        self._grip.setVisible(shown and not self._hiding)

    def _drag(self, width: int) -> None:
        """Свободный край тянут: ширина за мышью, край у угла стоит на месте."""
        width = max(self._min_w, min(self._max_w, int(width)))
        if width == self._width or self._hiding:
            return
        self._width = width
        self._place()
        self._retarget(snap=True)

    def _dropped(self) -> None:
        """Мышь отпустили: ширину — в настройки, до масштаба."""
        width = round(self._width / self._scale)
        if width != self.cfg.card_width:
            self.cfg.card_width = width
            self.resized.emit(width)

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


class _Grip(QWidget):
    """Свободный край карточки: за него тянут ширину, как у обычного окна.

    Ширина идёт за курсором по опросу, а не по событиям мыши. Окно карточки
    никогда не становится активным, а «только окно переднего плана может
    захватить мышь; фоновое получает её события, лишь пока курсор над его
    видимой частью» (Microsoft, Mouse Input Overview). Быстрая рука уходила бы
    с края в прозрачную часть окна — и край замирал бы, не дождавшись её.
    """

    def __init__(self, card: AnswerCard) -> None:
        super().__init__(card)
        self._card = card
        self._from: tuple[int, int] | None = None
        """Где курсор и какая ширина были в момент нажатия."""

        self.setCursor(Qt.SizeHorCursor)
        self._poll = QTimer(self)
        self._poll.setInterval(16)
        self._poll.timeout.connect(self._follow)

    def paintEvent(self, _event) -> None:  # noqa: N802 — имя из Qt
        # Полностью прозрачные пиксели Windows отдаёт окну под карточкой, и
        # наружная половина края мышь не ловила бы. Альфа 1 глазу не видна.
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 1))

    def mousePressEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        if event.button() == Qt.LeftButton:
            self._from = (QCursor.pos().x(), self._card._width)
            self._poll.start()

    def mouseReleaseEvent(self, _event) -> None:  # noqa: N802 — имя из Qt
        self.release()

    def release(self) -> None:
        """Конец перетаскивания: последнее положение курсора — и ширину в настройки."""
        if self._from is None:
            return
        self._follow(final=True)
        self._from = None
        self._poll.stop()
        self._card._dropped()

    def _follow(self, final: bool = False) -> None:
        if self._from is None:
            return
        if not final and not _primary_button_down():
            # Кнопку отпустили там, где событие до карточки не дошло.
            self.release()
            return
        start_x, start_width = self._from
        shift = QCursor.pos().x() - start_x
        self._card._drag(start_width - shift if self._card._right else start_width + shift)


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
        if fmt.hasProperty(_ROLE):
            block = block.next()
            continue
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


def _block(role: str, top: int = 0, bottom: int = 0) -> QTextBlockFormat:
    """Абзац, который карточка вставляет в ленту сама; распорка — нулевой высоты."""
    fmt = QTextBlockFormat()
    fmt.setProperty(_ROLE, role)
    fmt.setTopMargin(top)
    fmt.setBottomMargin(bottom)
    if role == "spacer":
        fmt.setLineHeight(0.0, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    return fmt


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


def _blurred(screen, region: QRect, focus: QRect) -> tuple[QImage | None, bool]:
    """Снимок фона под окном карточки, размытый уменьшением, и светлый ли он
    там, где встанет сама карточка (focus — в координатах окна)."""
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
    pixels = raw.reshape(small.height(), small.bytesPerLine())[:, : small.width() * 4]
    pixels = pixels.reshape(small.height(), small.width(), 4)
    # Окно шире карточки, а вуаль выбирается по тому, что под ней самой.
    left, right = focus.left() // BLUR_DIV, -(-(focus.right() + 1) // BLUR_DIV)
    under = pixels[:, max(0, left):max(left + 1, right)].reshape(-1, 4)
    luma = (0.0722 * under[:, 0] + 0.7152 * under[:, 1] + 0.2126 * under[:, 2]).mean() / 255.0
    blurred = small.scaled(region.width(), region.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return blurred, bool(luma >= theme.MATERIAL_THRESHOLD)


def _primary_button_down() -> bool:
    """Зажата ли основная кнопка мыши сейчас, а не в последнем событии окна."""
    if sys.platform != "win32":
        return bool(QGuiApplication.mouseButtons() & Qt.LeftButton)
    import ctypes

    user32 = ctypes.windll.user32
    # GetAsyncKeyState смотрит на физические кнопки, а у левши, поменявшего
    # их местами (SM_SWAPBUTTON), основная — правая.
    sm_swapbutton, vk_lbutton, vk_rbutton = 23, 0x01, 0x02
    button = vk_rbutton if user32.GetSystemMetrics(sm_swapbutton) else vk_lbutton
    return bool(user32.GetAsyncKeyState(button) & 0x8000)


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
