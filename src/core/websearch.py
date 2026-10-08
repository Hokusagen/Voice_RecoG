"""Поиск в интернете для ответов Дарви: Tavily вместо встроенного поиска Groq.

Встроенный browser_search у gpt-oss на Groq открывает страницы целиком, и
каждый следующий его шаг заново читает всё накопленное: одна перепроверка
8.10.2026 съела 147.7 тыс. входных токенов из суточных 200 тыс. Здесь ищем
сами: один-два запроса, по четыре результата с фрагментами страниц, и модель
отвечает по ним одним вызовом — около 2.4 тыс. токенов на перепроверку,
первое слово через ~3 с (замер на 39 вопросах, 9.10.2026).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import requests

URL = "https://api.tavily.com/search"

PER_QUERY = 4
"""Результатов на запрос; запросов один-два, всего до восьми."""

TEXT_CHARS = 1500
"""Потолок текста одного результата — три фрагмента basic по ~500 символов.
Восемь результатов — около 3.5 тыс. токенов, на замере медиана была 1.3 тыс."""


@dataclass
class Found:
    """Один результат поиска — то, что увидит модель."""

    title: str
    url: str
    text: str


class SearchFailed(RuntimeError):
    """Поиск не ответил. Текст — для карточки."""


class WebSearch:
    def __init__(self, key: str, depth: str = "basic", timeout_s: float = 10.0) -> None:
        self.key = key.strip()
        self.depth = depth
        self.timeout_s = timeout_s
        self._session = requests.Session()

    def search(self, queries: list[str]) -> list[Found]:
        """Результаты всех запросов без повторов, в порядке запросов.

        Два запроса идут параллельно: по очереди они стоили бы ещё одного
        поиска, а basic — это 1.7 с в медиане и до 3 с в хвосте.
        """
        if len(queries) == 1:
            batches = [self._one(queries[0])]
        else:
            with ThreadPoolExecutor(len(queries)) as pool:
                batches = list(pool.map(self._one, queries))
        found: list[Found] = []
        seen: set[str] = set()
        for batch in batches:
            for item in batch:
                if item.url and item.url not in seen:
                    seen.add(item.url)
                    found.append(item)
        return found

    def _one(self, query: str) -> list[Found]:
        if not self.key.isascii():
            # Заголовок HTTP пишется в latin-1: кириллица или невидимый символ,
            # попавший в ключ при копировании, уронили бы запрос UnicodeEncodeError.
            raise SearchFailed("в ключе Tavily лишние символы — вставь его заново")
        try:
            response = self._session.post(
                URL,
                headers={"Authorization": f"Bearer {self.key}"},
                json={
                    "query": query,
                    "search_depth": self.depth,
                    "max_results": PER_QUERY,
                    # Своего ответа Tavily не просим: по условиям его генеративные
                    # функции могут учиться на запросах, да и отвечает у нас модель.
                    "include_answer": False,
                },
                timeout=self.timeout_s,
            )
        except requests.Timeout as exc:
            raise SearchFailed("поиск не ответил вовремя") from exc
        except requests.RequestException as exc:
            raise SearchFailed("поиск недоступен: нет сети") from exc
        if response.status_code != 200:
            raise SearchFailed(_error(response))
        try:
            results = response.json().get("results") or []
        except ValueError as exc:
            raise SearchFailed("поиск вернул непонятный ответ") from exc
        # Поля могут отсутствовать: у части результатов Tavily нет даже title.
        return [
            Found(
                title=item.get("title") or "",
                url=item.get("url") or "",
                text=" ".join((item.get("content") or "").split())[:TEXT_CHARS],
            )
            for item in results
            if isinstance(item, dict)
        ]


def _error(response: requests.Response) -> str:
    """Отказ Tavily словами для карточки: какой лимит упёрся, видно только по коду."""
    code = response.status_code
    if code == 401:
        return "поиск не принял ключ Tavily"
    if code == 432:
        # Бесплатные 1000 кредитов в месяц: сброс первого числа, ждать минуту бесполезно.
        return "поиск: кончился месячный запас Tavily"
    if code == 433:
        return "поиск: упёрся в потолок оплаты Tavily"
    if code == 429:
        return "поиск: слишком часто, подожди минуту"
    try:
        detail = response.json().get("detail")
        message = detail.get("error", "") if isinstance(detail, dict) else str(detail or "")
    except (ValueError, AttributeError):
        message = ""
    return f"поиск ответил {code}" + (f": {message[:80]}" if message else "")
