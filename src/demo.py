"""Демо-режим: прогоняет HUD по состояниям, не трогая микрофон и модели.

    venv\\Scripts\\python.exe src\\demo.py            все состояния, шрифт из конфига
    venv\\Scripts\\python.exe src\\demo.py fonts      короткий цикл, шрифты по очереди
    venv\\Scripts\\python.exe src\\demo.py Onest      все состояния заданным шрифтом
    venv\\Scripts\\python.exe src\\demo.py voice      «Слушаю» без конца, голос с микрофона
    venv\\Scripts\\python.exe src\\demo.py card       вопрос Дарви, уточнение и карточка ответа

Выход — кнопка «Остановить демо» слева вверху или Ctrl+C в терминале.

Нужен, чтобы смотреть на оформление живьём: стекло, кромку и переходы можно
оценить только в движении, по скриншотам они врут.
"""

from __future__ import annotations

import math
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from config import Config
from core.state import Stage, Status
from ui import theme
from ui import hud as hud_module

#: Сценарий: состояние и сколько миллисекунд его показывать.
SCRIPT = [
    (Status(Stage.LOADING, "Загружаю модель", "large-v3-turbo, cuda / int8_float16"), 2600),
    (Status(Stage.LOADING, "Прогреваю редактор", "qwen2.5:3b"), 1800),
    (Status(Stage.LISTENING, "Слушаю", "отпустите клавишу, когда закончите"), 4200),
    (Status(Stage.TRANSCRIBING, "Распознаю", "4.2 с записи"), 2400),
    (Status(Stage.POLISHING, "Причёсываю", "qwen2.5:3b"), 2000),
    (
        Status(
            Stage.DONE,
            "Готово за 2.1 с",
            "Слушай, там в Компас-3D надо переделать спецификацию по ЕСКД.",
            inserted=True,
        ),
        2600,
    ),
    (Status(Stage.DONE, "Запомнил правку", "блютуз → Bluetooth · и ещё 2"), 2400),
    (
        Status(
            Stage.WARNING,
            "Правку не записал",
            "не нашёл, из какой это диктовки — выделите предложение целиком",
        ),
        2600,
    ),
    (Status(Stage.LISTENING, "Слушаю", "отпустите клавишу, когда закончите"), 2600),
    (Status(Stage.CANCELLED, "Отменено"), 1600),
    (Status(Stage.TRANSCRIBING, "Распознаю", "8.1 с записи"), 2000),
    (
        Status(
            Stage.WARNING,
            "Вставил как есть · Ollama не запущена",
            "вчера я испачкал свои замшевые нью-балансы",
        ),
        2600,
    ),
    (Status(Stage.ERROR, "Нет микрофона", "устройство ввода не найдено"), 2400),
    (Status(Stage.PAUSED, "Пауза", "горячие клавиши отключены"), 2200),
    (Status(Stage.IDLE), 1400),
]


class FakeVoice:
    """Правдоподобная громкость: слоги, паузы между словами, вдохи."""

    def __init__(self) -> None:
        self.t = 0.0
        self.speaking = False

    def level(self) -> float:
        if not self.speaking:
            return 0.0008
        syllables = 0.5 + 0.5 * math.sin(self.t * 11.0)
        words = max(0.0, math.sin(self.t * 1.6)) ** 0.4
        breath = 0.75 + 0.25 * math.sin(self.t * 0.5 + 1.0)
        return 0.004 + 0.16 * syllables * words * breath


class MicVoice:
    """Громкость с настоящего микрофона: голос на плашке оценивают своим голосом,
    синтетика ровнее живой речи и прячет дёрганость."""

    def __init__(self, device: int | None, sample_rate: int) -> None:
        import numpy as np
        import sounddevice as sd

        self._level = 0.0

        def callback(block, _frames, _time, _status) -> None:
            self._level = float(np.sqrt(np.mean(np.square(block))))

        self._stream = sd.InputStream(device=device, samplerate=sample_rate, channels=1, dtype="float32",
                                      blocksize=sample_rate // 33, callback=callback)
        self._stream.start()

    def level(self) -> float:
        return self._level


class StopPanel(QWidget):
    """Кнопка, которая закрывает демо целиком.

    Демо крутится по кругу, а терминал, из которого его запустили, бывает не
    под рукой — например, когда демо запустил агент в фоне. Закрыть окошко
    крестиком — тоже выход.
    """

    def __init__(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QPushButton, QVBoxLayout

        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Демо")
        layout = QVBoxLayout(self)
        button = QPushButton("Остановить демо")
        button.setMinimumHeight(32)
        button.clicked.connect(QApplication.quit)
        layout.addWidget(button)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.left() + 24, screen.top() + 24)
        self.show()

    def closeEvent(self, event) -> None:  # noqa: N802 — имя из Qt
        event.accept()
        QApplication.quit()


def voice_panel(sources: dict, choice: dict, top: int) -> QWidget:
    """Переключатель источника звука для демо «voice»: свой микрофон или синтетика."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QButtonGroup, QLabel, QRadioButton, QVBoxLayout

    panel = QWidget()
    panel.setWindowTitle("Голос на плашке")
    panel.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
    layout = QVBoxLayout(panel)
    layout.addWidget(QLabel("Звук:"))
    sound = QButtonGroup(panel)
    for index, key in enumerate(sources):
        button = QRadioButton(key)
        button.setChecked(choice["source"] == key)
        button.toggled.connect(lambda on, key=key: on and choice.update(source=key))
        sound.addButton(button, index)
        layout.addWidget(button)
    screen = QApplication.primaryScreen().availableGeometry()
    panel.move(screen.left() + 24, top)
    panel.show()
    return panel


#: Короткий прогон для сравнения шрифтов: только то, где виден текст.
FONT_SCRIPT = [
    (Stage.LISTENING, "Слушаю", "отпустите клавишу, когда закончите", 3400),
    (Stage.POLISHING, "Причёсываю", "qwen2.5:3b", 1800),
    (
        Stage.DONE,
        "Готово за 2.1 с",
        "Слушай, там в Компас-3D надо переделать спецификацию по ЕСКД.",
        3400,
    ),
    (Stage.IDLE, "", "", 900),
]

FONT_CHOICES = ("Inter", "Onest", "Golos Text", "Manrope", "Segoe UI")

#: Разговор для демо карточки: вопрос и уточнение. Ответы — в духе того, что
#: пишет gpt-oss-120b по промпту ask.system_prompt: формулы юникодом, без
#: заголовков и таблиц.
CARD_TALK = [
    (
        "Чем softmax отличается от сигмоиды?",
        "Сигмоида превращает одно число в вероятность от 0 до 1: σ(x) = 1 / (1 + e^−x). "
        "Каждый выход считается отдельно, и в сумме вероятности могут дать что угодно.\n\n"
        "Softmax берёт сразу вектор и делит экспоненты на их сумму: softmax(xᵢ) = e^xᵢ / Σⱼ e^xⱼ. "
        "Выходы в сумме дают 1 — это распределение по классам, и рост одного класса отнимает "
        "вероятность у остальных.\n\n"
        "Отсюда правило:\n"
        "- **сигмоида** — когда классы не исключают друг друга (на снимке может быть и машина, "
        "и человек) или класс один;\n"
        "- **softmax** — когда ответ ровно один из нескольких.\n\n"
        "Для двух классов они совпадают: softmax от (x, 0) — это σ(x).",
    ),
    (
        "А для двух классов что ставить в последний слой?",
        "Один выход и сигмоиду. Два выхода с softmax дают то же самое, но учат лишний параметр: "
        "важна только разница между логитами.\n\n"
        "В PyTorch сигмоиду в модель не ставят — её берёт на себя функция потерь, так численно "
        "устойчивее:\n\n"
        "```python\n"
        "head = nn.Linear(hidden, 1)\n"
        "loss_fn = nn.BCEWithLogitsLoss()\n\n"
        "logits = head(features).squeeze(1)\n"
        "loss = loss_fn(logits, target.float())\n"
        "prob = torch.sigmoid(logits)  # только для предсказаний\n"
        "```\n\n"
        "Если классы несбалансированы, у `BCEWithLogitsLoss` есть `pos_weight` — отношение "
        "отрицательных примеров к положительным: при 900 и 100 это 9.\n\n"
        "Два выхода с `CrossEntropyLoss` — тоже рабочий вариант. Так удобнее, если потом "
        "добавится третий класс: поменять придётся только размер слоя.\n\n"
        "Порог 0.5 не обязателен: если ошибка в одну сторону дороже, подберите его по "
        "валидации — по F1 или по нужной полноте.",
    ),
]

#: Тот же последний вопрос после «Проверить в интернете».
CARD_RECHECK = (
    "Один выход и `BCEWithLogitsLoss` — так советует документация PyTorch: функция объединяет "
    "сигмоиду и бинарную кросс-энтропию, и это численно устойчивее, чем сигмоида отдельным "
    "слоем.\n\n"
    "```python\n"
    "head = nn.Linear(hidden, 1)\n"
    "loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([3.0]))\n"
    "```\n\n"
    "`pos_weight` — вес положительного класса. Пример из документации: 100 положительных и "
    "300 отрицательных примеров — pos_weight = 300 / 100 = 3.\n\n"
    "`CrossEntropyLoss` с двумя выходами тоже верен: он ждёт сырые логиты и номера классов, "
    "softmax делает сам."
)
CARD_SOURCES = [
    "https://pytorch.org/docs/stable/generated/torch.nn.BCEWithLogitsLoss.html",
    "https://pytorch.org/docs/stable/generated/torch.nn.CrossEntropyLoss.html",
]


def card_demo(cfg: Config) -> dict:
    """Вопрос, уточнение, перепроверка: плашка и карточка без облака и микрофона.

    Уточнение встаёт в ленту под первым ответом, как в приложении. Кнопки
    карточки живые: «Проверить в интернете» прогоняет перепроверку последнего
    хода, «Вставить» печатает текст в терминал, крестик начинает разговор
    заново. Свободный край тянется, и ширина, как в приложении, пишется в
    настройки.
    """
    from ui.card import AnswerCard

    hud = hud_module.create(cfg.ui)
    card = AnswerCard(cfg.ui)
    voice = FakeVoice()
    state = {"since": 0.0, "turn": 0, "next": None, "pieces": [], "sources": [], "epoch": 0, "talk": 1}
    hud.set_telemetry(lambda: (voice.level(), state["since"]))

    clock = QTimer(card)
    clock.setInterval(16)

    def tick() -> None:
        voice.t += 0.016
        if voice.speaking:
            state["since"] += 0.016

    clock.timeout.connect(tick)
    clock.start()

    # gpt-oss-120b на Groq пишет сотни токенов в секунду: кусок по 18 символов
    # в кадр примерно так и выглядит.
    stream = QTimer(card)
    stream.setInterval(16)

    def step() -> None:
        if state["pieces"]:
            card.feed(state["pieces"].pop(0))
            return
        stream.stop()
        card.finish(state["sources"])
        hud.show_status(Status(Stage.DONE, "Ответил", inserted=True))
        if state["next"] is not None:
            # Уточнение — через паузу на чтение, если человек не нажал ничего сам.
            later(9000, lambda: ask(state["next"]))

    stream.timeout.connect(step)

    def later(ms: int, action) -> None:
        """Отложенный шаг сценария; крестик и перепроверка отменяют все прежние."""
        epoch = state["epoch"]
        QTimer.singleShot(ms, lambda: epoch == state["epoch"] and action())

    def play(text: str, sources: list[str]) -> None:
        state["pieces"] = [text[i:i + 18] for i in range(0, len(text), 18)]
        state["sources"] = sources
        stream.start()

    def ask(index: int) -> None:
        question, answer = CARD_TALK[index]
        state["turn"] = index
        state["next"] = index + 1 if index + 1 < len(CARD_TALK) else None
        print(f"  вопрос: {question}")
        voice.speaking, state["since"] = True, 0.0
        hud.show_status(Status(Stage.LISTENING, "Слушаю", "вопрос · отпустите клавишу, когда закончите"))

        def heard() -> None:
            voice.speaking = False
            hud.show_status(Status(Stage.TRANSCRIBING, "Распознаю", "2.4 с записи"))

        def thinking() -> None:
            hud.show_status(Status(Stage.POLISHING, "Думаю", cfg.ask.model))
            card.start(f"demo-{state['talk']}", index + 1, question, False)

        later(2400, heard)
        later(3000, thinking)
        later(4200, lambda: play(answer, []))

    def interrupt() -> None:
        state["epoch"] += 1
        state["next"] = None
        state["pieces"] = []
        stream.stop()

    def recheck() -> None:
        interrupt()
        question, _ = CARD_TALK[state["turn"]]
        print(f"  проверяю в интернете: {question}")
        card.start(f"demo-{state['talk']}", state["turn"] + 1, question, True)
        hud.show_status(Status(Stage.POLISHING, "Ищу", cfg.ask.model))
        later(3200, lambda: play(CARD_RECHECK, CARD_SOURCES))

    def closed() -> None:
        interrupt()
        state["talk"] += 1
        print("  карточка закрыта — разговор заново\n")
        later(2500, lambda: ask(0))

    def resized(width: int) -> None:
        cfg.save()
        print(f"  ширина карточки {width} px — записал в config.json")

    card.recheck_requested.connect(recheck)
    card.insert_requested.connect(lambda text: print(f"  вставил бы: {text[:70]}…"))
    card.closed.connect(closed)
    card.resized.connect(resized)

    print("Демо карточки. Кнопки живые; выход — «Остановить демо» слева вверху.\n")
    ask(0)
    return {"hud": hud, "card": card, "clock": clock, "stream": stream}


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VoiceTyper Demo")
    # Пока крутится цикл Qt, Python не видит Ctrl+C: без этого демо из
    # терминала не закрыть.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    stop = StopPanel()

    cfg = Config.load()
    argument = sys.argv[1] if len(sys.argv) > 1 else ""
    cycle_fonts = argument.lower() == "fonts"
    voice_only = argument.lower() == "voice"
    card_only = argument.lower() == "card"

    theme.init_fonts(argument if argument and not (cycle_fonts or voice_only or card_only) else cfg.ui.font)
    if card_only:
        keep = card_demo(cfg)  # noqa: F841 — держит окна и таймеры живыми
        return app.exec()
    state = {"stop": stop}
    state.update(hud=hud_module.create(cfg.ui), step=0, font=0)

    voice = FakeVoice()
    elapsed = {"since": 0.0}

    sources = {"синтетика": voice}
    if voice_only:
        try:
            sources = {"микрофон": MicVoice(cfg.audio.device, cfg.audio.sample_rate), **sources}
        except Exception as exc:  # noqa: BLE001 — без микрофона демо идёт на синтетике
            print(f"Микрофон не открылся ({exc}) — голос синтетический")
    choice = {"source": next(iter(sources))}

    def telemetry() -> tuple[float, float]:
        return sources[choice["source"]].level(), elapsed["since"]

    state["hud"].set_telemetry(telemetry)

    clock = QTimer()
    clock.setInterval(16)

    def tick() -> None:
        voice.t += 0.016
        if voice.speaking:
            elapsed["since"] += 0.016

    clock.timeout.connect(tick)
    clock.start()

    def swap_font() -> None:
        """Шрифт выбирается при создании плашки, поэтому её надо пересобрать."""
        family = FONT_CHOICES[state["font"] % len(FONT_CHOICES)]
        state["font"] += 1
        chosen = theme.init_fonts(family)

        old = state["hud"]
        old.hide()
        old.deleteLater()

        fresh = hud_module.create(cfg.ui)
        fresh.set_telemetry(telemetry)
        state["hud"] = fresh
        print(f"\n=== шрифт: {chosen} ===")

    def advance() -> None:
        if cycle_fonts:
            index = state["step"] % len(FONT_SCRIPT)
            if index == 0:
                swap_font()
            stage, title, detail, hold = FONT_SCRIPT[index]
            family = FONT_CHOICES[(state["font"] - 1) % len(FONT_CHOICES)]
            status = Status(stage, f"{title} · {family}" if title else "", detail)
        else:
            status, hold = SCRIPT[state["step"] % len(SCRIPT)]

        state["step"] += 1
        voice.speaking = status.stage is Stage.LISTENING
        if voice.speaking:
            elapsed["since"] = 0.0

        print(f"  {status.stage.name:13s} {status.title}")
        state["hud"].show_status(status)
        QTimer.singleShot(hold, advance)

    print("Демо HUD. Выход — «Остановить демо» слева вверху.\n")
    if voice_only:
        voice.speaking = True
        state["panel"] = voice_panel(sources, choice, stop.frameGeometry().bottom() + 12)
        state["hud"].show_status(Status(Stage.LISTENING, "Слушаю"))
    else:
        advance()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
