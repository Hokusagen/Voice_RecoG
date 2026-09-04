"""Облачный редактор и распознавание через OpenAI-совместимый API.

По умолчанию это Groq: бесплатный тариф без карты, ответ быстрее секунды,
модели на русском заметно сильнее тех, что влезают в 4 ГБ видеопамяти. Но
адрес и модели живут в настройках, так что подойдёт любой сервер с теми же
путями /chat/completions и /audio/transcriptions — OpenAI, OpenRouter, Gemini
в режиме совместимости, собственный прокси.

Всё, что уходит сюда, покидает машину. Клиент молчит, пока ключ пуст, и
конвейер в этом случае работает по-старому, локально.
"""

from __future__ import annotations

import io
import re
import time
import wave
from dataclasses import dataclass, field

import numpy as np
import requests

from config import CloudConfig, LLMConfig
from core.llm import LLMUnavailable, Polished, _looks_sane, _sanitize


@dataclass
class Quota:
    """Остатки лимитов, как их сообщил сервер в заголовках последнего ответа.

    Groq отдаёт x-ratelimit-*: запросы считаются на сутки, токены — на
    минуту, и к каждому прилагается время до сброса. По ним можно не ждать
    отказа 429, а заранее понять, что минутный лимит на эту фразу не хватит.
    """

    requests_left: int | None = None
    requests_limit: int | None = None
    requests_reset_s: float = 0.0
    tokens_left: int | None = None
    tokens_limit: int | None = None
    tokens_reset_s: float = 0.0
    at: float = field(default_factory=time.monotonic)

    @property
    def age_s(self) -> float:
        return time.monotonic() - self.at

    def tokens_now(self) -> int | None:
        """Сколько токенов в минуте осталось с поправкой на прошедшее время."""
        if self.tokens_left is None:
            return None
        if self.tokens_reset_s and self.age_s >= self.tokens_reset_s:
            return self.tokens_limit if self.tokens_limit is not None else self.tokens_left
        return self.tokens_left

    def requests_now(self) -> int | None:
        if self.requests_left is None:
            return None
        if self.requests_reset_s and self.age_s >= self.requests_reset_s:
            return self.requests_limit if self.requests_limit is not None else self.requests_left
        return self.requests_left

    @property
    def known(self) -> bool:
        return self.requests_left is not None or self.tokens_left is not None


def parse_quota(headers) -> Quota:
    def num(name: str) -> int | None:
        value = headers.get(name)
        try:
            return int(float(value)) if value is not None else None
        except ValueError:
            return None

    return Quota(
        requests_left=num("x-ratelimit-remaining-requests"),
        requests_limit=num("x-ratelimit-limit-requests"),
        requests_reset_s=parse_duration(headers.get("x-ratelimit-reset-requests", "")),
        tokens_left=num("x-ratelimit-remaining-tokens"),
        tokens_limit=num("x-ratelimit-limit-tokens"),
        tokens_reset_s=parse_duration(headers.get("x-ratelimit-reset-tokens", "")),
    )


_DURATION = re.compile(r"(\d+(?:\.\d+)?)(h|m(?!s)|s|ms)")


def parse_duration(text: str) -> float:
    """«25m55.199s», «150ms», «1h2m» -> секунды. Голое число тоже секунды."""
    text = (text or "").strip().lower()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    total = 0.0
    for value, unit in _DURATION.findall(text):
        total += float(value) * {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}[unit]
    return total


def _estimate_tokens(*texts: str) -> int:
    """Русский у этих моделей режется примерно по три символа на токен;
    берём с запасом, чтобы не влететь в отказ на длинной фразе."""
    return sum(len(t) for t in texts) // 3 + 128


class CloudClient:
    def __init__(self, cfg: CloudConfig, llm_cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.llm_cfg = llm_cfg
        self._session = requests.Session()
        self.last_error: str | None = None
        self.quota = Quota()
        """Лимиты редактора (chat/completions)."""

        self.audio_quota = Quota()
        """Лимиты распознавания (audio/transcriptions): у Groq они отдельные."""

    # ---------- лимиты ----------

    def tokens_needed(self, raw_text: str, style: str = "careful") -> int:
        system = self.llm_cfg.dry_prompt if style == "dry" else self.llm_cfg.system_prompt
        return _estimate_tokens(system, raw_text) + _estimate_tokens(raw_text)

    def wait_for_polish(self, raw_text: str, style: str = "careful") -> float | None:
        """Сколько секунд подождать до правки; 0 — можно сразу; None — лимит суток.

        Считается по последним заголовкам: если минутных токенов на фразу не
        хватает, возвращает время до их сброса.
        """
        quota = self.quota
        if not quota.known:
            return 0.0
        requests_left = quota.requests_now()
        if requests_left is not None and requests_left <= 0:
            return None
        tokens = quota.tokens_now()
        if tokens is None or tokens >= self.tokens_needed(raw_text, style):
            return 0.0
        return max(0.5, quota.tokens_reset_s - quota.age_s)

    def quota_line(self) -> str:
        """Строка для трея: «облако: 982 из 1000 правок на сегодня · 7.9k ток/мин»."""
        q = self.quota
        if not q.known:
            return ""
        parts = []
        if q.requests_left is not None:
            parts.append(f"{q.requests_now()} из {q.requests_limit} правок на сегодня")
        if q.tokens_left is not None:
            parts.append(f"{(q.tokens_now() or 0) / 1000:.1f}k из {(q.tokens_limit or 0) / 1000:.0f}k токенов в минуту")
        a = self.audio_quota
        if a.requests_left is not None:
            parts.append(f"{a.requests_now()} из {a.requests_limit} распознаваний")
        return "облако: " + " · ".join(parts)

    def _remember(self, response: requests.Response, audio: bool = False) -> None:
        quota = parse_quota(response.headers)
        if not quota.known:
            return
        if audio:
            self.audio_quota = quota
        else:
            self.quota = quota

    # ---------- состояние ----------

    @property
    def configured(self) -> bool:
        """Ключ вставлен — значит, пользователь осознанно включил облако."""
        return bool(self.cfg.api_key.strip())

    @property
    def label(self) -> str:
        """Подпись для трея и журнала: «облако · openai/gpt-oss-120b»."""
        return f"облако · {self.cfg.model}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.cfg.api_key.strip()}"}

    @property
    def _base(self) -> str:
        return self.cfg.url.rstrip("/")

    # ---------- правка ----------

    def polish(self, raw_text: str, style: str = "careful") -> Polished:
        """Та же правка, что у OllamaClient, но через chat/completions."""
        system = self.llm_cfg.dry_prompt if style == "dry" else self.llm_cfg.system_prompt
        payload: dict = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": raw_text},
            ],
            "temperature": self.llm_cfg.temperature,
            # Потолок щедрый: у рассуждающих моделей размышления тоже идут в
            # счёт ответа, и тесный лимит обрывал текст на полуслове.
            "max_tokens": 2048,
        }
        if "gpt-oss" in self.cfg.model:
            # Рассуждающая модель: на чистке текста думать не о чем, а каждая
            # секунда раздумий — это секунда ожидания вставки.
            payload["reasoning_effort"] = "low"

        started = time.monotonic()
        try:
            response = self._session.post(
                f"{self._base}/chat/completions",
                json=payload,
                headers=self._headers(),
                timeout=self.cfg.timeout_s,
            )
        except requests.RequestException as exc:
            self.last_error = _describe(exc)
            raise LLMUnavailable(self.last_error) from exc

        self._remember(response)
        if response.status_code != 200:
            self.last_error = _http_error(response)
            raise LLMUnavailable(self.last_error)

        try:
            body = response.json()
            result = body["choices"][0]["message"]["content"] or ""
            usage = body.get("usage", {})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self.last_error = "облако вернуло непонятный ответ"
            raise LLMUnavailable(self.last_error) from exc

        cleaned = _sanitize(result)
        took = time.monotonic() - started
        polished = Polished(
            text=cleaned,
            response=result,
            took_s=took,
            output_tokens=int(usage.get("completion_tokens", 0)),
            gen_s=float(usage.get("completion_time", 0.0)),
        )
        print(f"[cloud] за {took:.1f} с: «{cleaned}»")

        if not _looks_sane(cleaned, raw_text):
            polished.accepted = False
            self.last_error = "облако ответило не по делу"
            raise LLMUnavailable(self.last_error, polished)

        self.last_error = None
        return polished

    # ---------- распознавание ----------

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str, prompt: str) -> str:
        """Whisper в облаке: тот же large-v3-turbo, но без видеокарты и за секунду."""
        pcm = np.clip(audio, -1.0, 1.0)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes((pcm * 32767).astype("<i2").tobytes())

        data = {
            "model": self.cfg.whisper_model,
            "response_format": "json",
            "temperature": "0",
        }
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        try:
            response = self._session.post(
                f"{self._base}/audio/transcriptions",
                data=data,
                files={"file": ("speech.wav", buffer.getvalue(), "audio/wav")},
                headers=self._headers(),
                timeout=self.cfg.timeout_s,
            )
        except requests.RequestException as exc:
            self.last_error = _describe(exc)
            raise CloudUnavailable(self.last_error) from exc

        self._remember(response, audio=True)
        if response.status_code != 200:
            self.last_error = _http_error(response)
            raise CloudUnavailable(self.last_error)

        try:
            text = response.json().get("text", "")
        except ValueError as exc:
            self.last_error = "облако вернуло непонятный ответ"
            raise CloudUnavailable(self.last_error) from exc

        self.last_error = None
        return text.strip()


class CloudUnavailable(RuntimeError):
    """Облачное распознавание не ответило; конвейер откатится на локальное."""


def _describe(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "облако недоступно: нет сети"
    if isinstance(exc, requests.Timeout):
        return "облако не ответило вовремя"
    return f"облако: {exc}"


def _http_error(response: requests.Response) -> str:
    code = response.status_code
    if code == 401:
        return "облако не приняло ключ"
    if code == 429:
        retry = parse_duration(response.headers.get("retry-after", ""))
        return "облако: исчерпан лимит" + (f", сброс через {retry:.0f} с" if retry else "")
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = ""
    return f"облако ответило {code}" + (f": {message[:80]}" if message else "")

