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

from core import journal
from core import stt
from core.cloud import CloudClient, CloudLimited, CloudUnavailable
from core.journal import Journal, Record
from core.llm import LLMUnavailable, OllamaClient, Polished
from core.paster import ClipboardError, Paster
from core.state import Stage, Status
from core.stt import WhisperEngine


@dataclass
class Job:
    audio: np.ndarray
    style: str | None
    """careful | dry — стиль правки; None — вставить сырой текст Whisper."""

    hotkey: str


class _Shutdown:
    """Маркер конца очереди."""


@dataclass
class _ReleaseGpu:
    """Просьба отдать видеокарту (True) или забрать обратно (False).

    Идёт через ту же очередь, что и диктовки: переселение моделей происходит
    строго между фразами, в рабочем потоке, и не гонится с распознаванием.
    """

    released: bool


class Pipeline(QObject):
    status = Signal(object)
    """Очередное состояние (core.state.Status) для HUD и трея."""

    ready = Signal(str)
    """Модель загружена; в аргументе — на чём именно она поднялась."""

    failed = Signal(str)
    """Модель не загрузилась, работать не получится."""

    transcribed = Signal(str)
    """Итоговый текст, который ушёл в активное окно."""

    quota = Signal(str)
    """Остатки лимитов облака после очередного запроса, строкой для трея."""

    limited = Signal(str, float)
    """Облако упёрлось в лимит: вид («minute» или «day») и секунды до сброса."""

    def __init__(
        self,
        whisper: WhisperEngine,
        llm: OllamaClient,
        paster: Paster,
        sounds,
        sample_rate: int,
        journal_log: Journal | None = None,
        release_gpu: bool = False,
        cloud: CloudClient | None = None,
    ) -> None:
        super().__init__()
        self._release_gpu = release_gpu
        self._cloud = cloud
        self._lite = not stt.available()
        """Лёгкая сборка: локального Whisper нет, всё делает облако."""

        self._whisper = whisper
        self._llm = llm
        self._paster = paster
        self._sounds = sounds
        self._sample_rate = sample_rate
        self._journal = journal_log or Journal(enabled=False)

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

    def set_gpu_released(self, released: bool) -> None:
        """Отдать видеокарту или забрать обратно; выполнится между фразами."""
        self._queue.put(_ReleaseGpu(released))

    @property
    def gpu_released(self) -> bool:
        return self._release_gpu

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
                if isinstance(item, _ReleaseGpu):
                    self._switch_gpu(item.released)
                else:
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
        return self._bring_up()

    def _bring_up(self) -> bool:
        """Поднимает Whisper на нужном устройстве и Ollama, шлёт ready."""
        if self._lite and not self._cloud_configured:
            message = "лёгкая сборка распознаёт только в облаке — вставьте cloud.api_key в настройки"
            self._emit(Stage.ERROR, "Нужен ключ облака", message)
            self.failed.emit(message)
            return False
        if self._cloud_whisper:
            # Локальную модель не грузим вовсе: на процессоре она занимает
            # полторы гигабайта памяти, которой и так впритык. Поднимется
            # сама, если облако подведёт.
            self._whisper.unload()
            where = f"облако · {self._cloud.cfg.whisper_model}"
        else:
            try:
                where = self._whisper.load(self._whisper_device())
            except Exception as exc:
                self._emit(Stage.ERROR, "Whisper не запустился", str(exc))
                self.failed.emit(str(exc))
                return False
            self._emit(Stage.LOADING, "Прогреваю модель", where)
            self._whisper.warmup()

        summary = f"{where} · {self._prepare_llm()}"
        print(f"[pipeline] готов: {summary}")
        self.ready.emit(summary)
        self._emit(Stage.IDLE)
        return True

    @property
    def _cloud_configured(self) -> bool:
        return self._cloud is not None and self._cloud.configured

    @property
    def _cloud_whisper(self) -> bool:
        """Распознавать в облаке: лёгкая сборка — всегда; иначе пока видеокарта
        отдана, есть ключ и так настроено."""
        if not self._cloud_configured:
            return False
        if self._lite:
            return True
        return bool(self._release_gpu and self._whisper.cfg.cloud_when_released)

    @property
    def _cloud_llm(self) -> bool:
        """Править в облаке: лёгкая сборка — всегда при ключе; иначе по настройке."""
        if not self._cloud_configured:
            return False
        return self._lite or self._llm.cfg.backend == "cloud"

    def _whisper_device(self) -> str | None:
        """None — как в настройках; «cpu» — пока видеокарта отдана."""
        return "cpu" if self._release_gpu else None

    def _switch_gpu(self, released: bool) -> None:
        """Переселяет модели: на процессор без правки — или обратно на видеокарту.

        Переезд туда занимает секунды (выгрузка мгновенна, Whisper на CPU
        грузится из кэша на диске), обратно — десяток секунд с прогревом.
        Всё это время очередь диктовок ждёт, а HUD показывает «Загружаю».
        """
        if released == self._release_gpu and self._whisper.is_loaded:
            return
        self._release_gpu = released
        if released:
            self._emit(Stage.LOADING, "Отдаю видеокарту", "выгружаю редактор")
            if self._llm.cfg.enabled:
                self._llm.unload()
            where = "в облако" if self._cloud_whisper else "на процессор"
            self._emit(Stage.LOADING, "Отдаю видеокарту", f"Whisper переезжает {where}")
        else:
            self._emit(Stage.LOADING, "Забираю видеокарту", "Whisper возвращается на CUDA")
        self._bring_up()

    def _prepare_llm(self) -> str:
        """Поднимает Ollama и возвращает подпись о её состоянии.

        Проверка живёт в рабочем потоке специально: обращение к сети из потока
        интерфейса подвесило бы анимацию на всё время ожидания.
        """
        if not self._llm.cfg.enabled:
            return "без правки"
        if self._lite and not self._cloud_llm:
            return "без правки: нет ключа облака"
        if self._cloud_llm:
            # Ollama не трогаем: пока правит облако, её 2 ГБ видеопамяти
            # свободны. Если облако подведёт, Ollama поднимется сама.
            return self._cloud.label
        if self._release_gpu:
            return "видеокарта отдана, без правки"

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
        record = Record(at=journal.now(), audio_s=round(seconds, 2), hotkey=job.hotkey)

        self._emit(Stage.TRANSCRIBING, "Распознаю", f"{seconds:.1f} с записи")
        heard = time.monotonic()
        try:
            raw_text = self._transcribe(job.audio, record)
        except CloudUnavailable as exc:
            # Лёгкая сборка: локального Whisper нет, откатываться некуда.
            record.error = str(exc)
            self._close(record, started)
            self._emit(Stage.ERROR, "Не распознал", str(exc))
            self._sounds.play("error")
            return
        record.whisper_s = round(time.monotonic() - heard, 2)
        record.raw = raw_text
        record.raw_words = len(raw_text.split())

        if not raw_text:
            record.skipped = "Whisper ничего не разобрал"
            self._close(record, started)
            self._emit(Stage.WARNING, "Ничего не разобрал", "попробуйте сказать чётче")
            self._sounds.play("error")
            return
        print(f"[pipeline] сырой текст: «{raw_text}»")

        text = raw_text
        warning: str | None = None

        if job.style is None:
            record.skipped = "сырой режим"
        elif self._release_gpu and not self._cloud_llm:
            # Гонять 3b-модель на процессоре — это десятки секунд на фразу;
            # пока видеокарта отдана, честнее вставлять текст как есть.
            record.skipped = "видеокарта отдана"
        else:
            record.skipped = self._llm.skip_reason(raw_text)
        if not record.skipped:
            record.style = job.style or ""
            verb = "Сушу" if job.style == "dry" else "Причёсываю"
            try:
                polished = self._polish(raw_text, job.style or "careful", verb, record)
            except LLMUnavailable as exc:
                warning = str(exc)
                record.error = warning
                # Отклонённый ответ журналу нужен не меньше принятого: по нему
                # видно, на чём именно модель срывается.
                _note(record, exc.polished)
            else:
                text = polished.text
                _note(record, polished)

        try:
            self._paster.paste(text, hotkey=job.hotkey)
        except ClipboardError as exc:
            record.error = str(exc)
            self._close(record, started)
            self._emit(Stage.ERROR, "Не смог вставить", str(exc))
            self._sounds.play("error")
            return

        record.final = text
        record.changed_words = journal.count_changes(raw_text, text)
        if self._cloud is not None and self._cloud.quota.known:
            record.cloud_quota = self._cloud.quota_line()
        took = self._close(record, started)

        self.transcribed.emit(text)
        self._sounds.play("success")
        if warning:
            self._emit(Stage.WARNING, f"Вставил как есть · {warning}", text)
        else:
            self._emit(Stage.DONE, f"Готово за {took:.1f} с", text)

    def _transcribe(self, audio: np.ndarray, record: Record) -> str:
        """Whisper в облаке, если видеокарта отдана, иначе локальный."""
        if self._cloud_whisper:
            cfg = self._whisper.cfg
            try:
                text = self._cloud.transcribe(
                    audio, self._sample_rate, cfg.language, cfg.initial_prompt
                )
                record.stt = self._cloud.cfg.whisper_model
                return text
            except CloudUnavailable as exc:
                if self._lite:
                    raise
                print(f"[pipeline] облачный Whisper не ответил: {exc}; поднимаю локальный")
                record.error = str(exc)
            finally:
                self.quota.emit(self._cloud.quota_line())
        if not self._whisper.is_loaded:
            self._emit(Stage.LOADING, "Поднимаю Whisper", "облако не ответило")
            self._whisper.load(self._whisper_device())
        record.stt = f"{self._whisper.model_name} · {self._whisper.device}"
        return self._whisper.transcribe(audio)

    def _polish(self, raw_text: str, style: str, verb: str, record: Record) -> Polished:
        """Правка облаком с откатом на Ollama — или сразу Ollama."""
        if self._cloud_llm:
            record.llm_model = self._cloud.label
            try:
                return self._polish_cloud(raw_text, style, verb)
            except LLMUnavailable as exc:
                if isinstance(exc, CloudLimited):
                    self.limited.emit(exc.kind, exc.reset_s)
                if self._lite or self._release_gpu or not self._llm.cfg.enabled:
                    raise
                print(f"[pipeline] {exc}; пробую Ollama")
                _note(record, exc.polished)
            finally:
                self.quota.emit(self._cloud.quota_line())
        record.llm_model = self._llm.cfg.model
        self._emit(Stage.POLISHING, verb, self._llm.cfg.model)
        return self._llm.polish(raw_text, style)

    #: Дольше этого минутный лимит не ждём — быстрее ответит Ollama.
    _MAX_QUOTA_WAIT_S = 6.0

    def _polish_cloud(self, raw_text: str, style: str, verb: str) -> Polished:
        """Сначала сверяется с лимитами, потом идёт в облако.

        Если минутных токенов на фразу не хватает и сброс близко — ждёт его;
        если далеко или кончились суточные запросы — сразу отдаёт правку
        Ollama через LLMUnavailable, не тратя попытку на заведомый отказ.
        """
        wait = self._cloud.wait_for_polish(raw_text, style)
        if wait is None:
            quota = self._cloud.quota
            raise CloudLimited(
                "облако: исчерпан суточный лимит", "day",
                max(1.0, quota.requests_reset_s - quota.age_s),
            )
        if wait > self._MAX_QUOTA_WAIT_S:
            raise CloudLimited(f"облако: лимит минуты, сброс через {wait:.0f} с", "minute", wait)
        if wait > 0:
            self._emit(Stage.POLISHING, "Жду лимит облака", f"{wait:.0f} с")
            time.sleep(wait)
        self._emit(Stage.POLISHING, verb, self._cloud.cfg.model)
        return self._cloud.polish(raw_text, style)

    def _close(self, record: Record, started: float) -> float:
        """Дописывает длительность и отправляет запись в журнал."""
        took = time.monotonic() - started
        record.total_s = round(took, 2)
        self._journal.write(record)
        return took

    def _emit(self, stage: Stage, title: str = "", detail: str = "") -> None:
        self.status.emit(Status(stage=stage, title=title, detail=detail))


def _note(record: Record, polished: Polished | None) -> None:
    """Переносит в запись то, что модель рассказала о себе."""
    if polished is None:
        return
    record.llm_s = round(polished.took_s, 2)
    record.output_tokens = polished.output_tokens
    record.gen_s = round(polished.gen_s, 3)
    record.response = polished.response
    record.polished = polished.text
    record.accepted = polished.accepted
