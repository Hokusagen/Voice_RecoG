"""Демо-режим: прогоняет HUD по состояниям, не трогая микрофон и модели.

    venv\\Scripts\\python.exe src\\demo.py            все состояния, шрифт из конфига
    venv\\Scripts\\python.exe src\\demo.py fonts      короткий цикл, шрифты по очереди
    venv\\Scripts\\python.exe src\\demo.py Onest      все состояния заданным шрифтом
    venv\\Scripts\\python.exe src\\demo.py voice      «Слушаю» без конца, голос с микрофона

Выход — Ctrl+C в терминале.

Нужен, чтобы смотреть на оформление живьём: стекло, кромку и переходы можно
оценить только в движении, по скриншотам они врут.
"""

from __future__ import annotations

import math
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


def voice_panel(hud, sources: dict, choice: dict) -> QWidget:
    """Переключатели вида голоса и источника звука для демо «voice»."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QButtonGroup, QLabel, QRadioButton, QVBoxLayout

    panel = QWidget()
    panel.setWindowTitle("Голос на плашке")
    panel.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
    layout = QVBoxLayout(panel)
    styles = {"tide": "Прилив — свет снизу капсулы", "drop": "Капля — пятна справа от заголовка"}
    layout.addWidget(QLabel("Вид голоса:"))
    group = QButtonGroup(panel)
    for index, (key, title) in enumerate(styles.items()):
        button = QRadioButton(title)
        button.setChecked(getattr(hud, "voice_style", "tide") == key)
        button.toggled.connect(lambda on, key=key: on and setattr(hud, "voice_style", key))
        group.addButton(button, index)
        layout.addWidget(button)
    layout.addWidget(QLabel("Звук:"))
    sound = QButtonGroup(panel)
    for index, key in enumerate(sources):
        button = QRadioButton(key)
        button.setChecked(choice["source"] == key)
        button.toggled.connect(lambda on, key=key: on and choice.update(source=key))
        sound.addButton(button, index)
        layout.addWidget(button)
    screen = QApplication.primaryScreen().availableGeometry()
    panel.move(screen.left() + 24, screen.top() + 24)
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


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("VoiceTyper Demo")

    cfg = Config.load()
    argument = sys.argv[1] if len(sys.argv) > 1 else ""
    cycle_fonts = argument.lower() == "fonts"
    voice_only = argument.lower() == "voice"

    theme.init_fonts(argument if argument and not (cycle_fonts or voice_only) else cfg.ui.font)
    state = {"hud": hud_module.create(cfg.ui), "step": 0, "font": 0}

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

    print("Демо HUD. Ctrl+C в терминале, чтобы закрыть.\n")
    if voice_only:
        voice.speaking = True
        state["panel"] = voice_panel(state["hud"], sources, choice)
        state["hud"].show_status(Status(Stage.LISTENING, "Слушаю"))
    else:
        advance()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
