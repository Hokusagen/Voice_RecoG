"""Состояния приложения — общий словарь для конвейера, HUD и трея."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class Stage(Enum):
    """Что приложение делает прямо сейчас."""

    IDLE = auto()
    """Ничего не происходит, HUD спрятан."""

    LOADING = auto()
    """Грузим Whisper в память (единственный долгий шаг на старте)."""

    LISTENING = auto()
    """Микрофон открыт, пишем речь."""

    TRANSCRIBING = auto()
    """Whisper переводит звук в текст."""

    POLISHING = auto()
    """Ollama чистит транскрипт."""

    DONE = auto()
    """Текст вставлен в активное окно."""

    WARNING = auto()
    """Отработали, но не полностью: LLM недоступна, тишина в записи и т.п."""

    ERROR = auto()
    """Шаг провалился, вставлять нечего."""

    CANCELLED = auto()
    """Пользователь прервал запись."""

    PAUSED = auto()
    """Горячие клавиши отключены из трея."""


#: Стадии, на которых конвейер занят и новую запись начинать нельзя.
BUSY_STAGES = frozenset({Stage.TRANSCRIBING, Stage.POLISHING})

#: Стадии, после которых HUD сам уезжает через таймаут.
TRANSIENT_STAGES = frozenset(
    {Stage.DONE, Stage.WARNING, Stage.ERROR, Stage.CANCELLED, Stage.PAUSED}
)


@dataclass(frozen=True)
class Status:
    """Снимок состояния для отрисовки.

    Конвейер шлёт такие объекты в UI через очередь сигналов Qt, поэтому
    структура неизменяемая: её читают из другого потока, чем создают.
    """

    stage: Stage
    title: str = ""
    detail: str = ""
    progress: float | None = None
    """0..1 для определённого прогресса, None — бесконечная анимация."""

    @property
    def is_transient(self) -> bool:
        return self.stage in TRANSIENT_STAGES
