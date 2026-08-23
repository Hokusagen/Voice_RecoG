"""Фоновый конвейер: звук -> Whisper -> Ollama -> вставка.

Раньше вся эта цепочка выполнялась прямо в цикле опроса клавиатуры, так что на
время обработки — а это секунды — приложение переставало реагировать вообще на
всё. Здесь обработка живёт в отдельном потоке с очередью: пока распознаётся одна
фраза, можно надиктовать следующую, а пауза и выход срабатывают мгновенно.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QObject, Signal

from core.llm import LLMUnavailable, OllamaClient
from core.paster import ClipboardError, Paster
from core.state import Stage, Status
from core.stt import WhisperEngine


@dataclass
class Job:
    audio: np.ndarray
    polish: bool
    hotkey: str


class _Shutdown:
    """Маркер конца очереди."""


class Pipeline(QObject):
    status = Signal(object)
    """Очередное состояние (core.state.Status) для HUD и трея."""

    ready = Signal(str)
    """Модель загружена; в аргументе — на чём именно она поднялась."""

    failed = Signal(str)
    """Модель не загрузилась, работать не получится."""

    transcribed = Signal(str)
    """Итоговый текст, который ушёл в активное окно."""

    def __init__(
        self,
        whisper: WhisperEngine,
        llm: OllamaClient,
        paster: Paster,
        sounds,
        sample_rate: int,
    ) -> None:
        super().__init__()
        self._whisper = whisper
        self._llm = llm
        self._paster = paster
        self._sounds = sounds
        self._sample_rate = sample_rate

        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._busy = threading.Event()

    # ---------- жизненный цикл ----------

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self._thread.start()

    def shutdown(self, timeout: float = 3.0) -> None:
        self._queue.put(_Shutdown())
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def submit(self, job: Job) -> None:
        self._queue.put(job)

    @property
    def is_busy(self) -> bool:
        return self._busy.is_set()

    # ---------- рабочий поток ----------

    def _run(self) -> None:
        if not self._load_models():
            return
        while True:
            item = self._queue.get()
            if isinstance(item, _Shutdown):
                return
            self._busy.set()
            try:
                self._process(item)
            except Exception as exc:  # поток не должен умирать из-за одной фразы
                print(f"[pipeline] непредвиденный сбой: {exc}")
                self._emit(Stage.ERROR, "Сбой обработки", str(exc))
                self._sounds.play("error")
            finally:
                self._busy.clear()

    def _load_models(self) -> bool:
        detail = (
            "первый запуск: качаю модель, это займёт несколько минут"
            if not self._whisper.is_cached()
            else "готовлю распознавание"
        )
        self._emit(Stage.LOADING, "Загружаю модель", detail)

        try:
            where = self._whisper.load()
        except Exception as exc:
            self._emit(Stage.ERROR, "Whisper не запустился", str(exc))
            self.failed.emit(str(exc))
            return False

        self._emit(Stage.LOADING, "Прогреваю модель", where)
        self._whisper.warmup()

        self.ready.emit(f"{where} · {self._prepare_llm()}")
        self._emit(Stage.IDLE)
        return True

    def _prepare_llm(self) -> str:
        """Поднимает Ollama и возвращает подпись о её состоянии.

        Проверка живёт в рабочем потоке специально: обращение к сети из потока
        интерфейса подвесило бы анимацию на всё время ожидания.
        """
        if not self._llm.cfg.enabled:
            return "без правки"

        # Ollama держит модель в памяти только пять минут после запроса, поэтому
        # без прогрева первая же диктовка ждала бы загрузку весов.
        if self._llm.cfg.warmup:
            self._emit(Stage.LOADING, "Прогреваю редактор", self._llm.cfg.model)
            if self._llm.warmup():
                return self._llm.cfg.model
            print(f"[pipeline] Ollama недоступна: {self._llm.last_error}")
            return self._llm.last_error or "Ollama недоступна"

        return self._llm.cfg.model if self._llm.is_available() else "Ollama недоступна"

    # ---------- обработка одной фразы ----------

    def _process(self, job: Job) -> None:
        seconds = len(job.audio) / self._sample_rate
        started = time.monotonic()

        self._emit(Stage.TRANSCRIBING, "Распознаю", f"{seconds:.1f} с записи")
        raw_text = self._whisper.transcribe(job.audio)
        if not raw_text:
            self._emit(Stage.WARNING, "Ничего не разобрал", "попробуйте сказать чётче")
            self._sounds.play("error")
            return
        print(f"[pipeline] сырой текст: «{raw_text}»")

        text = raw_text
        warning: str | None = None

        if job.polish and not self._llm.should_skip(raw_text):
            self._emit(Stage.POLISHING, "Причёсываю", self._llm.cfg.model)
            try:
                text = self._llm.polish(raw_text)
            except LLMUnavailable as exc:
                warning = str(exc)
                text = raw_text

        try:
            self._paster.paste(text, hotkey=job.hotkey)
        except ClipboardError as exc:
            self._emit(Stage.ERROR, "Не смог вставить", str(exc))
            self._sounds.play("error")
            return

        self.transcribed.emit(text)
        took = time.monotonic() - started

        self._sounds.play("success")
        if warning:
            self._emit(Stage.WARNING, f"Вставил как есть · {warning}", text)
        else:
            self._emit(Stage.DONE, f"Готово за {took:.1f} с", text)

    def _emit(self, stage: Stage, title: str = "", detail: str = "") -> None:
        self.status.emit(Status(stage=stage, title=title, detail=detail))
