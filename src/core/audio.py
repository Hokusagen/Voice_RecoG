"""Захват звука с микрофона.

Три отличия от наивного варианта:

* поток открывается по требованию и закрывается после простоя — иначе Windows
  всё время показывает индикатор «микрофон используется»;
* кольцевой буфер хранит последние полсекунды звука до нажатия клавиши, чтобы
  не срезалось начало фразы;
* уровень сигнала считается прямо в аудио-колбэке и выставляется в атомарное
  поле, которое UI опрашивает, — так анимация эквалайзера показывает реальную
  громкость, а аудио-поток не блокируется на отрисовке.
"""

from __future__ import annotations

import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

from config import AudioConfig


class AudioError(RuntimeError):
    """Микрофон недоступен."""


class AudioRecorder:
    def __init__(self, cfg: AudioConfig) -> None:
        self.cfg = cfg
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

        block_frames = max(1, int(cfg.sample_rate * cfg.block_ms / 1000))
        preroll_blocks = max(1, round(cfg.preroll_ms / cfg.block_ms))
        self._block_frames = block_frames
        self._ring: deque[np.ndarray] = deque(maxlen=preroll_blocks)

        self._captured: list[np.ndarray] = []
        self._preroll: list[np.ndarray] = []
        self._capturing = False

        self._level = 0.0
        self._peak = 0.0
        self._started_at = 0.0
        self._last_used = time.monotonic()
        self._overflows = 0

    # ---------- жизненный цикл потока ----------

    def ensure_open(self) -> None:
        """Открывает поток, если он закрыт. Идемпотентно."""
        with self._lock:
            if self._stream is not None:
                return
            try:
                stream = sd.InputStream(
                    samplerate=self.cfg.sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=self._block_frames,
                    device=self.cfg.device,
                    callback=self._on_block,
                )
                stream.start()
            except Exception as exc:
                raise AudioError(f"не удалось открыть микрофон: {exc}") from exc
            self._stream = stream
            self._ring.clear()
        self._last_used = time.monotonic()

    def close(self) -> None:
        with self._lock:
            stream, self._stream = self._stream, None
            self._capturing = False
            self._ring.clear()
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception as exc:
                print(f"[audio] ошибка при закрытии потока: {exc}")
        self._level = 0.0

    def close_if_idle(self) -> bool:
        """Закрывает микрофон после простоя. Возвращает True, если закрыла."""
        if self.cfg.idle_close_s <= 0 or self._stream is None or self._capturing:
            return False
        if time.monotonic() - self._last_used < self.cfg.idle_close_s:
            return False
        self.close()
        return True

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    # ---------- аудио-колбэк ----------

    def _on_block(self, indata, frames, time_info, status) -> None:
        """Вызывается потоком PortAudio. Ничего тяжёлого здесь делать нельзя."""
        if status:
            self._overflows += 1

        block = indata.copy().reshape(-1)
        self._ring.append(block)

        # float32 из PortAudio уже в диапазоне -1..1, так что RMS сразу пригоден
        # как громкость. Копейки по времени, зато UI получает честные данные.
        rms = float(np.sqrt(np.mean(np.square(block))))
        self._level = rms

        if self._capturing:
            if rms > self._peak:
                self._peak = rms
            # list.append атомарен под GIL — блокировка в realtime-колбэке
            # была бы куда опаснее, чем гонка на последнем блоке.
            self._captured.append(block)

    # ---------- запись ----------

    def start_capture(self) -> None:
        self.ensure_open()
        # Порядок важен: сначала снимок пре-ролла, потом пустой список, и только
        # затем флаг. Иначе колбэк успеет дописать блок в старый список.
        self._preroll = list(self._ring)
        self._captured = []
        self._peak = 0.0
        self._overflows = 0
        self._capturing = True
        self._started_at = time.monotonic()
        self._last_used = self._started_at

    def stop_capture(self) -> np.ndarray | None:
        """Останавливает запись и отдаёт склеенный моно-сигнал."""
        if not self._capturing:
            return None
        self._capturing = False
        self._last_used = time.monotonic()

        blocks = self._preroll + self._captured
        self._preroll = []
        self._captured = []
        if not blocks:
            return None
        if self._overflows:
            print(f"[audio] пропущено блоков из-за перегрузки буфера: {self._overflows}")
        return np.concatenate(blocks).astype(np.float32, copy=False)

    def cancel_capture(self) -> None:
        self._capturing = False
        self._preroll = []
        self._captured = []
        self._last_used = time.monotonic()

    # ---------- телеметрия для UI ----------

    @property
    def is_capturing(self) -> bool:
        return self._capturing

    @property
    def level(self) -> float:
        """Мгновенный RMS последнего блока, 0..~1."""
        return self._level

    @property
    def peak(self) -> float:
        """Максимальный RMS за текущую запись — по нему судим о тишине."""
        return self._peak

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started_at if self._capturing else 0.0

    def duration_of(self, audio: np.ndarray) -> float:
        return len(audio) / float(self.cfg.sample_rate)

    def is_silent(self) -> bool:
        return self._peak < self.cfg.silence_rms
