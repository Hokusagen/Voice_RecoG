"""Связывает горячие клавиши, запись, конвейер и интерфейс."""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtWidgets import QApplication

from config import APP_VERSION, CONFIG_PATH, Config
from core import autostart
from core.audio import AudioError, AudioRecorder
from core.history import History
from core.journal import Journal
from core.hotkeys import HotkeyListener
from core.llm import OllamaClient
from core.paster import Paster, write_text
from core.pipeline import Job, Pipeline
from core.sounds import SoundBoard
from core.state import Stage, Status
from core.stt import WhisperEngine
from ui.hud import Hud
from ui.tray import Tray

#: Как часто проверять, не пора ли отпустить микрофон.
_IDLE_CHECK_MS = 15_000


class Controller(QObject):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg

        self.recorder = AudioRecorder(cfg.audio)
        self.whisper = WhisperEngine(cfg.whisper)
        self.llm = OllamaClient(cfg.llm)
        self.paster = Paster(cfg.paste)
        self.sounds = SoundBoard(enabled=cfg.ui.sounds, volume=cfg.ui.volume)
        self.history = History(cfg.ui.history_size)
        self.journal = Journal(cfg.llm.journal, cfg.llm.journal_max_mb)

        self.hud = Hud(cfg.ui)
        self.hud.set_telemetry(lambda: (self.recorder.level, self.recorder.elapsed))

        self.tray = Tray(cfg.ui, cfg.hotkeys)
        self.hotkeys = HotkeyListener(cfg.hotkeys)

        self.pipeline = Pipeline(
            self.whisper, self.llm, self.paster, self.sounds, cfg.audio.sample_rate,
            journal_log=self.journal,
        )

        self._action: str | None = None
        self._paused = False
        self._ready = False

        self._max_duration = QTimer(self)
        self._max_duration.setSingleShot(True)
        self._max_duration.timeout.connect(self._on_max_duration)

        self._idle_check = QTimer(self)
        self._idle_check.setInterval(_IDLE_CHECK_MS)
        self._idle_check.timeout.connect(self.recorder.close_if_idle)

        self._tray_reset = QTimer(self)
        self._tray_reset.setSingleShot(True)
        self._tray_reset.timeout.connect(self._reset_tray_stage)

        self._connect()

    def _connect(self) -> None:
        self.hotkeys.pressed.connect(self._on_pressed)
        self.hotkeys.released.connect(self._on_released)
        self.hotkeys.cancelled.connect(self._on_cancel)

        self.pipeline.status.connect(self._on_status)
        self.pipeline.ready.connect(self._on_ready)
        self.pipeline.failed.connect(self._on_failed)
        self.pipeline.transcribed.connect(self._on_transcribed)

        self.tray.pause_toggled.connect(self._on_pause)
        self.tray.sounds_toggled.connect(self._on_sounds)
        self.tray.autostart_toggled.connect(self._on_autostart)
        self.tray.mode_changed.connect(self._on_mode)
        self.tray.history_picked.connect(self._on_history_pick)
        self.tray.config_requested.connect(self._on_open_config)
        self.tray.journal_requested.connect(self._on_open_journal)
        self.tray.quit_requested.connect(self.shutdown)

    # ---------- запуск и остановка ----------

    def start(self) -> None:
        self.tray.set_autostart_checked(autostart.is_enabled())
        self.tray.set_history(self.history)
        self.tray.setToolTip(f"Голосовой ввод {APP_VERSION} · {self.cfg.hotkeys.record.upper()}")
        self.tray.show()

        self.pipeline.start()
        self.hotkeys.start()
        self._idle_check.start()

    def shutdown(self) -> None:
        self._idle_check.stop()
        self.hotkeys.stop()
        self.recorder.cancel_capture()
        self.recorder.close()
        self.hud.hide()
        self.tray.hide()
        self.pipeline.shutdown()
        QApplication.quit()

    # ---------- горячие клавиши ----------

    @Slot(str)
    def _on_pressed(self, action: str) -> None:
        if self.cfg.hotkeys.mode == "toggle" and self._action is not None:
            self._finish_recording()
            return
        self._begin_recording(action)

    @Slot(str)
    def _on_released(self, action: str) -> None:
        if self.cfg.hotkeys.mode == "toggle":
            return
        if self._action == action:
            self._finish_recording()

    @Slot()
    def _on_cancel(self) -> None:
        if self._action is None:
            return
        self._action = None
        self._max_duration.stop()
        self.recorder.cancel_capture()
        self.sounds.play("cancel")
        self._show(Stage.CANCELLED, "Отменено")

    def _begin_recording(self, action: str) -> None:
        if self._action is not None:
            return
        if not self._ready:
            self._show(Stage.WARNING, "Ещё загружаюсь", "модель не готова")
            return

        try:
            self.recorder.start_capture()
        except AudioError as exc:
            self.sounds.play("error")
            self._show(Stage.ERROR, "Нет микрофона", str(exc))
            return

        self._action = action
        self.sounds.play("start")
        hint = "отпустите клавишу, когда закончите"
        if self.cfg.hotkeys.mode == "toggle":
            hint = f"нажмите {self.cfg.hotkeys.record.upper()} ещё раз"
        self._show(Stage.LISTENING, "Слушаю", hint)
        self._max_duration.start(self.cfg.audio.max_duration_s * 1000)

    def _finish_recording(self) -> None:
        action, self._action = self._action, None
        if action is None:
            return
        self._max_duration.stop()

        audio = self.recorder.stop_capture()
        self.sounds.play("stop")

        if audio is None:
            self.hud.dismiss()
            return

        seconds = self.recorder.duration_of(audio)
        if seconds * 1000 < self.cfg.audio.min_duration_ms:
            self._show(Stage.CANCELLED, "Слишком коротко", f"{seconds:.1f} с")
            return
        if self.recorder.is_silent():
            # Whisper на тишине всё равно ничего не даст, а полторы секунды
            # обработки съест.
            self._show(Stage.WARNING, "Тишина", "микрофон ничего не услышал")
            return

        self.pipeline.submit(
            Job(audio=audio, polish=action == "record", hotkey=getattr(self.cfg.hotkeys, action))
        )

    @Slot()
    def _on_max_duration(self) -> None:
        if self._action is not None:
            self._finish_recording()

    # ---------- события конвейера ----------

    @Slot(object)
    def _on_status(self, status: Status) -> None:
        # Пока человек диктует, экран принадлежит записи: обработка предыдущей
        # фразы идёт фоном и не должна перебивать эквалайзер.
        if self._action is not None and status.stage is not Stage.ERROR:
            return
        self._render(status)

    @Slot(str)
    def _on_ready(self, where: str) -> None:
        self._ready = True
        summary = f"{self.cfg.whisper.model} · {where}"
        self.tray.set_summary(summary)
        self.tray.setToolTip(f"Голосовой ввод {APP_VERSION} · {self.cfg.hotkeys.record.upper()}\n{summary}")
        self.sounds.play("ready")
        self._show(Stage.DONE, "Готов к работе", f"зажмите {self.cfg.hotkeys.record.upper()}")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._ready = False
        self.tray.set_summary("Не запустился")
        self.sounds.play("error")

    @Slot(str)
    def _on_transcribed(self, text: str) -> None:
        self.history.add(text)
        self.tray.set_history(self.history)

    # ---------- меню трея ----------

    @Slot(bool)
    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self.hotkeys.set_enabled(not paused)
        if paused and self._action is not None:
            self._on_cancel()
        if paused:
            self.recorder.close()
            self._show(Stage.PAUSED, "Пауза", "горячие клавиши отключены")
        else:
            self._show(Stage.DONE, "Снова слушаю", f"зажмите {self.cfg.hotkeys.record.upper()}")

    @Slot(bool)
    def _on_sounds(self, enabled: bool) -> None:
        self.cfg.ui.sounds = enabled
        self.sounds.enabled = enabled
        if enabled:
            self.sounds.volume = self.cfg.ui.volume
        self.cfg.save()

    @Slot(bool)
    def _on_autostart(self, enabled: bool) -> None:
        actual = autostart.set_enabled(enabled)
        self.cfg.ui.autostart = actual
        self.cfg.save()
        if actual != enabled:
            self.tray.set_autostart_checked(actual)

    @Slot(str)
    def _on_mode(self, mode: str) -> None:
        self.cfg.hotkeys.mode = mode
        self.cfg.save()

    @Slot(str)
    def _on_history_pick(self, text: str) -> None:
        write_text(text)
        self._show(Stage.DONE, "Скопировано в буфер", text)

    @Slot()
    def _on_open_config(self) -> None:
        self.cfg.save()
        try:
            os.startfile(CONFIG_PATH)
        except OSError as exc:
            self._show(Stage.ERROR, "Не открылся конфиг", str(exc))

    @Slot()
    def _on_open_journal(self) -> None:
        """Показывает журнал в проводнике: .jsonl открывать нечем, папку — есть чем."""
        path = self.journal.path
        try:
            if path.exists():
                subprocess.Popen(["explorer", f"/select,{path}"])
            else:
                os.startfile(path.parent)
        except OSError as exc:
            self._show(Stage.ERROR, "Не открылся журнал", str(exc))

    # ---------- отрисовка ----------

    def _show(self, stage: Stage, title: str, detail: str = "") -> None:
        self._render(Status(stage=stage, title=title, detail=detail))

    def _render(self, status: Status) -> None:
        self.hud.show_status(status)
        self.tray.set_stage(status.stage)
        if status.is_transient:
            # Иконка должна гаснуть вместе с плашкой, а та держится тем дольше,
            # чем длиннее распознанный текст.
            self._tray_reset.start(self.hud.hold_ms(status))
        else:
            self._tray_reset.stop()

    @Slot()
    def _reset_tray_stage(self) -> None:
        self.tray.set_stage(Stage.PAUSED if self._paused else Stage.IDLE)
