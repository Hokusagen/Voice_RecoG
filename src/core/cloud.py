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
import time
import wave

import numpy as np
import requests

from config import CloudConfig, LLMConfig
from core.llm import LLMUnavailable, Polished, _looks_sane, _sanitize


class CloudClient:
    def __init__(self, cfg: CloudConfig, llm_cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.llm_cfg = llm_cfg
        self._session = requests.Session()
        self.last_error: str | None = None

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
            # Тот же потолок, что у локальной модели: ответ не длиннее входа
            # больше чем в полтора раза.
            "max_tokens": min(1024, max(96, len(raw_text) // 2 + 64)),
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
        return "облако: исчерпан лимит запросов"
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = ""
    return f"облако ответило {code}" + (f": {message[:80]}" if message else "")

