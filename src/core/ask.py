"""«Спросить Дарви»: вопрос голосом — ответ модели, который в текст не вставляется.

Отличие от диктовки одно, но принципиальное: текст Whisper здесь не результат, а
вход для модели, и ответ идёт человеку, а не в активное окно. Поэтому и своя
клавиша: догадываться, вопрос это к Дарви или вопрос, надиктованный в чат, мы не
беремся — ошибка в ту сторону стоит вставленного текста.

Разговор живёт, пока на него отвечают: вопрос, заданный в пределах
ask.followup_s после ответа, — уточнение в том же разговоре, позже — новый
разговор. Когда появится карточка, границей станет её закрытие.

Ответы — только облаком. Какой сервер и какая модель, решает замер
(src/ask_eval.py), поэтому здесь нет ничего, привязанного к Groq.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from config import AskConfig, app_data_dir
from core.audio import to_wav
from core.journal import new_id

if TYPE_CHECKING:
    from core.cloud import CloudClient

#: Сколько символов прошлого разговора отдавать Whisper подсказкой. Его
#: предел — 224 токена, русский режется примерно по 2.9 символа на токен
#: (замер на токенизаторе large-v3-turbo, 6.10.2026). 400 символов — около
#: 140 токенов: с запасом, потому что слишком длинную подсказку облако
#: отбивает, и клиент перестаёт слать подсказки вовсе.
_HINT_CHARS = 400

#: Разметка ответа, которая Whisper ничего не подскажет, а место съест.
_MARKUP = re.compile(r"[`*_$#>|]+")


@dataclass
class Answer:
    """Ответ модели вместе с тем, что о нём стоит знать журналу."""

    text: str
    model: str
    effort: str
    first_s: float = 0.0
    """От запроса до первого слова ответа — столько карточка будет пустой."""

    took_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    truncated: bool = False
    """Упёрлись в max_tokens: ответ оборван, и это видно только здесь."""


class AskFailed(RuntimeError):
    """Облако не ответило на вопрос. Откатываться некуда: Ollama держит
    маленькую модель для правки, а не для ответов."""


@dataclass
class Turn:
    question: str
    answer: str


@dataclass
class Conversation:
    id: str = field(default_factory=new_id)
    turns: list[Turn] = field(default_factory=list)
    last_at: float = 0.0
    """Когда пришёл последний ответ: от него считается окно уточнения."""


class Asker:
    """Держит разговор и собирает запрос к модели. Живёт в потоке конвейера."""

    def __init__(self, cfg: AskConfig, cloud: CloudClient) -> None:
        self.cfg = cfg
        self._cloud = cloud
        self._current: Conversation | None = None
        self._audio_dir = app_data_dir() / "asks"

    @property
    def configured(self) -> bool:
        return self._cloud.can_ask

    def conversation(self) -> Conversation:
        """Текущий разговор, если уточнение пришло вовремя, иначе новый."""
        current = self._current
        if current is None or not current.turns or time.monotonic() - current.last_at > self.cfg.followup_s:
            current = self._current = Conversation()
        return current

    def close(self) -> None:
        """Разговор окончен: следующий вопрос начнёт новый, даже если ответ свежий."""
        self._current = None

    def whisper_hint(self, conversation: Conversation) -> str:
        """Подсказка Whisper для уточнения: прошлый вопрос и начало ответа.

        Начало, а не хвост: первым предложением модель называет суть, и там
        стоят термины, которые человек скорее всего повторит. Пусто — если
        уточнять нечего или подсказка выключена.
        """
        if not self.cfg.context_hint or not conversation.turns:
            return ""
        last = conversation.turns[-1]
        text = _MARKUP.sub("", f"{last.question} {last.answer}")
        text = " ".join(text.split())
        if len(text) <= _HINT_CHARS:
            return text
        return text[:_HINT_CHARS].rsplit(" ", 1)[0]

    def messages(self, question: str, conversation: Conversation) -> list[dict]:
        messages = [{"role": "system", "content": self.cfg.system_prompt}]
        for turn in conversation.turns[-self.cfg.history_turns:]:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer})
        messages.append({"role": "user", "content": question})
        return messages

    def ask(
        self,
        question: str,
        conversation: Conversation,
        on_delta: Callable[[str], None] | None = None,
    ) -> Answer:
        answer = self._cloud.ask(
            self.messages(question, conversation),
            self.cfg.model,
            self.cfg.reasoning_effort,
            self.cfg.max_tokens,
            on_delta,
        )
        conversation.turns.append(Turn(question, answer.text))
        conversation.last_at = time.monotonic()
        return answer

    def keep_audio(self, audio: np.ndarray, sample_rate: int, name: str) -> str:
        """Сохраняет запись вопроса; возвращает имя файла или пусто.

        Сбой записи не должен стоить вопроса — как и сбой журнала.
        """
        if not self.cfg.keep_audio:
            return ""
        try:
            self._audio_dir.mkdir(parents=True, exist_ok=True)
            path = self._audio_dir / f"{name}.wav"
            path.write_bytes(to_wav(audio, sample_rate))
            self._prune()
        except OSError as exc:
            print(f"[ask] не удалось сохранить запись: {exc}")
            return ""
        return path.name

    def _prune(self) -> None:
        files = sorted(self._audio_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for path in files[: max(0, len(files) - self.cfg.keep_audio_max)]:
            path.unlink(missing_ok=True)
