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
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from config import AskConfig, app_data_dir
from core import formulas
from core.audio import AudioArchive
from core.journal import new_id
from core.websearch import Found, SearchFailed, WebSearch

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


#: Номер источника в ответе по своему поиску: «【2】», а по привычке gpt-oss и
#: «【2†L3-L5】». Скобки те же, что у встроенного поиска, — clean_answer их уже
#: вычищает из карточки и журнала, а источники собираются по ним заранее.
_CITED = re.compile(r"【(\d+)")

#: Длиннее запрос поисковику не нужен: Tavily раньше отбивал запросы от 400.
_QUERY_CHARS = 400

#: Сколько от прошлого ответа видит шаг с запросами: в начале ответа суть и
#: термины, а хвост стоил бы токенов на каждый поиск.
_CONTEXT_CHARS = 600

#: Промпт шага, где модель пишет запросы для своего поиска. Короткий нарочно:
#: шаг стоит ~200 токенов и полсекунды. «Без личного» — запрос уходит чужому
#: сервису, а по условиям Tavily сведения о здоровье конкретного человека в
#: запросах запрещены.
QUERY_PROMPT = (
    "Ты составляешь запросы для поиска в интернете по последнему вопросу человека. Вопрос "
    "распознан из речи, в нём бывают ошибки: исправь их по смыслу. Названия, которых не "
    "знаешь, не заменяй похожими знакомыми — оставь как сказано: это может быть что-то новое. "
    "Если вопрос — уточнение, учти разговор выше. Запрос — коротко, ключевыми словами, на "
    "языке, на котором вернее найдётся ответ, и о самом предмете, без личного: не «у меня …». "
    "Если в вопросе две темы — два запроса, иначе один. Выведи только запросы, по одному в строке."
)


def clean_answer(text: str) -> str:
    """Текст ответа без служебных ссылок поиска — для карточки и журнала."""
    return _CITATION.sub("", text).strip()


def parse_queries(text: str) -> list[str]:
    """Запросы из ответа модели: по строке на запрос, не больше двух.

    Хвосты строк чистим: на 39 вопросах 8.10.2026 gpt-oss с раздумьями low
    оставил мусор в конце 9 запросов — нулевой символ (6 раз), BOM,
    «</assistant», лишнюю «>». Ещё бывают пробел нулевой ширины и неразрывный
    дефис U+2011, который поисковик дефисом не считает.
    """
    text = text.replace(chr(0x2011), "-")
    text = "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch) not in ("Cc", "Cf"))
    text = re.sub(r"</?\w*>?\s*$", "", text, flags=re.M)
    queries = []
    for line in text.splitlines():
        # Маркер списка «- » или «1. » срезаем, а цифры в начале самого запроса — нет.
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip("«»\"' >")
        if line:
            queries.append(line[:_QUERY_CHARS])
    return queries[:2]


def _with_results(question: str, found: list[Found]) -> str:
    """Вопрос вместе с найденным.

    Правило ссылок — здесь, а не в системном промпте: промпт лежит у человека
    в config.json, и там может быть старая версия, написанная под встроенный
    поиск. Номера — в тех же скобках, что у него: их уже чистит clean_answer.
    """
    if not found:
        return (
            "Поиск ничего не нашёл. Так и скажи, а ответь по тому, что знаешь сам, "
            f"предупредив, что это без проверки.\n\nВопрос: {question}"
        )
    lines = [f"【{n}】 {item.title} — {item.url}\n{item.text}" for n, item in enumerate(found, 1)]
    return (
        "Результаты поиска:\n\n" + "\n\n".join(lines)
        + "\n\nОтвечай по ним и ставь номер источника в таких же скобках, например 【2】. "
        "Чего в них нет — так и скажи, не придумывай."
        + f"\n\nВопрос: {question}"
    )


def _cited(text: str, found: list[Found]) -> list[str]:
    """Адреса, на которые сослался ответ, в порядке первой ссылки."""
    urls: list[str] = []
    for number in _CITED.findall(text):
        index = int(number) - 1
        if 0 <= index < len(found) and found[index].url not in urls:
            urls.append(found[index].url)
    return urls


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

    queries: list[str] = field(default_factory=list)
    """Что модель искала: запросы пишет она сама, по вопросу и разговору."""

    opened: list[str] = field(default_factory=list)
    """Страницы, которые модель открыла и прочла."""

    found: list[str] = field(default_factory=list)
    """Выдача поиска: из неё модель отвечает, если ничего не открывала."""

    cited: list[str] = field(default_factory=list)
    """Страницы, на которые сослался ответ по своему поиску."""

    @property
    def sources(self) -> list[str]:
        """Источники для карточки и журнала: на что сослался ответ, что прочла
        модель, а без того и другого — верх выдачи."""
        return self.cited or self.opened or self.found[:3]


class AskFailed(RuntimeError):
    """Облако не ответило на вопрос. Откатываться некуда: Ollama держит
    маленькую модель для правки, а не для ответов."""

    def __init__(self, message: str, search: bool = False) -> None:
        super().__init__(message)
        self.search = search
        """Отказал свой поиск, а не модель: ответить можно и без него."""


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
        self._archive = AudioArchive(app_data_dir() / "asks", max_files=cfg.keep_audio_max)
        self._search = WebSearch(cfg.search_key, cfg.search_depth) if cfg.search_key.strip() else None
        """Свой поиск (Tavily); без ключа ищет встроенный поиск gpt-oss у Groq."""

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
        # Формулы — плоским текстом: «\frac{1}{1+e^{-x}}» Whisper ничего не подскажет.
        text = _MARKUP.sub("", f"{last.question} {formulas.to_plain(last.answer)}")
        text = " ".join(text.split())
        if len(text) <= _HINT_CHARS:
            return text
        return text[:_HINT_CHARS].rsplit(" ", 1)[0]

    def messages(
        self, question: str, conversation: Conversation, found: list[Found] | None = None,
    ) -> list[dict]:
        """found — выдача своего поиска: она ложится в вопрос, ответ пишется по ней."""
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
        content = question if found is None else _with_results(question, found)
        messages.append({"role": "user", "content": content})
        return messages

    def ask(
        self,
        question: str,
        conversation: Conversation,
        on_delta: Callable[[str], None] | None = None,
        search: bool | None = None,
        on_search: Callable[[str], None] | None = None,
    ) -> Answer:
        """search — искать ли в интернете; None — как в настройках (ask.web_search).
        on_search получает каждый новый запрос модели к поиску, пока она ищет."""
        wanted = self.cfg.web_search if search is None else search
        try:
            answer = self._answer(question, conversation, on_delta, wanted, on_search)
        except AskFailed as exc:
            # Лучше ответ без поиска, чем никакого. Встроенный поиск съедает
            # тысячи токенов на вопрос, и лимит кончается у него первым; а при
            # обязательном поиске модель иной раз отказывается искать — «Tool
            # choice is required, but model did not call a tool» шесть раз подряд
            # на одном вопросе 7.10. Свой поиск отказывает по своим причинам:
            # кончился месячный запас Tavily, не ответил сервер. Сбой сети у
            # модели повтор без поиска не вылечит. Если искать попросил сам
            # человек, ответ без поиска ему не нужен — он уже есть.
            failed_search = exc.search or "лимит" in str(exc) or "tool" in str(exc).lower()
            if not wanted or search is not None or not failed_search:
                raise
            print(f"[ask] {exc}; отвечаю без поиска")
            answer = self._answer(question, conversation, on_delta, False, on_search)
        conversation.turns.append(Turn(question, answer.text))
        conversation.last_at = time.monotonic()
        return answer

    def _answer(
        self,
        question: str,
        conversation: Conversation,
        on_delta: Callable[[str], None] | None,
        search: bool,
        on_search: Callable[[str], None] | None,
    ) -> Answer:
        if search and self._search is not None:
            return self._answer_found(question, conversation, on_delta, on_search)
        return self._cloud.ask(
            self.messages(question, conversation), self.cfg.model, self.cfg.reasoning_effort,
            self.cfg.max_tokens, on_delta, search, on_search,
        )

    def _answer_found(
        self,
        question: str,
        conversation: Conversation,
        on_delta: Callable[[str], None] | None,
        on_search: Callable[[str], None] | None,
    ) -> Answer:
        """Свой поиск: модель пишет запросы, Tavily ищет, модель отвечает по найденному.

        Три шага вместо одного, но каждый короткий: запросы — полсекунды и
        ~200 токенов, поиск basic — 1.7 с в медиане, а ответ читает только
        фрагменты страниц. У встроенного browser_search один вызов внутри
        делает дюжину шагов и перечитывает целые страницы на каждом.
        """
        started = time.monotonic()
        effort = "low" if self.cfg.reasoning_effort else ""
        draft = self._cloud.ask(self._query_messages(question, conversation), self.cfg.model, effort, 400)
        queries = parse_queries(draft.text) or [question[:_QUERY_CHARS]]
        if on_search is not None:
            for query in queries:
                on_search(query)
        try:
            found = self._search.search(queries)
        except SearchFailed as exc:
            raise AskFailed(str(exc), search=True) from exc

        pieces: list[str] = []

        def collect(piece: str) -> None:
            # Номера источников из текста вычистит clean_answer, поэтому ловим их по пути.
            pieces.append(piece)
            if on_delta is not None:
                on_delta(piece)

        searched = time.monotonic() - started
        answer = self._cloud.ask(
            self.messages(question, conversation, found), self.cfg.model, self.cfg.reasoning_effort,
            self.cfg.max_tokens, collect,
        )
        answer.searched = True
        answer.queries = queries
        answer.found = [item.url for item in found]
        answer.cited = _cited("".join(pieces), found)
        # В журнал — цена и время всей перепроверки, а не одного последнего шага.
        answer.prompt_tokens += draft.prompt_tokens
        answer.completion_tokens += draft.completion_tokens
        answer.reasoning_tokens += draft.reasoning_tokens
        answer.first_s += searched
        answer.took_s += searched
        return answer

    def _query_messages(self, question: str, conversation: Conversation) -> list[dict]:
        """Шаг с запросами видит конец разговора: уточнению без него не из чего понять тему."""
        messages = [{"role": "system", "content": QUERY_PROMPT}]
        for turn in conversation.turns[-2:]:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer[:_CONTEXT_CHARS]})
        messages.append({"role": "user", "content": question})
        return messages

    def recheck(
        self,
        on_delta: Callable[[str], None] | None = None,
        on_search: Callable[[str], None] | None = None,
    ) -> tuple[Conversation, str, Answer]:
        """Задаёт последний вопрос заново, но с поиском, — «Проверить в интернете».

        Ответ заменяет прежний в разговоре: уточнение дальше должно опираться
        на проверенное, а не на то, что модель вспомнила сама.
        """
        conversation = self._current
        if conversation is None or not conversation.turns:
            raise AskFailed("перепроверять нечего: разговор закончен")
        turn = conversation.turns.pop()
        try:
            answer = self.ask(turn.question, conversation, on_delta, search=True, on_search=on_search)
        except AskFailed:
            conversation.turns.append(turn)
            raise
        return conversation, turn.question, answer

    def keep_audio(self, audio: np.ndarray, sample_rate: int, name: str) -> str:
        """Сохраняет запись вопроса; возвращает имя файла или пусто."""
        if not self.cfg.keep_audio:
            return ""
        return self._archive.keep(audio, sample_rate, name)
