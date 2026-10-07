"""Облачный редактор и распознавание через OpenAI-совместимый API.

По умолчанию это Groq: бесплатный тариф без карты, ответ быстрее секунды,
модели на русском заметно сильнее тех, что влезают в 4 ГБ видеопамяти. Но
адрес и модели живут в настройках, так что подойдёт любой сервер с теми же
путями /chat/completions и /audio/transcriptions — OpenAI, OpenRouter, Gemini
в режиме совместимости, собственный прокси.

Серверов может быть два: основной и запасной, `cloud.reserve` в настройках.
Groq закрывает доступ целым диапазонам адресов — однажды он перестал отвечать
всем, кто выходил в сеть через тот же VPN, и приложение осталось с Whisper на
процессоре. Если основной сервер молчит, запрос уходит запасному, а через
четверть часа приложение пробует основной снова: у него бесплатный тариф, у
запасного платный.

Всё, что уходит сюда, покидает машину. Клиент молчит, пока ключ пуст, и
конвейер в этом случае работает по-старому, локально.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import requests

from config import AskConfig, CloudConfig, LLMConfig
from core.ask import Answer, AskFailed, clean_answer
from core.audio import to_wav
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


@dataclass
class _Server:
    """Один облачный сервер: куда идти, чем платить и что он о себе сообщил.

    Лимиты и расход токенов у каждого свои, поэтому живут здесь, а не в
    клиенте: после переключения счётчики Groq ничего не говорят о запасном.
    """

    name: str
    url: str
    api_key: str
    model: str
    whisper_model: str
    output_tokens_per_minute: int

    quota: Quota = field(default_factory=Quota)
    """Лимиты редактора (chat/completions)."""

    audio_quota: Quota = field(default_factory=Quota)
    """Лимиты распознавания (audio/transcriptions): у Groq они отдельные."""

    ask_quota: Quota = field(default_factory=Quota)
    """Лимиты модели вопросов: у Groq они свои у каждой модели, и остатки по
    вопросам не должны выдавать себя за остатки правки."""

    output_log: list[tuple[float, int]] = field(default_factory=list)
    """Выходные токены последней минуты: OTPM сервер в заголовках не шлёт."""

    sends_prompt: bool = True
    """Принимает ли prompt в транскрипции.

    У Groq это подсказка со списком терминов, а OpenRouter такого поля не
    знает и отбивает весь запрос. Узнаём по первому отказу и больше не шлём.
    """

    @property
    def base(self) -> str:
        return self.url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key.strip()}"}

    @property
    def live(self) -> bool:
        """Ключ вставлен — значит, этим сервером можно пользоваться."""
        return bool(self.api_key.strip())

    def remember(self, response: requests.Response, slot: str = "chat") -> None:
        """slot — чьи это лимиты: chat (правка), audio или ask."""
        quota = parse_quota(response.headers)
        if not quota.known:
            return
        if slot == "audio":
            self.audio_quota = quota
        elif slot == "ask":
            self.ask_quota = quota
        else:
            self.quota = quota


class CloudClient:
    def __init__(self, cfg: CloudConfig, llm_cfg: LLMConfig, ask_cfg: AskConfig | None = None) -> None:
        self.cfg = cfg
        self.llm_cfg = llm_cfg
        self._session = requests.Session()
        self.last_error: str | None = None

        main = _Server(
            "облако", cfg.url, cfg.api_key, cfg.model,
            cfg.whisper_model, cfg.output_tokens_per_minute,
        )
        reserve = _Server(
            "запасное облако", cfg.reserve.url, cfg.reserve.api_key, cfg.reserve.model,
            cfg.reserve.whisper_model, cfg.reserve.output_tokens_per_minute,
        )
        self._servers = [server for server in (main, reserve) if server.live]
        self._active = self._servers[0] if self._servers else main
        """Кого спрашиваем сейчас. Меняется сам, когда сервер перестаёт отвечать."""

        self._left_main_at = 0.0
        """Когда ушли с основного: через reserve.return_after_s пробуем его снова."""

        self._ask_server: _Server | None = None
        """Свой сервер для вопросов из ask.url: тогда вопросы не ходят на серверы
        правки и не переезжают на запасной."""
        if ask_cfg is not None and ask_cfg.url.strip() and ask_cfg.api_key.strip():
            self._ask_server = _Server(
                "облако вопросов", ask_cfg.url, ask_cfg.api_key, ask_cfg.model, "", 0,
            )

    # ---------- кто отвечает ----------

    @property
    def quota(self) -> Quota:
        return self._active.quota

    @property
    def audio_quota(self) -> Quota:
        return self._active.audio_quota

    @property
    def model(self) -> str:
        return self._active.model

    @property
    def whisper_model(self) -> str:
        return self._active.whisper_model

    @property
    def on_reserve(self) -> bool:
        """Работает не тот сервер, который человек считает основным."""
        return bool(self._servers) and self._active is not self._servers[0]

    def _chain(self) -> list[_Server]:
        """Кого пробовать в этом запросе: активного, следом остальных."""
        return [self._active] + [s for s in self._servers if s is not self._active]

    def _maybe_return(self) -> None:
        """Пора ли обратно на основной сервер.

        Уход на запасной — это почти всегда оборванный VPN или блокировка по
        адресу, и то и другое проходит. Ждём четверть часа, чтобы не платить
        таймаутом за каждую диктовку, и пробуем снова.
        """
        if not self.on_reserve:
            return
        if time.monotonic() - self._left_main_at < self.cfg.reserve.return_after_s:
            return
        print("[cloud] пробую основное облако снова")
        self._active = self._servers[0]

    def _settle(self, server: _Server) -> None:
        """Запоминает, кто ответил: со следующей диктовки идём сразу к нему."""
        if server is self._active:
            return
        self._active = server
        if self.on_reserve:
            self._left_main_at = time.monotonic()
        print(f"[cloud] перешёл на {server.name}: {server.model}")

    def _request(
        self,
        path: str,
        build: Callable[[_Server], dict],
        slot: str = "chat",
        on_limit: bool = False,
        only: _Server | None = None,
    ) -> requests.Response:
        """Запрос активному серверу, а если он молчит — следующему.

        Молчание — это оборванная сеть, отклонённый ключ, закрытый доступ или
        ошибка на той стороне: всё, с чем повторять к тому же серверу
        бессмысленно. Отказ по лимиту в этот список не входит — правку
        подхватит Ollama; on_limit добавляет его для распознавания, где
        альтернатива хуже: Whisper на процессоре идёт в реальном времени.

        Тело запроса собирает build: у серверов разные модели и потолок ответа,
        поэтому один раз заранее его не посчитать. only — спросить только этот
        сервер, мимо цепочки основной–запасной.
        """
        if only is None:
            self._maybe_return()
        trouble = "облако не настроено"
        for server in [only] if only is not None else self._chain():
            try:
                response = self._session.post(
                    f"{server.base}/{path}",
                    headers=server.headers,
                    timeout=self.cfg.timeout_s,
                    **build(server),
                )
            except requests.RequestException as exc:
                trouble = _describe(exc)
            else:
                server.remember(response, slot)
                if not _hopeless(response, on_limit):
                    if only is None:
                        self._settle(server)
                    return response
                trouble = _http_error(response)
            print(f"[cloud] {server.name} не отвечает: {trouble}")
        raise CloudDown(trouble)

    # ---------- лимиты ----------

    def tokens_needed(self, raw_text: str, style: str = "careful") -> int:
        system = self.llm_cfg.dry_prompt if style == "dry" else self.llm_cfg.system_prompt
        return _estimate_tokens(system, raw_text) + _estimate_tokens(raw_text)

    def output_cap(self, raw_text: str, server: _Server | None = None) -> int:
        """Сколько токенов разрешить ответу.

        Правка возвращает примерно тот же текст, что и приняла, так что потолок
        считаем по длине фразы с запасом на знаки — и не выше минутного лимита:
        заявленный потолок выше него сервер отбивает, даже не начав отвечать.
        """
        server = server or self._active
        cap = _estimate_tokens(raw_text) + len(raw_text) // 9
        limit = server.output_tokens_per_minute
        return min(cap, limit) if limit > 0 else cap

    def _spend_output(self, tokens: int) -> None:
        """Записывает расход: по заголовкам его не восстановить."""
        if tokens > 0:
            self._active.output_log.append((time.monotonic(), tokens))

    def wait_for_output(self, cap: int) -> float:
        """Сколько ждать, пока в минутном окне освободится место под ответ."""
        limit = self._active.output_tokens_per_minute
        if limit <= 0:
            return 0.0
        now = time.monotonic()
        log = [(at, n) for at, n in self._active.output_log if now - at < 60.0]
        self._active.output_log = log
        spent = sum(n for _, n in log)
        if spent + cap <= limit:
            return 0.0
        freed = 0
        for at, tokens in log:
            freed += tokens
            if spent - freed + cap <= limit:
                return max(0.5, 60.0 - (now - at))
        return 60.0

    def wait_for_polish(self, raw_text: str, style: str = "careful") -> float | None:
        """Сколько секунд подождать до правки; 0 — можно сразу; None — лимит суток.

        Считается по последним заголовкам: если минутных токенов на фразу не
        хватает, возвращает время до их сброса.
        """
        quota = self.quota
        output_wait = self.wait_for_output(self.output_cap(raw_text))
        if not quota.known:
            return output_wait
        requests_left = quota.requests_now()
        if requests_left is not None and requests_left <= 0:
            return None
        tokens = quota.tokens_now()
        if tokens is None or tokens >= self.tokens_needed(raw_text, style):
            return output_wait
        return max(output_wait, quota.tokens_reset_s - quota.age_s, 0.5)

    def quota_line(self) -> str:
        """Строка для трея: «облако: 982 из 1000 правок на сегодня · 7.9k ток/мин»."""
        q = self.quota
        parts = []
        if q.requests_left is not None:
            parts.append(f"{q.requests_now()} из {q.requests_limit} правок на сегодня")
        if q.tokens_left is not None:
            parts.append(f"{(q.tokens_now() or 0) / 1000:.1f}k из {(q.tokens_limit or 0) / 1000:.0f}k токенов в минуту")
        a = self.audio_quota
        if a.requests_left is not None:
            parts.append(f"{a.requests_now()} из {a.requests_limit} распознаваний")
        q = (self._ask_server or self._active).ask_quota
        if q.requests_left is not None:
            parts.append(f"{q.requests_now()} из {q.requests_limit} вопросов")
        if not parts:
            # Запасной сервер лимиты в заголовках не шлёт, но то, что работает
            # он, а не основной, человеку важнее самих цифр: там платный тариф.
            return "работает запасное облако" if self.on_reserve else ""
        return f"{self._active.name}: " + " · ".join(parts)

    # ---------- состояние ----------

    @property
    def configured(self) -> bool:
        """Ключ вставлен — значит, пользователь осознанно включил облако."""
        return bool(self._servers)

    @property
    def can_ask(self) -> bool:
        """Есть кому задать вопрос: свой сервер вопросов или серверы правки."""
        return self._ask_server is not None or self.configured

    @property
    def label(self) -> str:
        """Подпись для трея и журнала: «облако · openai/gpt-oss-120b»."""
        return f"{self._active.name} · {self._active.model}"

    @property
    def stt_label(self) -> str:
        """То же про распознавание: «облако · whisper-large-v3-turbo»."""
        return f"{self._active.name} · {self._active.whisper_model}"

    # ---------- правка ----------

    def polish(self, raw_text: str, style: str = "careful") -> Polished:
        """Та же правка, что у OllamaClient, но через chat/completions."""
        system = self.llm_cfg.dry_prompt if style == "dry" else self.llm_cfg.system_prompt

        def build(server: _Server) -> dict:
            payload: dict = {
                "model": server.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": raw_text},
                ],
                "temperature": self.llm_cfg.temperature,
                # Потолок считаем по длине фразы: в лимит OTPM у Groq идёт не
                # фактический ответ, а это число, и щедрые 2048 отбивались
                # отказом ещё до модели.
                "max_tokens": self.output_cap(raw_text, server),
            }
            if "gpt-oss" in server.model:
                # Рассуждающая модель: на чистке текста думать не о чем, а
                # каждая секунда раздумий — это секунда ожидания вставки.
                payload["reasoning_effort"] = "low"
            return {"json": payload}

        started = time.monotonic()
        try:
            response = self._request("chat/completions", build)
        except CloudDown as exc:
            self.last_error = str(exc)
            raise LLMUnavailable(self.last_error) from exc

        if response.status_code == 429:
            self.last_error = _http_error(response)
            retry = parse_duration(response.headers.get("retry-after", ""))
            kind = "day" if (self.quota.requests_now() or 1) <= 0 else "minute"
            raise CloudLimited(self.last_error, kind, retry or self.quota.tokens_reset_s or 60.0)
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
        self._spend_output(int(usage.get("completion_tokens", 0)))
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

    # ---------- вопросы ----------

    def ask(
        self,
        messages: list[dict],
        model: str,
        effort: str,
        max_tokens: int,
        on_delta: Callable[[str], None] | None = None,
        search: bool = False,
    ) -> Answer:
        """Ответ на вопрос потоком: on_delta получает текст по мере генерации.

        Поток нужен не ради эффекта: рассуждающая модель отвечает секундами, и
        карточка должна заполняться, а не ждать конца. Раздумья модели (поле
        reasoning у gpt-oss) не показываем, только считаем.

        search — встроенный поиск gpt-oss у Groq, обязательный: по своей воле
        модель им почти не пользуется (6.10 не стала искать даже API Godot и
        выдала код третьей версии). В on_delta текст идёт как есть, со ссылками
        вида 【2†L14-L17】; чистит их clean_answer.
        """

        def build(server: _Server) -> dict:
            payload: dict = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "stream": True,
                # Без этого OpenAI-совместимые серверы не присылают расход
                # токенов в потоке; Groq кладёт его ещё и в x_groq.
                "stream_options": {"include_usage": True},
            }
            if effort:
                payload["reasoning_effort"] = effort
            if search:
                payload["tools"] = [{"type": "browser_search"}]
                payload["tool_choice"] = "required"
            return {"json": payload, "stream": True}

        started = time.monotonic()
        try:
            response = self._request("chat/completions", build, slot="ask", only=self._ask_server)
        except CloudDown as exc:
            self.last_error = str(exc)
            raise AskFailed(self.last_error) from exc

        with response:
            if response.status_code != 200:
                self.last_error = _http_error(response)
                raise AskFailed(self.last_error)
            answer = Answer(text="", model=model, effort=effort)
            try:
                _read_stream(response, answer, started, on_delta)
            except requests.RequestException as exc:
                self.last_error = "облако оборвало ответ: " + _describe(exc)
                raise AskFailed(self.last_error) from exc

        answer.text = clean_answer(answer.text)
        answer.took_s = time.monotonic() - started
        if not answer.text:
            # Пустой ответ с обрывом — это не сбой облака: рассуждающая модель
            # на трудном вопросе может извести весь max_tokens на раздумья
            # (gpt-oss · high, 2998 из 3000, 6.10.2026).
            self.last_error = (
                "модель потратила весь потолок ответа на раздумья"
                if answer.truncated else "облако ответило пустым текстом"
            )
            raise AskFailed(self.last_error)
        self.last_error = None
        return answer

    # ---------- распознавание ----------

    def transcribe(self, audio: np.ndarray, sample_rate: int, language: str, prompt: str) -> str:
        """Whisper в облаке: тот же large-v3-turbo, но без видеокарты и за секунду."""
        speech = to_wav(audio, sample_rate)

        def build(server: _Server) -> dict:
            data = {
                "model": server.whisper_model,
                "response_format": "json",
                "temperature": "0",
            }
            if language:
                data["language"] = language
            if prompt and server.sends_prompt:
                data["prompt"] = prompt
            return {"data": data, "files": {"file": ("speech.wav", speech, "audio/wav")}}

        response = self._transcription(build)
        if response.status_code == 400 and prompt and self._active.sends_prompt:
            # Подсказку с терминами принимают не все: OpenRouter поля prompt не
            # знает и отбивает весь запрос. Повторяем без неё — лучше
            # распознать без списка терминов, чем не распознать вовсе.
            print(f"[cloud] {self._active.name} не приняло prompt — повторяю без него")
            self._active.sends_prompt = False
            response = self._transcription(build)

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

    def _transcription(self, build: Callable[[_Server], dict]) -> requests.Response:
        try:
            return self._request("audio/transcriptions", build, slot="audio", on_limit=True)
        except CloudDown as exc:
            self.last_error = str(exc)
            raise CloudUnavailable(self.last_error) from exc


class CloudUnavailable(RuntimeError):
    """Облачное распознавание не ответило; конвейер откатится на локальное."""


class CloudDown(RuntimeError):
    """Не ответил ни один сервер: внутренняя, наружу выходит переведённой."""


class CloudLimited(LLMUnavailable):
    """Облако упёрлось в лимит. kind — «minute» или «day», reset_s — когда отпустит."""

    def __init__(self, message: str, kind: str, reset_s: float) -> None:
        super().__init__(message)
        self.kind = kind
        self.reset_s = reset_s


def _read_stream(
    response: requests.Response,
    answer: Answer,
    started: float,
    on_delta: Callable[[str], None] | None,
) -> None:
    """Разбирает поток server-sent events в answer.

    Строки режем по байтам, а не по декодированному тексту: iter_lines с
    decode_unicode делит строки ещё и по U+2028 и прочим разделителям из
    юникода, и на первом же замере JSON посреди ответа порвался пополам.
    """
    for raw in response.iter_lines():
        line = raw.decode("utf-8", "replace").strip()
        # Пустые строки разделяют события, а «:» в начале — пинги-комментарии.
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        error = chunk.get("error")
        if error:
            message = error.get("message", "") if isinstance(error, dict) else str(error)
            raise AskFailed(f"облако прервало ответ: {message[:80]}")
        usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
        if usage:
            answer.prompt_tokens = int(usage.get("prompt_tokens") or 0)
            answer.completion_tokens = int(usage.get("completion_tokens") or 0)
            details = usage.get("completion_tokens_details") or {}
            answer.reasoning_tokens = int(details.get("reasoning_tokens") or 0)
        for choice in chunk.get("choices") or []:
            if choice.get("finish_reason") == "length":
                answer.truncated = True
            for tool in (choice.get("delta") or {}).get("executed_tools") or []:
                _note_source(answer, tool)
            piece = (choice.get("delta") or {}).get("content")
            if not piece:
                continue
            if not answer.text:
                answer.first_s = time.monotonic() - started
            answer.text += piece
            if on_delta is not None:
                on_delta(piece)


#: Адрес страницы в выводе инструмента браузера: «L1: URL: https://…».
_TOOL_URL = re.compile(r"URL:\s*(https?://\S+)")


def _note_source(answer: Answer, tool: dict) -> None:
    """Запоминает, что модель нашла или открыла.

    Каждый шаг браузера приходит в потоке дважды: сначала аргументы, потом
    вывод. Открытые страницы — то, что модель прочла, они идут в источники
    первыми; выдачу поиска держим про запас — на случай, если модель
    ответила по сниппетам и ничего не открывала.
    """
    if "output" not in tool:
        return
    answer.searched = True
    name = tool.get("name", "")
    found = tool.get("search_results")
    results = found.get("results") if isinstance(found, dict) else None
    urls = [r.get("url", "") for r in results or [] if isinstance(r, dict)]
    if name == "browser.open":
        match = _TOOL_URL.search(tool.get("output") or "")
        opened = urls[:1] or ([match.group(1)] if match else [])
        for url in opened:
            if url and url not in answer.opened:
                answer.opened.append(url)
    elif name == "browser.search":
        for url in urls:
            if url and url not in answer.found:
                answer.found.append(url)


def _hopeless(response: requests.Response, on_limit: bool) -> bool:
    """Стоит ли с таким ответом идти к другому серверу.

    Закрытый доступ, отклонённый ключ, отсутствующий путь и любая ошибка на той
    стороне — да: повтор к тому же серверу ничего не изменит. Всё остальное,
    включая наши собственные 400, возвращаем как есть.
    """
    code = response.status_code
    if code == 200:
        return False
    if code in (401, 403, 404, 408):
        return True
    if code == 429:
        return on_limit
    return code >= 500


def _describe(exc: Exception) -> str:
    if isinstance(exc, requests.ConnectionError):
        return "облако недоступно: нет сети"
    if isinstance(exc, requests.Timeout):
        return "облако не ответило вовремя"
    return f"облако: {exc}"


#: «...on output tokens per minute (OTPM): Limit 1000, Requested 1582» —
#: название лимита из тела отказа. «Limit» обязателен: у Gemini в тексте
#: отказа есть «more information on this error, head to:», и без него
#: квота тарифа читалась как лимит с названием «this error, head to».
_LIMIT_NAME = re.compile(r" on ([^:]+): Limit")


def _http_error(response: requests.Response) -> str:
    code = response.status_code
    if code == 401:
        return "облако не приняло ключ"
    try:
        body = response.json()
        # Gemini в режиме совместимости кладёт ошибку в список из одного элемента.
        if isinstance(body, list) and body:
            body = body[0]
        message = body["error"]["message"] or ""
    except (ValueError, KeyError, TypeError, IndexError):
        message = ""
    if code == 403:
        # Groq закрывает доступ целым диапазонам адресов, и в теле ответа это
        # не отличить от запрета на модель: подсказываем, куда смотреть.
        return "облако закрыло доступ с этого адреса" + (f": {message[:60]}" if message else "")
    if code == 429:
        retry = parse_duration(response.headers.get("retry-after", ""))
        # Какой лимит упёрся, пишут только в теле: в заголовках у Groq запросы
        # и токены в минуту, а отбить запрос может и то, чего там нет.
        name = _LIMIT_NAME.search(message)
        detail = name.group(1).strip() if name else ""
        if not detail and "quota" in message.lower():
            # Так отказывает Gemini, когда кончились бесплатные запросы на сутки:
            # ждать минуту тут бесполезно, и это должно быть видно из текста.
            detail = "квота тарифа"
        return (
            "облако: исчерпан лимит"
            + (f" — {detail}" if detail else "")
            + (f", сброс через {retry:.0f} с" if retry else "")
        )
    return f"облако ответило {code}" + (f": {message[:80]}" if message else "")
