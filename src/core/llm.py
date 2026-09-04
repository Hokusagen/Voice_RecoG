"""Постобработка транскрипта локальной моделью через Ollama."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

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
    "выход:",
    "вход:",
)

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Polished:
    """Правка вместе с тем, что о ней стоит знать журналу."""

    text: str
    response: str
    """Ответ до снятия обёрток: по нему видно, что модель приписала от себя."""

    took_s: float
    output_tokens: int = 0
    gen_s: float = 0.0
    """Время самой генерации — по нему считаются ток/с, не завися от очереди."""

    accepted: bool = True


class LLMUnavailable(RuntimeError):
    """Ollama не отвечает или ответила не по делу — работаем на сыром Whisper."""

    def __init__(self, message: str, polished: Polished | None = None) -> None:
        super().__init__(message)
        self.polished = polished
        """Отклонённый ответ, если он был: журналу нужен и он."""


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
                    "prompt": self._build_prompt("Ну это самое, проверка связи.", self.cfg.style),
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

    def unload(self) -> bool:
        """Просит Ollama выгрузить модель прямо сейчас.

        keep_alive=0 в пустом запросе освобождает видеопамять мгновенно, не
        дожидаясь таймаута из настроек; сама Ollama при этом продолжает жить.
        """
        try:
            response = self._session.post(
                f"{self._base}/api/generate",
                json={"model": self.cfg.model, "keep_alive": 0},
                timeout=10.0,
            )
            return response.status_code == 200
        except requests.RequestException as exc:
            self.last_error = _describe(exc)
            print(f"[llm] выгрузка не удалась: {self.last_error}")
            return False

    # ---------- основная работа ----------

    def skip_reason(self, raw_text: str) -> str:
        """Почему правку пропускаем. Пустая строка — не пропускаем."""
        if not self.cfg.enabled:
            return "правка выключена"
        if len(_WORD.findall(raw_text)) < self.cfg.min_words:
            return f"короче {self.cfg.min_words} слов"
        return ""

    def should_skip(self, raw_text: str) -> bool:
        """Короткие реплики не стоят похода в модель."""
        return bool(self.skip_reason(raw_text))

    def polish(self, raw_text: str, style: str = "careful") -> Polished:
        """Возвращает правку с таймингами. Бросает LLMUnavailable при сбое.

        style — careful (вычистить мусор) или dry (оставить только суть).
        """
        prompt = self._build_prompt(raw_text, style)
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
            # Модель иногда дописывает к готовому ответу собственную разметку и
            # начинает текст заново — на реальной диктовке так потерялось две
            # трети фразы. Обрываем ровно на этих словах.
            "stop": ["Input text:", "Cleaned output text:", "\nВход:", "\nВыход:"],
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
            body = response.json()
        except ValueError as exc:
            self.last_error = "Ollama вернула некорректный JSON"
            raise LLMUnavailable(self.last_error) from exc

        result = body.get("response", "")
        cleaned = _sanitize(result)
        took = time.monotonic() - started
        polished = Polished(
            text=cleaned,
            response=result,
            took_s=took,
            output_tokens=int(body.get("eval_count", 0)),
            gen_s=float(body.get("eval_duration", 0)) / 1e9,
        )
        print(f"[llm] за {took:.1f} с: «{cleaned}»")

        if not _looks_sane(cleaned, raw_text):
            polished.accepted = False
            self.last_error = "модель ответила не по делу"
            raise LLMUnavailable(self.last_error, polished)

        self.last_error = None
        return polished

    def _build_prompt(self, raw_text: str, style: str = "careful") -> str:
        # Системная часть неизменна от запроса к запросу, поэтому Ollama
        # переиспользует её KV-кэш и обсчитывает заново только сам транскрипт.
        # Смена стиля меняет префикс, и первая фраза в новом стиле платит за
        # его обсчёт пару секунд — дальше кэш снова работает.
        system = self.cfg.dry_prompt if style == "dry" else self.cfg.system_prompt
        return (
            f"{system}\n\n"
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

    # Сухой стиль любит оформлять списком даже одну мысль; список из одного
    # пункта — это просто предложение.
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].lstrip().startswith(("- ", "— ", "• ")):
        text = lines[0].lstrip()[2:]

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
