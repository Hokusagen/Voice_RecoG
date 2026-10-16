"""Окно настроек: то, что человек меняет, — без правки config.json руками.

Меню трея в Windows закрывается от любого промаха мимо подменю, и выбирать в
нём неудобно, поэтому всё, что там было, кроме паузы и истории, живёт здесь.
Раскладку и вид выбрали 17.10.2026 из концептов `design/settings`: вкладки
сверху и свой вид — переключатели вместо флажков, а два-четыре коротких
варианта стоят рядом сегментами и выбираются одним щелчком. Тёмное окно или
светлое — как в системе. Промпты, тайм-ауты и прочая техника остаются в
config.json — на него ссылка на вкладке «Система».

Изменение применяется сразу, без кнопки «Сохранить»: окно пишет значение в
общий Config и шлёт changed с путём поля, а контроллер делает остальное —
переподписывает клавиши, меняет громкость, сохраняет файл. Часть полей
читается только при запуске (ключи, серверы и модели облака); если такое
поле отличается от того, с чем приложение поднялось, внизу окна появляется
«Перезапустить».

Вид держится стилями самого окна, а не стилем приложения: Fusion на всё
приложение перекрасил бы и меню трея.
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config import Config, build_version

#: Поля, которые читаются только при запуске: для них нужен перезапуск.
RESTART_FIELDS = (
    "cloud.url", "cloud.api_key", "cloud.model", "cloud.reserve.api_key",
    "ask.url", "ask.api_key", "ask.model", "ask.reasoning_effort",
    "ask.search_key", "ask.search_depth", "audio.keep_dictations",
)

#: Серверы вопросов на выбор: адрес, модель и раздумья, с которыми он отвечает.
#: GigaChat — без раздумий: с ними 3-Ultra изводит весь потолок и молчит.
GIGACHAT_URL = "https://api.giga.chat/v1"
ASK_SERVERS = {
    "groq": ("", "openai/gpt-oss-120b", "medium"),
    "giga": (GIGACHAT_URL, "GigaChat-3-Ultra", ""),
}

_NAMES = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "windows": "Win", "cmd": "Cmd", "esc": "Esc"}


def pretty_combo(combo: str) -> str:
    """«ctrl+shift+f8» → «Ctrl + Shift + F8»: так сочетания пишут в Windows."""
    parts = [part.strip() for part in combo.split("+") if part.strip()]
    return " + ".join(_NAMES.get(part, part.upper() if len(part) <= 3 else part.capitalize()) for part in parts)


def _get(cfg: Config, path: str) -> Any:
    target: Any = cfg
    for part in path.split("."):
        target = getattr(target, part)
    return target


def _set(cfg: Config, path: str, value: Any) -> None:
    *head, last = path.split(".")
    target: Any = cfg
    for part in head:
        target = getattr(target, part)
    setattr(target, last, value)


def snapshot(cfg: Config) -> dict[str, Any]:
    """Значения полей, которым нужен перезапуск, — на момент запуска."""
    return {path: _get(cfg, path) for path in RESTART_FIELDS}


# ---------- содержание ----------


@dataclass
class Row:
    kind: str
    """hotkey | choice | toggle | autostart | text | secret | server | mic | volume | button | info"""

    title: str
    hint: str = ""
    path: str = ""
    options: tuple = ()
    visible: Callable[["SettingsWindow"], bool] | None = None


def _content(cfg: Config) -> list[tuple[str, list[tuple[str, list[Row]]]]]:
    """Вкладки → группы → строки. Подписи сверены с живым прогоном концептов."""
    corners = (
        ("bottom-right", "Справа снизу"), ("bottom-left", "Слева снизу"),
        ("top-right", "Справа сверху"), ("top-left", "Слева сверху"),
    )
    system = "Windows" if sys.platform == "win32" else "системой"
    return [
        ("Диктовка", [
            ("Клавиши", [
                Row("hotkey", "Диктовка", "зажал, сказал, отпустил", "record"),
                Row("hotkey", "Другой стиль правки", "та же диктовка, правка другого стиля", "record_alt"),
                Row("hotkey", "Без правки", "ровно то, что расслышал Whisper", "record_raw"),
                Row("hotkey", "Запомнить правку", "выдели исправленный текст и нажми", "correct"),
                Row("hotkey", "Спросить Дарви", "ответ — в карточку, в текст не вставляется", "ask"),
                Row("hotkey", "Отмена", "сбросить запись, пока говоришь", "cancel"),
                Row("choice", "Режим клавиши", "", "hotkeys.mode",
                    (("hold", "Удерживать"), ("toggle", "Нажать — нажать"))),
            ]),
            ("Правка", [
                Row("choice", "Стиль по основной клавише", "другой — по своей клавише", "llm.style",
                    (("careful", "Бережная"), ("dry", "Сухая"))),
                Row("choice", "Где править", "облако — по ключу на вкладке «Облако»", "llm.backend",
                    (("local", "Ollama"), ("cloud", "Облако"))),
            ]),
            ("Микрофон", [
                Row("mic", "Микрофон", "со следующей записи", "audio.device"),
                Row("toggle", "Хранить звук диктовок",
                    f"для замеров распознавания, до {cfg.audio.keep_dictations_mb:.0f} МБ", "audio.keep_dictations"),
            ]),
        ]),
        ("Дарви", [
            ("Как спрашивать", [
                Row("toggle", "Обращение по имени", "«Дарви, …» в начале диктовки — вопрос", "ask.by_name"),
                Row("toggle", "Искать перед каждым ответом",
                    "без этого — по кнопке в карточке или просьбой «найди в интернете»", "ask.web_search"),
                Row("text", "О себе", "система и версии: ответы про код будут для них", "ask.about"),
            ]),
            ("Кто отвечает", [
                Row("server", "Сервер", ""),
                Row("text", "Адрес сервера", "OpenAI-совместимый, …/v1", "ask.url",
                    visible=lambda w: w.server == "custom"),
                Row("secret", "Ключ сервера", "у GigaChat — ключ авторизации из личного кабинета", "ask.api_key",
                    visible=lambda w: w.server != "groq"),
                Row("text", "Модель", "", "ask.model"),
                Row("choice", "Раздумья", "GigaChat с раздумьями молчит", "ask.reasoning_effort",
                    (("", "Без"), ("low", "Немного"), ("medium", "Средне"), ("high", "Долго"))),
            ]),
            ("Поиск", [
                Row("secret", "Ключ Tavily", "без него ищет встроенный поиск Groq", "ask.search_key"),
                Row("choice", "Глубина", "глубоко — вдвое дороже", "ask.search_depth",
                    (("fast", "Быстро"), ("basic", "Обычно"), ("advanced", "Глубоко"))),
            ]),
        ]),
        ("Плашка и звук", [
            ("Плашка", [
                Row("toggle", "Показывать плашку", "", "ui.hud_enabled"),
                Row("choice", "Где", "", "ui.hud_position",
                    (("bottom", "Снизу по центру"), ("top", "Сверху по центру")) + corners),
                Row("choice", "Появление", "", "ui.hud_appear",
                    (("drop", "Капля"), ("drop-single", "Одним движением"))),
                Row("toggle", "На мониторе с курсором", "", "ui.hud_follow_cursor"),
                Row("choice", "Угол карточки Дарви", "", "ui.card_corner", corners),
            ]),
            ("Звук", [
                Row("toggle", "Звуки", "начало и конец записи, готово, ошибка", "ui.sounds"),
                Row("volume", "Громкость", "", "ui.volume"),
            ]),
        ]),
        ("Облако", [
            ("Основное", [
                Row("secret", "Ключ Groq", "распознавание и правка в облаке", "cloud.api_key"),
                Row("text", "Адрес", "например, через Cloudflare AI Gateway", "cloud.url"),
                Row("text", "Модель правки", "", "cloud.model"),
            ]),
            ("Запасное", [
                Row("secret", "Ключ OpenRouter", "если основное молчит; тариф там платный", "cloud.reserve.api_key"),
            ]),
        ]),
        ("Система", [
            ("Запуск", [
                Row("autostart", f"Запускать с {system}", "", "ui.autostart"),
                Row("toggle", "Отдать видеокарту",
                    "Whisper на процессоре или в облаке, редактор выгружен", "release_gpu"),
            ]),
            ("Файлы", [
                Row("button", "Журнал диктовок", "что распознано, как поправлено, вопросы Дарви", "journal"),
                Row("button", "Остальное", "промпты, тайм-ауты, лимиты — руками в файле", "config"),
                Row("info", "Версия", "сверять с журналом, когда что-то сломалось"),
            ]),
        ]),
    ]


# ---------- вид ----------

_DARK = dict(
    window="#202020", side="#1a1a1a", field="#2c2c2c", line="#3a3a3a", text="#ececec",
    muted="#9b9b9b", accent="#79b0ff", on_accent="#0b1a2e", select="#353535", warning="#ff8a8a",
)
_LIGHT = dict(
    window="#f7f7f7", side="#ededed", field="#ffffff", line="#d4d4d4", text="#1b1b1b",
    muted="#6b6b6b", accent="#2a66d0", on_accent="#ffffff", select="#e4e4e4", warning="#b3261e",
)


def _is_dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def _palette(c: dict[str, str]) -> QPalette:
    palette = QPalette()
    for role, key in (
        (QPalette.Window, "window"), (QPalette.WindowText, "text"), (QPalette.Base, "field"),
        (QPalette.AlternateBase, "side"), (QPalette.Text, "text"), (QPalette.Button, "field"),
        (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent"), (QPalette.HighlightedText, "on_accent"),
        (QPalette.PlaceholderText, "muted"), (QPalette.ToolTipBase, "field"), (QPalette.ToolTipText, "text"),
        (QPalette.Mid, "line"), (QPalette.Midlight, "line"), (QPalette.Light, "field"), (QPalette.Dark, "side"),
    ):
        palette.setColor(role, QColor(c[key]))
    return palette


def _chevron(color: str) -> str:
    """Стрелка выпадающего списка файлом: стилю окна нужна картинка по адресу.

    Без своей стрелки её рисует системный стиль Windows — тёмным по тёмному.
    """
    folder = Path(tempfile.gettempdir()) / "voicetyper"
    name = f"chevron-{color.lstrip('#')}"
    for scale, suffix in ((1, ""), (2, "@2x")):
        path = folder / f"{name}{suffix}.png"
        if path.exists():
            continue
        folder.mkdir(parents=True, exist_ok=True)
        pixmap = QPixmap(10 * scale, 6 * scale)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), 1.5 * scale)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawPolyline([QPointF(1 * scale, 1 * scale), QPointF(5 * scale, 5 * scale), QPointF(9 * scale, 1 * scale)])
        p.end()
        pixmap.save(str(path))
    return (folder / f"{name}.png").as_posix()


def _eye(color: str) -> QIcon:
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


def _style(c: dict[str, str]) -> str:
    return f"""
    QWidget#settings, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {c['window']}; }}
    QLabel {{ color: {c['text']}; background: transparent; }}
    QLabel#groupTitle {{ font-size: 9pt; font-weight: 600; color: {c['muted']}; padding: 16px 0 4px 0; }}
    QLabel#rowHint {{ color: {c['muted']}; font-size: 9pt; }}
    QLabel#warning {{ color: {c['warning']}; font-size: 9pt; padding: 6px 0 0 0; }}
    QLineEdit, QComboBox {{
        background: {c['field']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px;
        padding: 5px 8px; min-width: 230px; selection-background-color: {c['accent']};
        selection-color: {c['on_accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border-color: {c['accent']}; }}
    QComboBox {{ combobox-popup: 0; padding-right: 26px; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url("{_chevron(c['muted'])}"); width: 10px; height: 6px; }}
    QComboBox QAbstractItemView {{
        background: {c['field']}; color: {c['text']}; border: 1px solid {c['line']}; outline: 0;
        padding: 4px; selection-background-color: {c['select']}; selection-color: {c['text']};
    }}
    QPushButton {{
        background: {c['field']}; color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px;
        padding: 5px 14px;
    }}
    QPushButton:hover {{ border-color: {c['accent']}; }}
    QPushButton#hotkey {{ font-weight: 600; min-width: 150px; }}
    QPushButton#hotkey[waiting="true"] {{ border-color: {c['accent']}; color: {c['accent']}; }}
    QPushButton[segment] {{ border-radius: 0; padding: 5px 12px; margin: 0; }}
    QPushButton[segment="first"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    QPushButton[segment="last"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    QPushButton[segment]:checked {{ background: {c['accent']}; color: {c['on_accent']}; border-color: {c['accent']}; }}
    QTabWidget::pane {{ border: none; border-top: 1px solid {c['line']}; }}
    QTabBar {{ background: {c['window']}; }}
    QTabBar::tab {{ padding: 9px 16px; border: none; color: {c['muted']}; background: transparent; }}
    QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
    QTabBar::tab:hover {{ color: {c['text']}; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 3px; min-height: 32px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    QSlider::groove:horizontal {{ height: 4px; background: {c['line']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: #ffffff; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}
    QToolTip {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['line']}; padding: 4px 6px; }}
    QFrame#restartBar {{ background: {c['side']}; border-top: 1px solid {c['line']}; }}
    """


class Switch(QAbstractButton):
    """Переключатель вместо флажка: состояние видно издалека."""

    def __init__(self, colors: dict[str, str]) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(42, 24)
        self._colors = colors
        """Общий словарь цветов окна: смена темы перекрашивает и переключатель."""

        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._step)
        self.toggled.connect(self._animate)

    def set_quiet(self, on: bool) -> None:
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._anim.stop()
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
        off, on = QColor(self._colors["line"]), QColor(self._colors["accent"])
        t = self._t
        color = QColor(
            round(off.red() + (on.red() - off.red()) * t),
            round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t),
        )
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(QRectF(1, 3, 40, 18), 9, 9)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(11 + 20 * t, 12), 6.5, 6.5)


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
        for index, (_value, label) in enumerate(options):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            place = "first" if index == 0 else "last" if index == len(options) - 1 else "mid"
            button.setProperty("segment", place)
            self._group.addButton(button, index)
            line.addWidget(button)
        # idClicked — только щелчок человека: значение из настроек его не шлёт.
        self._group.idClicked.connect(lambda index: self.changed.emit(self._values[index]))

    def set_value(self, value) -> None:
        if value in self._values:
            self._group.button(self._values.index(value)).setChecked(True)


def _fits_segments(options) -> bool:
    """Рядом встают только короткие наборы: шесть мест плашки — уже список."""
    width = sum(len(label) for _, label in options)
    return (len(options) <= 3 and width <= 30) or (len(options) == 4 and width <= 26)


# ---------- окно ----------


class SettingsWindow(QWidget):
    changed = Signal(str)
    """Поле поменялось, его значение уже в Config: путь вида «llm.style»."""

    restart_requested = Signal()
    journal_requested = Signal()
    config_requested = Signal()

    def __init__(
        self,
        cfg: Config,
        hotkeys,
        launched: dict[str, Any],
        autostart_enabled: Callable[[], bool],
        microphones: Callable[[], list[tuple[int | None, str]]],
        icon: QIcon | None = None,
    ) -> None:
        super().__init__(None, Qt.Window)
        self.cfg = cfg
        self._hotkeys = hotkeys
        self._launched = launched
        self._autostart_enabled = autostart_enabled
        self._microphones = microphones
        self._colors: dict[str, str] = dict(_DARK if _is_dark() else _LIGHT)
        self._refreshers: list[Callable[[], None]] = []
        self._rows: list[tuple[Row, QFrame]] = []
        self._edits: list[tuple[QLineEdit, str]] = []
        self._eyes: list[QAction] = []
        self._hotkey_buttons: list[QPushButton] = []
        self._capturing: QPushButton | None = None
        self.server = self._server_of(cfg.ask.url)
        """Кто отвечает Дарви: groq | giga | custom. Своё состояние, а не вывод из
        адреса: выбрав «Свой», человек ещё не вписал адрес, а строка должна
        уже появиться."""

        self.setObjectName("settings")
        self.setWindowTitle("Настройки VoiceTyper")
        if icon is not None:
            self.setWindowIcon(icon)
        self.resize(700, 620)
        self.setMinimumSize(600, 460)
        # Пока пишется сочетание, фокус держит само окно: иначе пробел или
        # Enter нажали бы кнопку, на которой стоял фокус.
        self.setFocusPolicy(Qt.StrongFocus)

        hotkeys.captured.connect(self._on_captured)

        # Громкость пересобирает звуковые файлы на диске, поэтому колесо и
        # стрелки применяют её после паузы, а не на каждом шаге.
        self._volume_timer = QTimer(self)
        self._volume_timer.setSingleShot(True)
        self._volume_timer.setInterval(300)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        for title, groups in _content(cfg):
            tabs.addTab(self._page(groups), title)

        self._restart_bar = QFrame()
        self._restart_bar.setObjectName("restartBar")
        bar = QHBoxLayout(self._restart_bar)
        bar.setContentsMargins(20, 10, 20, 10)
        bar.addWidget(QLabel("Часть изменений заработает после перезапуска"), 1)
        restart = QPushButton("Перезапустить")
        restart.clicked.connect(self.restart_requested)
        bar.addWidget(restart)
        self._restart_bar.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(tabs, 1)
        root.addWidget(self._restart_bar)

        self._apply_look()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _scheme: self._apply_look())

    # ---------- показ ----------

    def open(self) -> None:
        self.server = self._server_of(self.cfg.ask.url)
        for refresh in self._refreshers:
            refresh()
        self._update_rows()
        self._update_restart_bar()
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        if self._capturing is not None:
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        self._stop_capture()
        # Поле, из которого не ушли, тоже считается: закрыл окно — значит, всё.
        for edit, path in self._edits:
            self._apply(path, edit.text().strip())
        super().hideEvent(event)

    def _apply_look(self) -> None:
        self._colors.clear()
        self._colors.update(_DARK if _is_dark() else _LIGHT)
        self.setPalette(_palette(self._colors))
        self.setStyleSheet(_style(self._colors))
        icon = _eye(self._colors["muted"])
        for eye in self._eyes:
            eye.setIcon(icon)
        for switch in self.findChildren(Switch):
            switch.update()

    # ---------- страницы и строки ----------

    def _page(self, groups) -> QScrollArea:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 12, 28, 24)
        layout.setSpacing(0)
        for title, rows in groups:
            label = QLabel(title)
            label.setObjectName("groupTitle")
            layout.addWidget(label)
            for row in rows:
                frame = self._row(row)
                layout.addWidget(frame)
                self._rows.append((row, frame))
            if title == "Клавиши":
                self._hotkey_warning = QLabel()
                self._hotkey_warning.setObjectName("warning")
                self._hotkey_warning.hide()
                layout.addWidget(self._hotkey_warning)
        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(page)
        return scroll

    def _row(self, row: Row) -> QFrame:
        frame = QFrame()
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
        line.addWidget(self._control(row), 0, Qt.AlignRight | Qt.AlignVCenter)
        return frame

    def _control(self, row: Row) -> QWidget:
        builder = getattr(self, f"_{row.kind}")
        return builder(row)

    def _hotkey(self, row: Row) -> QWidget:
        button = QPushButton()
        button.setObjectName("hotkey")
        button.setProperty("action", row.path)
        button.setFocusPolicy(Qt.NoFocus)
        button.setToolTip("Щёлкни и нажми новое сочетание; Esc — оставить как было")
        button.clicked.connect(lambda _c=False, b=button: self._start_capture(b))
        self._hotkey_buttons.append(button)
        self._refreshers.append(lambda: self._show_combo(button))
        return button

    def _choice(self, row: Row) -> QWidget:
        if _fits_segments(row.options):
            segmented = Segmented(row.options)
            segmented.changed.connect(lambda value: self._apply(row.path, value))
            self._refreshers.append(lambda: segmented.set_value(_get(self.cfg, row.path)))
            return segmented
        combo = QComboBox()
        for value, label in row.options:
            combo.addItem(label, value)

        def refresh() -> None:
            value = _get(self.cfg, row.path)
            if combo.findData(value) < 0:
                combo.addItem(str(value) or "—", value)
            _quiet(combo, combo.setCurrentIndex, combo.findData(value))

        combo.currentIndexChanged.connect(lambda _i: self._apply(row.path, combo.currentData()))
        self._refreshers.append(refresh)
        return combo

    def _server(self, row: Row) -> QWidget:
        segmented = Segmented((("groq", "Groq"), ("giga", "GigaChat"), ("custom", "Свой")))
        segmented.changed.connect(self._on_server)
        self._refreshers.append(lambda: segmented.set_value(self.server))
        return segmented

    def _mic(self, row: Row) -> QWidget:
        combo = QComboBox()

        def refresh() -> None:
            combo.blockSignals(True)
            combo.clear()
            devices = self._microphones()
            current = self.cfg.audio.device
            if current is not None and all(index != current for index, _ in devices):
                devices.append((current, f"Устройство {current} — не найдено"))
            for index, name in devices:
                combo.addItem(name, index)
            combo.setCurrentIndex(max(0, combo.findData(current)))
            combo.blockSignals(False)

        combo.currentIndexChanged.connect(lambda _i: self._apply(row.path, combo.currentData()))
        self._refreshers.append(refresh)
        return combo

    def _toggle(self, row: Row) -> QWidget:
        switch = Switch(self._colors)
        switch.toggled.connect(lambda on: self._apply(row.path, on))
        self._refreshers.append(lambda: switch.set_quiet(bool(_get(self.cfg, row.path))))
        return switch

    def _autostart(self, row: Row) -> QWidget:
        # Правда — в реестре, а не в config.json: туда смотрит Windows.
        switch = Switch(self._colors)
        switch.toggled.connect(lambda on: self._apply(row.path, on, force=True))
        self._refreshers.append(lambda: switch.set_quiet(self._autostart_enabled()))
        return switch

    def _text(self, row: Row) -> QWidget:
        edit = QLineEdit()
        edit.editingFinished.connect(lambda: self._apply(row.path, edit.text().strip()))

        def refresh() -> None:
            _quiet(edit, edit.setText, str(_get(self.cfg, row.path)))
            # Длинная строка читается с начала, а не с хвоста, где встал курсор.
            edit.setCursorPosition(0)

        self._refreshers.append(refresh)
        self._edits.append((edit, row.path))
        return edit

    def _secret(self, row: Row) -> QWidget:
        # Ключ не показываем, пока не попросят: окно бывает и на показе экрана.
        edit = self._text(row)
        edit.setEchoMode(QLineEdit.Password)
        edit.setPlaceholderText("не задан")
        eye = QAction(_eye(self._colors["muted"]), "Показать", edit)
        eye.setCheckable(True)
        eye.toggled.connect(lambda on: edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        edit.addAction(eye, QLineEdit.TrailingPosition)
        self._eyes.append(eye)
        return edit

    def _volume(self, row: Row) -> QWidget:
        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 100)
        slider.setFixedWidth(230)

        def commit() -> None:
            self._apply(row.path, round(slider.value() / 100, 2))

        def on_value(_value: int) -> None:
            if not slider.isSliderDown():
                self._volume_timer.start()

        self._volume_timer.timeout.connect(commit)
        slider.sliderReleased.connect(commit)
        slider.valueChanged.connect(on_value)
        self._refreshers.append(lambda: _quiet(slider, slider.setValue, round(self.cfg.ui.volume * 100)))
        return slider

    def _button(self, row: Row) -> QWidget:
        if row.path == "journal":
            button = QPushButton("Открыть журнал")
            button.clicked.connect(self.journal_requested)
        else:
            button = QPushButton("Открыть config.json")
            button.clicked.connect(self.config_requested)
        return button

    def _info(self, row: Row) -> QWidget:
        label = QLabel(build_version())
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    # ---------- применение ----------

    def _apply(self, path: str, value: Any, force: bool = False) -> None:
        if _get(self.cfg, path) == value and not force:
            return
        _set(self.cfg, path, value)
        self.changed.emit(path)
        self._update_restart_bar()

    def _on_server(self, server: str) -> None:
        self.server = server
        if server in ASK_SERVERS:
            url, model, effort = ASK_SERVERS[server]
            self._apply("ask.url", url)
            self._apply("ask.model", model)
            self._apply("ask.reasoning_effort", effort)
            for refresh in self._refreshers:
                refresh()
        self._update_rows()

    @staticmethod
    def _server_of(url: str) -> str:
        for server, (known, _model, _effort) in ASK_SERVERS.items():
            if url.strip() == known:
                return server
        return "custom"

    def _update_rows(self) -> None:
        for row, frame in self._rows:
            if row.visible is not None:
                frame.setVisible(row.visible(self))

    def _update_restart_bar(self) -> None:
        pending = any(_get(self.cfg, path) != value for path, value in self._launched.items())
        self._restart_bar.setVisible(pending)

    # ---------- запись сочетания ----------

    def _show_combo(self, button: QPushButton) -> None:
        button.setText(pretty_combo(getattr(self.cfg.hotkeys, button.property("action"))) or "—")

    def _start_capture(self, button: QPushButton) -> None:
        if self._capturing is button:
            self._stop_capture()
            return
        self._stop_capture()
        self._capturing = button
        self._hotkey_warning.hide()
        _set_waiting(button, True)
        button.setText("Нажми сочетание…")
        self.setFocus()
        self._hotkeys.capture(allow_esc=button.property("action") == "cancel")

    def _stop_capture(self) -> None:
        if self._capturing is not None:
            button, self._capturing = self._capturing, None
            self._hotkeys.stop_capture()
            _set_waiting(button, False)
            self._show_combo(button)

    def _on_captured(self, combo: str) -> None:
        button, self._capturing = self._capturing, None
        if button is None:
            return
        _set_waiting(button, False)
        action = button.property("action")
        if combo:
            taken = [
                other.property("action") for other in self._hotkey_buttons
                if other is not button and getattr(self.cfg.hotkeys, other.property("action")) == combo
            ]
            if taken:
                title = next(row.title for row, _ in self._rows if row.kind == "hotkey" and row.path == taken[0])
                self._hotkey_warning.setText(f"{pretty_combo(combo)} уже занято: «{title}»")
                self._hotkey_warning.show()
            else:
                self._apply(f"hotkeys.{action}", combo)
        self._show_combo(button)


def _set_waiting(button: QPushButton, waiting: bool) -> None:
    button.setProperty("waiting", waiting)
    button.style().unpolish(button)
    button.style().polish(button)


def _quiet(widget: QWidget, setter: Callable[[Any], None], value: Any) -> None:
    """Показать значение из настроек, не приняв его за правку человека."""
    widget.blockSignals(True)
    setter(value)
    widget.blockSignals(False)
