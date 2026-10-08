"""GigaChat (Сбер) как сервер вопросов: всё, чем он отличается от OpenAI-совместимых.

Пути и поток у него те же, chat/completions, но пускает он по-своему. Bearer —
не ключ из личного кабинета, а токен на полчаса, который выдают в обмен на
этот ключ («ключ авторизации»). И сертификат у его серверов от НУЦ Минцифры,
которого нет в certifi: без своего корневого сертификата Python его серверам
не доверяет. Корневой лежит в assets/certs и используется только в запросах к
GigaChat — доверие к этому центру остальному приложению ни к чему.

Узнаём GigaChat по адресу: другого способа пустить к нему нет, так что
отдельная настройка только дала бы ошибиться.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

SCOPE = "GIGACHAT_API_PERS"
"""Доступ физлица. У компаний свои: GIGACHAT_API_B2B и GIGACHAT_API_CORP."""

_HOSTS = ("api.giga.chat", "gigachat.devices.sberbank.ru")

_MARGIN_S = 60.0
"""За сколько до конца жизни токена брать новый: запрос с токеном, истёкшим
посреди длинного ответа, сервер отбил бы."""


def is_gigachat(url: str) -> bool:
    return (urlparse(url.strip()).hostname or "") in _HOSTS


def ca_file() -> str:
    """Корневой сертификат НУЦ Минцифры — и из исходников, и из собранного exe."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parents[2]
    return str(base / "assets" / "certs" / "russian_trusted_root_ca.pem")


class AuthFailed(requests.RequestException):
    """Токен не выдали. Наследник RequestException: для клиента облака это
    такой же сбой связи с сервером, как оборванная сеть."""


class GigaChatAuth:
    """Держит токен доступа и берёт новый, когда старый на исходе."""

    def __init__(self, key: str, timeout_s: float = 20.0) -> None:
        # Ключ иногда копируют вместе с «Basic » из примера запроса.
        self.key = key.strip().removeprefix("Basic ").strip()
        self.timeout_s = timeout_s
        self._token = ""
        self._expires_at = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires_at - _MARGIN_S:
            return self._token
        response = requests.post(
            OAUTH_URL,
            headers={
                "Authorization": f"Basic {self.key}",
                # Сбер требует свой номер у каждого запроса токена.
                "RqUID": str(uuid.uuid4()),
                "Accept": "application/json",
            },
            data={"scope": SCOPE},
            verify=ca_file(),
            timeout=self.timeout_s,
        )
        if response.status_code != 200:
            raise AuthFailed(f"GigaChat не выдал токен ({response.status_code}): проверь ключ авторизации")
        body = response.json()
        self._token = body["access_token"]
        # expires_at — в миллисекундах; без него токен живёт полчаса.
        expires = body.get("expires_at")
        self._expires_at = expires / 1000 if expires else time.time() + 1800
        return self._token

    def forget(self) -> None:
        """Сервер токен не принял: следующий запрос возьмёт новый."""
        self._token = ""
