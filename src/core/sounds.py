"""Звуковые сигналы состояний.

winsound.Beep блокирует поток на всю длительность сигнала — 150 мс паузы ровно
в момент нажатия горячей клавиши, из-за чего срезается начало фразы.

Здесь волны синтезируются один раз и лежат готовыми WAV-файлами: winsound
разрешает асинхронное воспроизведение только из файла (SND_MEMORY с SND_ASYNC
он отвергает, а синхронные вызовы из разных потоков конфликтуют между собой).
Побочная польза — файлы можно заменить своими.
"""

from __future__ import annotations

import math
import sys
import wave
from pathlib import Path

from config import app_data_dir

if sys.platform == "win32":
    import winsound
else:
    winsound = None

import shutil
import subprocess

#: Проигрыватель для систем без winsound: на macOS afplay есть всегда, на
#: Linux — что найдётся из aplay/paplay. Пусто — звуков не будет.
_PLAYER: list[str] | None = None
if sys.platform == "darwin":
    _PLAYER = ["afplay"]
elif sys.platform != "win32":
    for candidate in (["paplay"], ["aplay", "-q"]):
        if shutil.which(candidate[0]):
            _PLAYER = candidate
            break

SAMPLE_RATE = 44_100
_MAX_AMPLITUDE = 32_767


def _glide(
    f_start: float,
    f_end: float,
    duration_ms: int,
    *,
    decay: float = 4.0,
    harmonic: float = 0.0,
) -> list[float]:
    """Тон с плавным изменением частоты и экспоненциальным затуханием.

    Частота меняется, поэтому фазу приходится накапливать интегрированием:
    подстановка текущей частоты в sin(2*pi*f*t) дала бы разрывы и щелчки.
    """
    total = max(1, int(SAMPLE_RATE * duration_ms / 1000))
    attack = max(1, int(SAMPLE_RATE * 0.006))
    release = max(1, int(SAMPLE_RATE * 0.010))

    samples: list[float] = []
    phase = 0.0
    for index in range(total):
        position = index / total
        frequency = f_start + (f_end - f_start) * position
        phase += 2 * math.pi * frequency / SAMPLE_RATE

        value = math.sin(phase)
        if harmonic:
            value = (value + harmonic * math.sin(2 * phase)) / (1.0 + harmonic)

        envelope = math.exp(-decay * position)
        if index < attack:
            envelope *= index / attack
        if index > total - release:
            envelope *= (total - index) / release
        samples.append(value * envelope)
    return samples


def _silence(duration_ms: int) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * duration_ms / 1000)


def _recipes() -> dict[str, list[float]]:
    return {
        # Восходящий — «слушаю».
        "start": _glide(620, 940, 110, decay=3.0),
        # Нисходящий — «записал, работаю».
        "stop": _glide(900, 620, 95, decay=3.5),
        # Квинта вверх — «готово».
        "success": _glide(880, 880, 70, decay=5.0) + _glide(1318, 1318, 150, decay=4.0),
        # Низкий с обертоном — «что-то не так».
        "error": _glide(230, 190, 230, decay=2.5, harmonic=0.35),
        # Нейтральный щелчок — «отменено».
        "cancel": _glide(520, 430, 70, decay=6.0),
        # Мягкий двойной — «модель загрузилась, можно работать».
        "ready": _glide(700, 700, 60, decay=6.0)
        + _silence(25)
        + _glide(1050, 1050, 110, decay=4.5),
    }


def _write_wav(path: Path, samples: list[float], volume: float) -> None:
    gain = max(0.0, min(1.0, volume)) * _MAX_AMPLITUDE
    frames = bytearray()
    for value in samples:
        clipped = max(-1.0, min(1.0, value))
        frames += int(clipped * gain).to_bytes(2, "little", signed=True)

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(bytes(frames))


class SoundBoard:
    """Готовые сигналы на диске плюс мгновенное асинхронное воспроизведение."""

    def __init__(self, enabled: bool = True, volume: float = 0.35) -> None:
        self.enabled = enabled and (winsound is not None or _PLAYER is not None)
        self._volume = max(0.0, min(1.0, volume))
        self._dir = app_data_dir() / "sounds"
        self._paths: dict[str, Path] = {}
        self._ensure_files()

    def _ensure_files(self) -> None:
        """Пересобирает файлы, только если их нет или изменилась громкость."""
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            marker = self._dir / "volume.txt"
            stored = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""
            current = f"{self._volume:.3f}"

            self._paths = {name: self._dir / f"{name}.wav" for name in _recipes()}
            if stored == current and all(path.exists() for path in self._paths.values()):
                return

            for name, samples in _recipes().items():
                _write_wav(self._paths[name], samples, self._volume)
            marker.write_text(current, encoding="utf-8")
        except OSError as exc:
            print(f"[sounds] не удалось подготовить сигналы: {exc}")
            self._paths = {}

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))
        self._ensure_files()

    def play(self, name: str) -> None:
        """Ставит сигнал в очередь звуковой карты и сразу возвращает управление."""
        if not self.enabled:
            return
        path = self._paths.get(name)
        if path is None or not path.exists():
            return
        try:
            if winsound is not None:
                winsound.PlaySound(
                    str(path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
                )
            elif _PLAYER is not None:
                subprocess.Popen(
                    _PLAYER + [str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except Exception as exc:  # звук не критичен, глушим любые сбои устройства
            print(f"[sounds] не удалось проиграть {name}: {exc}")
