"""«Спросить Дарви»: вопрос голосом — ответ модели, который в текст не вставляется.

Отличие от диктовки одно, но принципиальное: текст Whisper здесь не результат, а
вход для модели, и ответ идёт человеку, а не в активное окно. Поэтому и своя
клавиша: догадываться, вопрос это к Дарви или вопрос, надиктованный в чат, мы не
беремся — ошибка в ту сторону стоит вставленного текста.

Разговор живёт, пока открыта карточка с ним: вопрос при открытой карточке —
уточнение, сколько бы ни прошло после ответа, а крестик разговор заканчивает.
Если карточку убрала начатая диктовка, уточнением считается вопрос в пределах
ask.followup_s после ответа, позже — новый разговор.

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

#: Ссылки встроенного поиска gpt-oss: «【2†L14-L17】». Номер — курсор браузера
#: модели, а не порядковый номер источника, человеку он ничего не скажет.
#: Вторая ветка — недописанная ссылка в хвосте потока.
_CITATION = re.compile(r"\s?【[^】]*】|【[^】]*$")


def clean_answer(text: str) -> str:
    """Текст ответа без служебных ссылок поиска — для карточки и журнала."""
    return _CITATION.sub("", text).strip()


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

    searched: bool = False
    """Модель искала в интернете перед ответом."""

    opened: list[str] = field(default_factory=list)
    """Страницы, которые модель открыла и прочла."""

    found: list[str] = field(default_factory=list)
    """Выдача поиска: из неё модель отвечает, если ничего не открывала."""

    @property
    def sources(self) -> list[str]:
        """Источники для карточки и журнала: прочитанное, а без него — верх выдачи."""
        return self.opened or self.found[:3]


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

    def conversation(self, keep: bool = False) -> Conversation:
        """Текущий разговор, если вопрос его продолжает, иначе новый.

        keep — карточка с разговором открыта: продолжаем его, сколько бы ни
        прошло после ответа. Без неё уточнение — только в пределах followup_s.
        """
        current = self._current
        stale = current is not None and time.monotonic() - current.last_at > self.cfg.followup_s
        if current is None or not current.turns or (stale and not keep):
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
        system = self.cfg.system_prompt
        if self.cfg.about.strip():
            system += (
                f"- О человеке: {self.cfg.about.strip()}. Если ответ про код и настройки — "
                "давай их для этих версий, не упоминая их без нужды.\n"
            )
        messages = [{"role": "system", "content": system}]
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
        search: bool | None = None,
    ) -> Answer:
        """search — искать ли в интернете; None — как в настройках (ask.web_search)."""
        messages = self.messages(question, conversation)

        def ask(search: bool) -> Answer:
            return self._cloud.ask(
                messages, self.cfg.model, self.cfg.reasoning_effort, self.cfg.max_tokens, on_delta, search,
            )

        wanted = self.cfg.web_search if search is None else search
        try:
            answer = ask(wanted)
        except AskFailed as exc:
            # Лучше ответ без поиска, чем никакого. Поиск съедает тысячи токенов
            # на вопрос, и лимит кончается у него первым; а при обязательном
            # поиске модель иной раз отказывается искать — «Tool choice is
            # required, but model did not call a tool» шесть раз подряд на одном
            # вопросе 7.10. Сбой сети повтор без поиска не вылечит. Если искать
            # попросил сам человек, ответ без поиска ему не нужен — он уже есть.
            failed_search = "лимит" in str(exc) or "tool" in str(exc).lower()
            if not wanted or search is not None or not failed_search:
                raise
            print(f"[ask] {exc}; отвечаю без поиска")
            answer = ask(False)
        conversation.turns.append(Turn(question, answer.text))
        conversation.last_at = time.monotonic()
        return answer

    def recheck(self, on_delta: Callable[[str], None] | None = None) -> tuple[Conversation, str, Answer]:
        """Задаёт последний вопрос заново, но с поиском, — «Проверить в интернете».

        Ответ заменяет прежний в разговоре: уточнение дальше должно опираться
        на проверенное, а не на то, что модель вспомнила сама.
        """
        conversation = self._current
        if conversation is None or not conversation.turns:
            raise AskFailed("перепроверять нечего: разговор закончен")
        turn = conversation.turns.pop()
        try:
            answer = self.ask(turn.question, conversation, on_delta, search=True)
        except AskFailed:
            conversation.turns.append(turn)
            raise
        return conversation, turn.question, answer

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
