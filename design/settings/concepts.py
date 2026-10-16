"""Лаборатория окна настроек: одно содержание, три раскладки и два вида.

    venv\\Scripts\\python.exe design\\settings\\concepts.py

Слева вверху пульт: раскладка, вид и «Остановить демо». Окно живое — разделы
листаются, списки раскрываются, переключатели щёлкают, сочетание клавиш
записывается, — но ничего не сохраняет: значения — умолчания Config, ключи —
заглушки. Если поменять поле, которое приложение читает только при запуске,
внизу появится просьба перезапустить — так она будет выглядеть и в чистовике.

Сочетание здесь ловит само окно; запущенный VoiceTyper слышит те же клавиши
своим хуком, поэтому F8 в концепте поднимет и его диктовку. В чистовике
сочетание ловит общий хук, и этого не будет.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import Config, build_version

# ---------- содержание: одно на все раскладки ----------


@dataclass
class Row:
    kind: str
    """hotkey | choice | toggle | text | secret | slider | button | info | mic"""

    title: str
    hint: str = ""
    path: str = ""
    options: tuple = ()
    visible: Callable[[dict], bool] | None = None


@dataclass
class Group:
    title: str
    rows: list[Row]


@dataclass
class Section:
    title: str
    groups: list[Group] = field(default_factory=list)


ASK_SERVERS = {
    "": ("openai/gpt-oss-120b", "medium"),
    "giga": ("GigaChat-3-Ultra", ""),
    "custom": None,
}


def content() -> list[Section]:
    position = (
        ("bottom", "Снизу по центру"), ("top", "Сверху по центру"),
        ("bottom-right", "Справа снизу"), ("bottom-left", "Слева снизу"),
        ("top-right", "Справа сверху"), ("top-left", "Слева сверху"),
    )
    corner = position[2:]
    return [
        Section("Диктовка", [
            Group("Клавиши", [
                Row("hotkey", "Диктовка", "зажал, сказал, отпустил", "hotkeys.record"),
                Row("hotkey", "Другой стиль правки", "та же диктовка, правка другого стиля", "hotkeys.record_alt"),
                Row("hotkey", "Без правки", "ровно то, что расслышал Whisper", "hotkeys.record_raw"),
                Row("hotkey", "Запомнить правку", "выдели исправленный текст и нажми", "hotkeys.correct"),
                Row("hotkey", "Спросить Дарви", "ответ — в карточку, в текст не вставляется", "hotkeys.ask"),
                Row("hotkey", "Отмена", "сбросить запись, пока говоришь", "hotkeys.cancel"),
                Row("choice", "Режим клавиши", "", "hotkeys.mode",
                    (("hold", "Удерживать"), ("toggle", "Нажать — нажать"))),
            ]),
            Group("Правка", [
                Row("choice", "Стиль по основной клавише", "другой — по своей клавише", "llm.style",
                    (("careful", "Бережная"), ("dry", "Сухая"))),
                Row("choice", "Где править", "облако — по ключу в разделе «Облако»", "llm.backend",
                    (("local", "Ollama"), ("cloud", "Облако"))),
            ]),
            Group("Микрофон", [
                Row("mic", "Микрофон", "со следующей записи", "audio.device"),
                Row("toggle", "Хранить звук диктовок", "для замеров распознавания, до 500 МБ", "audio.keep_dictations"),
            ]),
        ]),
        Section("Дарви", [
            Group("Как спрашивать", [
                Row("toggle", "Обращение по имени", "«Дарви, …» в начале диктовки — вопрос", "ask.by_name"),
                Row("toggle", "Искать перед каждым ответом", "без этого — по кнопке в карточке или просьбой", "ask.web_search"),
                Row("text", "О себе", "система и версии: ответы про код будут для них", "ask.about"),
            ]),
            Group("Кто отвечает", [
                Row("choice", "Сервер", "", "_ask_server",
                    (("", "Groq"), ("giga", "GigaChat"), ("custom", "Свой"))),
                Row("text", "Адрес сервера", "OpenAI-совместимый, …/v1", "ask.url",
                    visible=lambda v: v["_ask_server"] == "custom"),
                Row("secret", "Ключ сервера", "у GigaChat — ключ авторизации", "ask.api_key",
                    visible=lambda v: v["_ask_server"] != ""),
                Row("text", "Модель", "", "ask.model"),
                Row("choice", "Раздумья", "GigaChat с раздумьями молчит", "ask.reasoning_effort",
                    (("", "Без"), ("low", "Немного"), ("medium", "Средне"), ("high", "Долго"))),
            ]),
            Group("Поиск", [
                Row("secret", "Ключ Tavily", "без него ищет встроенный поиск Groq", "ask.search_key"),
                Row("choice", "Глубина", "глубоко — вдвое дороже", "ask.search_depth",
                    (("fast", "Быстро"), ("basic", "Обычно"), ("advanced", "Глубоко"))),
            ]),
        ]),
        Section("Плашка и звук", [
            Group("Плашка", [
                Row("toggle", "Показывать плашку", "", "ui.hud_enabled"),
                Row("choice", "Где", "", "ui.hud_position", position),
                Row("choice", "Появление", "", "ui.hud_appear",
                    (("drop", "Капля"), ("drop-single", "Одним движением"))),
                Row("toggle", "На мониторе с курсором", "", "ui.hud_follow_cursor"),
                Row("choice", "Угол карточки Дарви", "", "ui.card_corner", corner),
            ]),
            Group("Звук", [
                Row("toggle", "Звуки", "начало и конец записи, готово, ошибка", "ui.sounds"),
                Row("slider", "Громкость", "", "ui.volume"),
            ]),
        ]),
        Section("Облако", [
            Group("Основное", [
                Row("secret", "Ключ Groq", "распознавание и правка в облаке", "cloud.api_key"),
                Row("text", "Адрес", "например, через Cloudflare AI Gateway", "cloud.url"),
                Row("text", "Модель правки", "", "cloud.model"),
            ]),
            Group("Запасное", [
                Row("secret", "Ключ OpenRouter", "если основное молчит; тариф платный", "cloud.reserve.api_key"),
            ]),
        ]),
        Section("Система", [
            Group("Запуск", [
                Row("toggle", "Запускать с Windows", "", "ui.autostart"),
                Row("toggle", "Отдать видеокарту", "Whisper на процессоре или в облаке, редактор выгружен", "release_gpu"),
            ]),
            Group("Файлы", [
                Row("button", "Журнал диктовок", "что распознано, как поправлено, вопросы Дарви", "Открыть журнал"),
                Row("button", "Остальное", "промпты, тайм-ауты, лимиты — руками в файле", "Открыть config.json"),
                Row("info", "Версия", "сверять с журналом, когда что-то сломалось", "_version"),
            ]),
        ]),
    ]


#: Поля, которые приложение читает только при запуске.
RESTART = {
    "cloud.url", "cloud.api_key", "cloud.model", "cloud.reserve.api_key",
    "ask.url", "ask.api_key", "ask.model", "ask.reasoning_effort",
    "ask.search_key", "ask.search_depth", "audio.keep_dictations", "_ask_server",
}


def initial_values() -> dict[str, Any]:
    cfg = Config()
    values: dict[str, Any] = {}
    for section in content():
        for group in section.groups:
            for row in group.rows:
                if row.path and not row.path.startswith("_") and row.kind not in ("button",):
                    target: Any = cfg
                    for part in row.path.split("."):
                        target = getattr(target, part)
                    values[row.path] = target
    # Заглушки, чтобы было видно, как выглядит заданный и пустой ключ.
    values["cloud.api_key"] = "gsk_заглушка_для_концепта"
    values["cloud.url"] = "https://gateway.ai.cloudflare.com/v1/…/groq"
    values["_ask_server"] = ""
    values["_version"] = build_version()
    return values


def pretty_combo(combo: str) -> str:
    names = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "windows": "Win", "esc": "Esc"}
    parts = [part for part in combo.split("+") if part]
    return " + ".join(names.get(part, part.upper() if len(part) <= 3 else part.capitalize()) for part in parts)


def microphones() -> list[tuple[int | None, str]]:
    found: list[tuple[int | None, str]] = [(None, "Как в системе")]
    try:
        import sounddevice as sd

        default = sd.query_devices(kind="input")
        for index, device in enumerate(sd.query_devices()):
            if device["max_input_channels"] > 0 and device["hostapi"] == default["hostapi"]:
                found.append((index, device["name"]))
    except Exception as exc:
        print(f"[concepts] микрофоны: {exc}")
    return found


# ---------- виды ----------


@dataclass(frozen=True)
class Look:
    own: bool
    dark: bool

    def colors(self) -> dict[str, str]:
        if self.dark:
            return dict(window="#202020", side="#1a1a1a", field="#2c2c2c", line="#3a3a3a",
                        text="#ececec", muted="#9b9b9b", accent="#79b0ff", on_accent="#0b1a2e",
                        select="#2f2f2f", hover="#353535")
        return dict(window="#f7f7f7", side="#ededed", field="#ffffff", line="#d8d8d8",
                    text="#1b1b1b", muted="#6b6b6b", accent="#2a66d0", on_accent="#ffffff",
                    select="#dddddd", hover="#f0f0f0")


def own_palette(c: dict[str, str]) -> QPalette:
    palette = QPalette()
    roles = {
        QPalette.Window: c["window"], QPalette.WindowText: c["text"], QPalette.Base: c["field"],
        QPalette.AlternateBase: c["side"], QPalette.Text: c["text"], QPalette.Button: c["field"],
        QPalette.ButtonText: c["text"], QPalette.Highlight: c["accent"],
        QPalette.HighlightedText: c["on_accent"], QPalette.PlaceholderText: c["muted"],
        QPalette.ToolTipBase: c["field"], QPalette.ToolTipText: c["text"], QPalette.Mid: c["line"],
        QPalette.Midlight: c["line"], QPalette.Light: c["field"], QPalette.Dark: c["side"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    return palette


def own_style(c: dict[str, str]) -> str:
    return f"""
    QLabel#pageTitle {{ font-size: 16pt; font-weight: 600; padding: 0 0 6px 0; }}
    QLabel#sectionTitle {{ font-size: 14pt; font-weight: 600; padding: 22px 0 0 0; }}
    QLabel#groupTitle {{ font-size: 9pt; font-weight: 600; color: {c['muted']}; padding: 16px 0 4px 0; }}
    QLabel#rowHint {{ color: {c['muted']}; font-size: 9pt; }}
    QFrame#row {{ border-bottom: 1px solid {c['line']}; }}
    QLineEdit, QComboBox {{
        background: {c['field']}; border: 1px solid {c['line']}; border-radius: 6px;
        padding: 5px 8px; min-width: 230px;
    }}
    QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c['field']}; border: 1px solid {c['line']}; selection-background-color: {c['select']};
        selection-color: {c['text']}; outline: 0; padding: 4px;
    }}
    QPushButton {{
        background: {c['field']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 5px 14px;
    }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton#hotkey {{ font-weight: 600; min-width: 140px; }}
    QPushButton#hotkey[waiting="true"] {{ border-color: {c['accent']}; color: {c['accent']}; }}
    QPushButton[segment] {{ border-radius: 0; padding: 5px 12px; margin: 0; }}
    QPushButton[segment="first"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    QPushButton[segment="last"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    QPushButton[segment="only"] {{ border-radius: 6px; }}
    QPushButton[segment]:checked {{
        background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']};
    }}
    QListWidget#sections {{ background: {c['side']}; border: none; padding: 12px 8px; outline: 0; }}
    QListWidget#sections::item {{ padding: 8px 14px; border-radius: 6px; margin: 1px 0; }}
    QListWidget#sections::item:hover {{ background: {c['hover']}; }}
    QListWidget#sections::item:selected {{ background: {c['select']}; color: {c['text']}; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {c['line']}; }}
    QTabBar::tab {{ padding: 9px 16px; border: none; color: {c['muted']}; background: transparent; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; }}
    QScrollArea {{ border: none; background: transparent; }}
    QFrame#restartBar {{ background: {c['side']}; border-top: 1px solid {c['line']}; }}
    QLineEdit#search {{ min-width: 0; padding: 7px 10px; }}
    """


SYSTEM_STYLE = """
QLabel#pageTitle { font-size: 15pt; font-weight: 600; padding: 0 0 6px 0; }
QLabel#sectionTitle { font-size: 13pt; font-weight: 600; padding: 20px 0 0 0; }
QLabel#groupTitle { font-weight: 600; padding: 14px 0 4px 0; }
QLabel#rowHint { color: palette(placeholder-text); }
"""


class Switch(QAbstractButton):
    """Переключатель вместо флажка: состояние видно издалека."""

    def __init__(self, accent: str, off: str) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._accent, self._off = QColor(accent), QColor(off)
        self._t = 0.0
        self._anim = QVariantAnimation(self, duration=140, easingCurve=QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)
        self.toggled.connect(self._animate)

    def set_quiet(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._t = 1.0 if on else 0.0
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def _step(self, value) -> None:
        self._t = float(value)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 — имя из Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        track = QRectF(1, 3, 40, 18)
        color = QColor(
            int(self._off.red() + (self._accent.red() - self._off.red()) * self._t),
            int(self._off.green() + (self._accent.green() - self._off.green()) * self._t),
            int(self._off.blue() + (self._accent.blue() - self._off.blue()) * self._t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(track, 9, 9)
        p.setBrush(QColor("#ffffff"))
        x = 11 + 20 * self._t
        p.drawEllipse(QPointF(x, 12), 6.5, 6.5)


class Segmented(QWidget):
    """Два-четыре варианта рядом: выбор одним щелчком, без раскрытия списка."""

    changed = Signal(object)

    def __init__(self, options) -> None:
        super().__init__()
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        self._group = QButtonGroup(self)
        self._values = [value for value, _ in options]
        for index, (value, label) in enumerate(options):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            place = "only" if len(options) == 1 else "first" if index == 0 else "last" if index == len(options) - 1 else "mid"
            button.setProperty("segment", place)
            self._group.addButton(button, index)
            line.addWidget(button)
        self._group.idClicked.connect(lambda index: self.changed.emit(self._values[index]))

    def set_value(self, value) -> None:
        if value in self._values:
            self._group.button(self._values.index(value)).setChecked(True)


# ---------- окно ----------


class ConceptWindow(QWidget):
    """Одна раскладка в одном виде; пульт пересоздаёт окно при переключении."""

    def __init__(self, layout_kind: str, look: Look, values: dict[str, Any]) -> None:
        super().__init__(None, Qt.Window)
        self.look = look
        self.values = values
        self.launched = dict(values)
        self.sections = content()
        self._setters: dict[str, list[Callable[[Any], None]]] = {}
        self._rows: list[tuple[Row, QFrame, QWidget]] = []
        self._capturing: QPushButton | None = None
        self._capture_path = ""
        self.setFocusPolicy(Qt.StrongFocus)

        titles = {"sidebar": "А · Разделы слева", "page": "Б · Одна страница", "tabs": "В · Вкладки сверху"}
        self.setWindowTitle(f"Настройки VoiceTyper — концепт {titles[layout_kind]}")
        colors = look.colors()
        self.setStyleSheet(own_style(colors) if look.own else SYSTEM_STYLE)

        body = {"sidebar": self._sidebar, "page": self._single_page, "tabs": self._tabs}[layout_kind]()

        self._restart_bar = QFrame()
        self._restart_bar.setObjectName("restartBar")
        bar = QHBoxLayout(self._restart_bar)
        bar.setContentsMargins(20, 10, 20, 10)
        bar.addWidget(QLabel("Часть изменений заработает после перезапуска"), 1)
        bar.addWidget(QPushButton("Перезапустить"))
        self._restart_bar.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(body, 1)
        root.addWidget(self._restart_bar)

        size = {"sidebar": (860, 620), "page": (640, 760), "tabs": (700, 600)}[layout_kind]
        self.resize(*size)
        self._refresh_visibility()

    # ---------- раскладки ----------

    def _sidebar(self) -> QWidget:
        sections = QListWidget()
        sections.setObjectName("sections")
        sections.setFixedWidth(200)
        pages = QStackedWidget()
        for section in self.sections:
            sections.addItem(section.title)
            sections.item(sections.count() - 1).setSizeHint(QSize(180, 36))
            pages.addWidget(self._scroll(self._section_page(section, heading="page")))
        sections.currentRowChanged.connect(pages.setCurrentIndex)
        sections.setCurrentRow(0)
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(0)
        line.addWidget(sections)
        line.addWidget(pages, 1)
        return holder

    def _single_page(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        search = QLineEdit()
        search.setObjectName("search")
        search.setPlaceholderText("Найти настройку: «громкость», «ключ», «F8»…")
        search.setClearButtonEnabled(True)
        top = QHBoxLayout()
        top.setContentsMargins(28, 18, 28, 6)
        top.addWidget(search)
        column.addLayout(top)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(28, 0, 28, 24)
        layout.setSpacing(0)
        self._section_labels: list[tuple[QLabel, Section]] = []
        self._group_labels: list[tuple[QLabel, Group]] = []
        for section in self.sections:
            title = QLabel(section.title)
            title.setObjectName("sectionTitle")
            layout.addWidget(title)
            self._section_labels.append((title, section))
            self._fill_groups(layout, section)
        layout.addStretch(1)
        column.addWidget(self._scroll(content_widget), 1)
        search.textChanged.connect(self._filter)
        return holder

    def _tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        for section in self.sections:
            tabs.addTab(self._scroll(self._section_page(section, heading=None)), section.title)
        return tabs

    def _section_page(self, section: Section, heading: str | None) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(0)
        if heading:
            title = QLabel(section.title)
            title.setObjectName("pageTitle")
            layout.addWidget(title)
        self._fill_groups(layout, section)
        layout.addStretch(1)
        return page

    def _fill_groups(self, layout: QVBoxLayout, section: Section) -> None:
        for group in section.groups:
            label = QLabel(group.title)
            label.setObjectName("groupTitle")
            layout.addWidget(label)
            if hasattr(self, "_group_labels"):
                self._group_labels.append((label, group))
            for row in group.rows:
                frame, control = self._row(row)
                layout.addWidget(frame)
                self._rows.append((row, frame, control))

    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        return scroll

    # ---------- строки ----------

    def _row(self, row: Row) -> tuple[QFrame, QWidget]:
        frame = QFrame()
        frame.setObjectName("row")
        line = QHBoxLayout(frame)
        line.setContentsMargins(0, 9, 0, 9)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(QLabel(row.title))
        if row.hint:
            hint = QLabel(row.hint)
            hint.setObjectName("rowHint")
            hint.setWordWrap(True)
            text.addWidget(hint)
        line.addLayout(text, 1)
        line.addSpacing(16)
        control = self._control(row)
        line.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        return frame, control

    def _control(self, row: Row) -> QWidget:
        c = self.look.colors()
        value = self.values.get(row.path)
        if row.kind == "hotkey":
            button = QPushButton(pretty_combo(value))
            button.setObjectName("hotkey")
            button.setFocusPolicy(Qt.NoFocus)
            button.setMinimumWidth(150)
            button.clicked.connect(lambda _c=False, b=button, p=row.path: self._start_capture(b, p))
            self._on_value(row.path, lambda v, b=button: b.setText(pretty_combo(v)))
            return button
        if row.kind == "choice":
            # Рядом встают только короткие наборы: четыре «Справа снизу» вышли
            # бы шире строки, а выбор из шести — уже список.
            width = sum(len(label) for _, label in row.options)
            fits = (len(row.options) <= 3 and width <= 30) or (len(row.options) == 4 and width <= 26)
            if self.look.own and fits:
                segmented = Segmented(row.options)
                segmented.set_value(value)
                segmented.changed.connect(lambda v, p=row.path: self._apply(p, v))
                self._on_value(row.path, segmented.set_value)
                return segmented
            combo = QComboBox()
            combo.setMinimumWidth(230)
            for option, label in row.options:
                combo.addItem(label, option)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.currentIndexChanged.connect(lambda _i, cb=combo, p=row.path: self._apply(p, cb.currentData()))
            self._on_value(row.path, lambda v, cb=combo: _quiet(cb, cb.setCurrentIndex, cb.findData(v)))
            return combo
        if row.kind == "mic":
            combo = QComboBox()
            combo.setMinimumWidth(230)
            for index, name in microphones():
                combo.addItem(name, index)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.currentIndexChanged.connect(lambda _i, cb=combo, p=row.path: self._apply(p, cb.currentData()))
            return combo
        if row.kind == "toggle":
            if self.look.own:
                switch = Switch(c["accent"], c["line"])
                switch.set_quiet(bool(value))
                switch.toggled.connect(lambda on, p=row.path: self._apply(p, on))
                return switch
            box = QCheckBox()
            box.setChecked(bool(value))
            box.toggled.connect(lambda on, p=row.path: self._apply(p, on))
            return box
        if row.kind in ("text", "secret"):
            edit = QLineEdit(str(value or ""))
            edit.setMinimumWidth(230)
            if row.kind == "secret":
                edit.setEchoMode(QLineEdit.Password)
                edit.setPlaceholderText("не задан")
                eye = QAction(eye_icon(c["muted"]), "показать", edit)
                eye.setCheckable(True)
                eye.toggled.connect(lambda on, e=edit: e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
                edit.addAction(eye, QLineEdit.TrailingPosition)
            edit.editingFinished.connect(lambda e=edit, p=row.path: self._apply(p, e.text().strip()))
            self._on_value(row.path, lambda v, e=edit: _quiet(e, e.setText, str(v or "")))
            return edit
        if row.kind == "slider":
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, 100)
            slider.setFixedWidth(230)
            slider.setValue(round(float(value) * 100))
            slider.valueChanged.connect(lambda v, p=row.path: self._apply(p, round(v / 100, 2)))
            return slider
        if row.kind == "button":
            button = QPushButton(row.path)
            button.setToolTip("в концепте ничего не открывает")
            return button
        label = QLabel(str(value))
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _on_value(self, path: str, setter: Callable[[Any], None]) -> None:
        self._setters.setdefault(path, []).append(setter)

    # ---------- изменения ----------

    def _apply(self, path: str, value: Any) -> None:
        if self.values.get(path) == value:
            return
        self.values[path] = value
        if path == "_ask_server" and ASK_SERVERS[value] is not None:
            model, effort = ASK_SERVERS[value]
            for key, new in (("ask.model", model), ("ask.reasoning_effort", effort),
                             ("ask.url", "https://api.giga.chat/v1" if value == "giga" else "")):
                self.values[key] = new
                for setter in self._setters.get(key, []):
                    setter(new)
        print(f"[concepts] {path} = {value!r}" if "key" not in path else f"[concepts] {path} изменён")
        self._refresh_visibility()
        pending = any(self.values.get(key) != self.launched.get(key) for key in RESTART)
        self._restart_bar.setVisible(pending)

    def _refresh_visibility(self) -> None:
        for row, frame, _control in self._rows:
            if row.visible is not None:
                frame.setVisible(row.visible(self.values))

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row, frame, control in self._rows:
            haystack = f"{row.title} {row.hint}".lower()
            if row.kind == "hotkey":
                haystack += " " + pretty_combo(self.values.get(row.path, "")).lower()
            shown = (not needle or needle in haystack) and (row.visible is None or row.visible(self.values))
            frame.setVisible(shown)
        for label, group in self._group_labels:
            label.setVisible(any(frame.isVisibleTo(self) for row, frame, _ in self._rows if row in group.rows))
        for label, section in self._section_labels:
            label.setVisible(any(
                frame.isVisibleTo(self) for row, frame, _ in self._rows
                if any(row in group.rows for group in section.groups)
            ))

    # ---------- запись сочетания ----------

    def _start_capture(self, button: QPushButton, path: str) -> None:
        self._stop_capture()
        self._capturing, self._capture_path = button, path
        button.setText("Нажми сочетание…")
        button.setProperty("waiting", True)
        button.style().unpolish(button)
        button.style().polish(button)
        self.setFocus()

    def _stop_capture(self) -> None:
        if self._capturing is not None:
            button, self._capturing = self._capturing, None
            button.setProperty("waiting", False)
            button.style().unpolish(button)
            button.style().polish(button)
            button.setText(pretty_combo(self.values[self._capture_path]))

    def keyPressEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        if self._capturing is None:
            super().keyPressEvent(event)
            return
        event.accept()
        key = event.key()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
        path = self._capture_path
        if key == Qt.Key_Escape and path != "hotkeys.cancel":
            self._stop_capture()
            return
        mods = event.modifiers()
        parts = [name for flag, name in ((Qt.ControlModifier, "ctrl"), (Qt.ShiftModifier, "shift"),
                                         (Qt.AltModifier, "alt"), (Qt.MetaModifier, "windows")) if mods & flag]
        parts.append(QKeySequence(key).toString().lower())
        combo = "+".join(parts)
        self._stop_capture()
        self._apply(path, combo)
        for setter in self._setters.get(path, []):
            setter(combo)


def eye_icon(color: str) -> QIcon:
    """Глаз у поля ключа: без значка кнопку «показать» не видно."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 2.4))
    p.drawEllipse(QRectF(4, 9, 24, 14))
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(16, 16), 3.6, 3.6)
    p.end()
    return QIcon(pixmap)


def _quiet(widget: QWidget, setter: Callable[[Any], None], value: Any) -> None:
    widget.blockSignals(True)
    setter(value)
    widget.blockSignals(False)


# ---------- пульт ----------


class Panel(QWidget):
    """Пульт концептов: раскладка, вид и выход — по просьбе: кнопка, а не Ctrl+C."""

    def __init__(self, app: QApplication) -> None:
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.app = app
        self.setWindowTitle("Концепты настроек")
        self._system_style = app.style().name()
        self._system_palette = app.palette()
        self._dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self.layout_kind = "sidebar"
        self.own = True
        self.window: ConceptWindow | None = None
        self.values = initial_values()

        column = QVBoxLayout(self)
        column.addWidget(QLabel("Раскладка"))
        layouts = QButtonGroup(self)
        for key, label in (("sidebar", "А · Разделы слева"), ("page", "Б · Одна страница"), ("tabs", "В · Вкладки сверху")):
            radio = QRadioButton(label)
            radio.setChecked(key == self.layout_kind)
            radio.toggled.connect(lambda on, k=key: on and self._switch(layout_kind=k))
            layouts.addButton(radio)
            column.addWidget(radio)
        column.addSpacing(8)
        column.addWidget(QLabel("Вид"))
        looks = QButtonGroup(self)
        for own, label in ((False, "Системный Windows"), (True, "Свой: переключатели и сегменты")):
            radio = QRadioButton(label)
            radio.setChecked(own == self.own)
            radio.toggled.connect(lambda on, o=own: on and self._switch(own=o))
            looks.addButton(radio)
            column.addWidget(radio)
        column.addSpacing(10)
        stop = QPushButton("Остановить демо")
        stop.setMinimumHeight(32)
        stop.clicked.connect(app.quit)
        column.addWidget(stop)

        screen = app.primaryScreen().availableGeometry()
        self.move(screen.left() + 24, screen.top() + 24)
        self.show()
        self._switch()

    def _switch(self, layout_kind: str | None = None, own: bool | None = None) -> None:
        if layout_kind is not None:
            self.layout_kind = layout_kind
        if own is not None:
            self.own = own
        look = Look(own=self.own, dark=self._dark)
        if self.own:
            self.app.setStyle("Fusion")
            self.app.setPalette(own_palette(look.colors()))
        else:
            self.app.setStyle(self._system_style)
            self.app.setPalette(self._system_palette)
        geometry = self.window.geometry() if self.window is not None else None
        if self.window is not None:
            self.window.close()
            self.window.deleteLater()
        self.window = ConceptWindow(self.layout_kind, look, self.values)
        if geometry is not None:
            self.window.move(geometry.topLeft())
        else:
            screen = self.app.primaryScreen().availableGeometry()
            self.window.move(screen.center() - self.window.rect().center())
        self.window.show()
        self.window.raise_()

    def closeEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        event.accept()
        self.app.quit()


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    panel = Panel(app)  # noqa: F841 — держит окна живыми
    if "--shots" in sys.argv:
        _shots(panel, Path(sys.argv[sys.argv.index("--shots") + 1]))
        return 0
    return app.exec()


def _shots(panel: Panel, folder: Path) -> None:
    """Снимки окон для проверки вёрстки — не замена живому прогону."""
    folder.mkdir(parents=True, exist_ok=True)
    for own in (False, True):
        for kind in ("sidebar", "page", "tabs"):
            panel._switch(layout_kind=kind, own=own)
            QApplication.processEvents()
            panel.window.grab().save(str(folder / f"{kind}-{'own' if own else 'system'}.png"))
            if kind == "sidebar":
                panel.window.findChild(QListWidget, "sections").setCurrentRow(1)
                QApplication.processEvents()
                panel.window.grab().save(str(folder / f"darvi-{'own' if own else 'system'}.png"))


if __name__ == "__main__":
    sys.exit(main())
