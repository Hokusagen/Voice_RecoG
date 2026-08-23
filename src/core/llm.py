"""Постобработка транскрипта локальной моделью через Ollama."""

from __future__ import annotations

import re
import time

import requests

from config import LLMConfig

#: Вступления, которыми модель иногда обрамляет ответ вопреки инструкции.
_PREAMBLES = (
    "cleaned output text:",
    "cleaned text:",
    "output:",
    "исправленный текст:",
    "вот исправленный текст:",
    "вот результат:",
    "результат:",
    "чистовик:",
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_WORD = re.compile(r"\w+", re.UNICODE)


class LLMUnavailable(RuntimeError):
    """Ollama не отвечает — работаем на сыром тексте Whisper."""


class OllamaClient:
    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        # Сессия переиспользует TCP-соединение: на каждой диктовке экономит
        # рукопожатие, а их тут по одному на фразу.
        self._session = requests.Session()
        self.last_error: str | None = None

    @property
    def _base(self) -> str:
        return self.cfg.url.rstrip("/")

    # ---------- доступность и прогрев ----------

    def is_available(self, timeout: float = 2.0) -> bool:
        try:
            response = self._session.get(f"{self._base}/api/tags", timeout=timeout)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def warmup(self) -> bool:
        """Прогревает Ollama настоящим промптом.

        Загрузить веса мало: системная часть промпта занимает несколько сотен
        токенов, и первый запрос уходил на её обсчёт — замерено 8.8 секунды
        против 0.8 у следующих. Прогоняем ровно тот же префикс с коротким
        входом, и его KV-кэш остаётся готовым к первой настоящей диктовке.
        """
        try:
            response = self._session.post(
                f"{self._base}/api/generate",
                json={
                    "model": self.cfg.model,
                    "prompt": self._build_prompt("Ну это самое, проверка связи."),
                    "stream": False,
                    "keep_alive": self.cfg.keep_alive,
                    "options": {
                        "temperature": self.cfg.temperature,
                        "num_predict": 8,
                        "num_ctx": self.cfg.num_ctx,
                    },
                },
                timeout=max(60.0, self.cfg.timeout_s),
            )
            ok = response.status_code == 200
            if not ok:
                self.last_error = f"Ollama ответила {response.status_code}"
            return ok
        except requests.RequestException as exc:
            self.last_error = _describe(exc)
            print(f"[llm] прогрев не удался: {self.last_error}")
            return False

    # ---------- основная работа ----------

    def should_skip(self, raw_text: str) -> bool:
        """Короткие реплики не стоят похода в модель."""
        if not self.cfg.enabled:
            return True
        return len(_WORD.findall(raw_text)) < self.cfg.min_words

    def polish(self, raw_text: str) -> str:
        """Возвращает вычищенный текст. Бросает LLMUnavailable при сбое."""
        prompt = self._build_prompt(raw_text)
        payload = {
            "model": self.cfg.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.cfg.keep_alive,
            "options": {
                "temperature": self.cfg.temperature,
                # Ответ не бывает длиннее входа больше чем в полтора раза:
                # ограничение экономит время и не даёт модели уйти в рассуждения.
                "num_predict": min(512, max(64, len(raw_text) // 2 + 32)),
                "num_ctx": self.cfg.num_ctx,
            },
        }

        started = time.monotonic()
        try:
            response = self._session.post(
                f"{self._base}/api/generate", json=payload, timeout=self.cfg.timeout_s
            )
        except requests.RequestException as exc:
            self.last_error = _describe(exc)
            raise LLMUnavailable(self.last_error) from exc

        if response.status_code != 200:
            self.last_error = f"Ollama ответила {response.status_code}"
            raise LLMUnavailable(self.last_error)

        try:
            result = response.json().get("response", "")
        except ValueError as exc:
            self.last_error = "Ollama вернула некорректный JSON"
            raise LLMUnavailable(self.last_error) from exc

        cleaned = _sanitize(result)
        took = time.monotonic() - started
        print(f"[llm] за {took:.1f} с: «{cleaned}»")

        if not _looks_sane(cleaned, raw_text):
            self.last_error = "модель ответила не по делу"
            raise LLMUnavailable(self.last_error)

        self.last_error = None
        return cleaned

    def _build_prompt(self, raw_text: str) -> str:
        # Системная часть неизменна от запроса к запросу, поэтому Ollama
        # переиспользует её KV-кэш и обсчитывает заново только сам транскрипт.
        return (
            f"{self.cfg.system_prompt}\n\n"
            f'Input text:\n"{raw_text}"\n\n'
            f"Cleaned output text:"
        )


def _sanitize(text: str) -> str:
    """Снимает обёртки, которыми модель любит украшать ответ."""
    text = _THINK_BLOCK.sub("", text).strip()

    lowered = text.lower()
    for preamble in _PREAMBLES:
        if lowered.startswith(preamble):
            text = text[len(preamble) :].strip()
            break

    if len(text) >= 2 and text[0] in "\"'«“" and text[-1] in "\"'»”":
        text = text[1:-1].strip()

    return text.strip()


def _looks_sane(cleaned: str, raw_text: str) -> bool:
    """Отсекает случаи, когда модель ответила на текст вместо его чистки."""
    if not cleaned:
        return False
    raw_words = len(_WORD.findall(raw_text))
    clean_words = len(_WORD.findall(cleaned))
    if raw_words == 0:
        return False
    # Чистка убирает слова, а не добавляет: рост больше чем в два раза почти
    # всегда означает, что модель начала отвечать на реплику.
    return clean_words <= max(8, raw_words * 2)


def _describe(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "Ollama не запущена"
    if isinstance(exc, requests.Timeout):
        return "Ollama не ответила вовремя"
    return str(exc)
