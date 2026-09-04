"""Распознавание речи через faster-whisper."""

from __future__ import annotations

import gc
import os
import re
import time
from pathlib import Path

import numpy as np

from config import WhisperConfig

#: Фразы, которые Whisper дорисовывает на тишине и обрывках. Если весь ответ
#: состоит только из такой фразы — это галлюцинация, а не речь.
_HALLUCINATIONS = (
    "продолжение следует",
    "субтитры сделал",
    "субтитры создавал",
    "редактор субтитров",
    "спасибо за просмотр",
    "подписывайтесь на канал",
    "подпишись на канал",
    "thanks for watching",
    "thank you for watching",
    "subtitles by",
)

_PUNCT_ONLY = re.compile(r"^[\s.,!?…\-–—\"'«»()]*$")


class WhisperEngine:
    """Ленивая обёртка над WhisperModel.

    faster_whisper импортируется только в load(): его импорт тянет ctranslate2 и
    CUDA-библиотеки и стоит несколько секунд, а окно и трей должны появиться
    сразу.
    """

    def __init__(self, cfg: WhisperConfig) -> None:
        self.cfg = cfg
        self._model = None
        self.device = ""
        self.compute_type = ""
        self.model_name = ""

    # ---------- загрузка ----------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def is_cached(self) -> bool:
        """Скачана ли модель ранее — чтобы честно предупредить о долгом старте."""
        if os.path.isdir(self.cfg.model):
            return True
        cache = Path(
            os.environ.get("HF_HUB_CACHE")
            or os.environ.get("HF_HOME", "")
            or Path.home() / ".cache" / "huggingface"
        )
        if cache.name != "hub":
            cache = cache / "hub"
        try:
            return any(cache.glob("models--*whisper*"))
        except OSError:
            return False

    def load(self, device: str | None = None) -> str:
        """Загружает модель и возвращает строку вида 'cuda / int8_float16'.

        device перекрывает настройку: так конвейер переселяет модель на
        процессор, когда видеокарту отдали другим задачам, и обратно.
        """
        from faster_whisper import WhisperModel

        self.unload()
        attempts = self._device_plan(device or self.cfg.device)
        # На процессоре может стоять другая, более лёгкая модель.
        name = self.cfg.cpu_model if device == "cpu" and self.cfg.cpu_model else self.cfg.model
        last_error: Exception | None = None
        for device, compute_type in attempts:
            try:
                started = time.monotonic()
                self._model = WhisperModel(name, device=device, compute_type=compute_type)
                self.device, self.compute_type = device, compute_type
                took = time.monotonic() - started
                print(f"[stt] {name} на {device}/{compute_type} за {took:.1f} с")
                self.model_name = name
                return f"{device} / {compute_type}"
            except Exception as exc:
                last_error = exc
                print(f"[stt] {device}/{compute_type} не поднялся: {exc}")

        raise RuntimeError(f"не удалось загрузить Whisper: {last_error}")

    def unload(self) -> None:
        """Отпускает модель вместе с её видеопамятью.

        ctranslate2 освобождает память при уничтожении объекта, но ссылка на
        него могла остаться в кадрах сборщика — поэтому ещё и gc.collect().
        """
        if self._model is None:
            return
        self._model = None
        self.device = self.compute_type = ""
        gc.collect()

    def _device_plan(self, wanted_device: str) -> list[tuple[str, str]]:
        """Список попыток «устройство + точность» от желаемой к запасной."""
        wanted_device = wanted_device.lower()
        wanted_compute = self.cfg.compute_type.lower()

        def compute_for(device: str) -> str:
            # Явно заданная точность относится к видеокарте: на процессоре
            # float16 не поддерживается, а int8 — единственный быстрый вариант.
            if wanted_compute != "auto" and device == "cuda":
                return wanted_compute
            # int8_float16 на Turing и новее даёт вдвое меньше VRAM при том же
            # качестве — на карте с 4 ГБ это разница между «влезло вместе с
            # Ollama» и «не влезло».
            return "int8_float16" if device == "cuda" else "int8"

        if wanted_device == "cpu":
            return [("cpu", compute_for("cpu"))]
        plan = [("cuda", compute_for("cuda"))]
        if wanted_device == "auto":
            plan.append(("cpu", "int8"))
        return plan

    def warmup(self) -> None:
        """Прогоняет секунду шума, чтобы CUDA-ядра скомпилировались заранее."""
        if self._model is None:
            return
        try:
            # Whisper ждёт 16 кГц моно; ровно секунда — достаточно, чтобы
            # прогреть энкодер и декодер, но не задержать старт.
            noise = (np.random.default_rng(0).standard_normal(16_000) * 1e-3).astype(np.float32)
            segments, _ = self._model.transcribe(noise, language=self.cfg.language, beam_size=1)
            for _ in segments:
                pass
        except Exception as exc:
            print(f"[stt] прогрев не удался: {exc}")

    # ---------- распознавание ----------

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None:
            raise RuntimeError("модель Whisper ещё не загружена")

        segments, _info = self._model.transcribe(
            audio,
            language=self.cfg.language or None,
            beam_size=self.cfg.beam_size,
            vad_filter=self.cfg.vad,
            vad_parameters={"min_silence_duration_ms": self.cfg.vad_min_silence_ms},
            # Без этого модель «зацикливается»: предыдущий текст утягивает
            # следующий сегмент в повтор той же фразы.
            condition_on_previous_text=False,
            initial_prompt=self.cfg.initial_prompt or None,
            temperature=0.0,
        )
        text = "".join(segment.text for segment in segments).strip()
        return "" if _is_hallucination(text) else text


def _is_hallucination(text: str) -> bool:
    stripped = text.strip()
    if not stripped or _PUNCT_ONLY.match(stripped):
        return True
    lowered = stripped.lower().strip(" .,!?…-–—\"'«»")
    return any(lowered.startswith(phrase) for phrase in _HALLUCINATIONS) and len(lowered) < 60
