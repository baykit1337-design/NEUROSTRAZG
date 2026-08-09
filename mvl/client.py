"""HTTP-клиенты для двух хостов.

- `chap.heliosarchive.online` — REST API: каталог и оглавление. Открыт.
- `www.mvlempyr.io` — витрина: единственный источник текста глав.
  Путь `/chapter/*` на бэкенд-хосте закрыт правилом WAF, тексты берём здесь.

Только HTTP-запросы: никаких headless-браузеров. Нужен curl_cffi с отпечатком
Chrome — обычный requests Cloudflare отсекает по TLS-отпечатку.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

BASE = "https://chap.heliosarchive.online"
API = f"{BASE}/wp-json/wp/v2"
SITE = "https://www.mvlempyr.io"

# Вежливость к серверу — значения из ТЗ, поднимать не нужно.
MAX_CONCURRENCY = 5
PAUSE_RANGE = (1.0, 2.0)
# Витрина: строго один поток, пауза 2-4 секунды с джиттером.
SITE_PAUSE_RANGE = (2.0, 4.0)
MAX_ATTEMPTS = 3
TIMEOUT = 30

log = logging.getLogger(__name__)


class HttpError(Exception):
    """Запрос не удался после всех попыток."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Blocked(HttpError):
    """Cloudflare закрыл доступ (403/429).

    Ретраить бессмысленно и вредно: повторы только усугубят блокировку.
    Прогон останавливается целиком.
    """


def _make_session():
    """Сессия curl_cffi, либо requests, либо тонкая обёртка над urllib."""
    try:
        from curl_cffi import requests as curl_requests

        return curl_requests.Session(impersonate="chrome"), "curl_cffi"
    except ImportError:
        pass

    try:
        import requests

        session = requests.Session()
        session.headers.update({"User-Agent": _FALLBACK_UA})
        return session, "requests"
    except ImportError:
        return _UrllibSession(), "urllib"


_FALLBACK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class _UrllibResponse:
    def __init__(self, status: int, body: bytes):
        self.status_code = status
        self._body = body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", "replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class _UrllibSession:
    """Последний рубеж: стандартная библиотека, без внешних зависимостей."""

    def get(self, url: str, params=None, timeout: int = TIMEOUT, **_):
        import urllib.error
        import urllib.request

        if params:
            url = f"{url}?{encode_params(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": _FALLBACK_UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _UrllibResponse(resp.status, resp.read())
        except urllib.error.HTTPError as exc:
            return _UrllibResponse(exc.code, exc.read())

    def close(self):
        pass


def encode_params(params) -> str:
    """Кодирует параметры, сохраняя повторяющиеся ключи вида slug[]."""
    from urllib.parse import quote

    parts = []
    items = params.items() if hasattr(params, "items") else params
    for key, value in items:
        if isinstance(value, (list, tuple)):
            for item in value:
                parts.append(f"{quote(str(key))}={quote(str(item))}")
        else:
            parts.append(f"{quote(str(key))}={quote(str(value))}")
    return "&".join(parts)


class Client:
    """Потокобезопасный HTTP-клиент с ретраями и экспоненциальным backoff.

    Сессия создаётся отдельно для каждого потока: сессии curl_cffi не
    рассчитаны на параллельное использование из нескольких потоков.
    """

    #: Статусы, по которым прогон останавливается сразу, без ретраев.
    block_statuses: frozenset[int] = frozenset()

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        timeout: int = TIMEOUT,
        headers: dict[str, str] | None = None,
    ):
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.headers = dict(headers or {})
        self._local = threading.local()
        self._sessions: list[Any] = []
        self._lock = threading.Lock()
        self.backend = "?"

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            session, backend = _make_session()
            self._local.session = session
            self.backend = backend
            with self._lock:
                self._sessions.append(session)
        return session

    def get(self, url: str, params=None, headers: dict[str, str] | None = None) -> Any:
        """GET с ретраями. Возвращает объект ответа; кидает HttpError."""
        last_error = "unknown"
        last_status: int | None = None
        request_headers = {**self.headers, **(headers or {})}

        for attempt in range(1, self.max_attempts + 1):
            try:
                if params is not None:
                    full_url = f"{url}?{encode_params(params)}"
                else:
                    full_url = url
                resp = self._session().get(
                    full_url, timeout=self.timeout, headers=request_headers or None
                )
                status = resp.status_code

                if status == 200:
                    return resp
                if status in self.block_statuses:
                    raise Blocked(
                        f"HTTP {status} — доступ закрыт (Cloudflare): {url}", status=status
                    )
                if status == 404:
                    # Ретраить бессмысленно — главы просто нет.
                    raise HttpError(f"HTTP 404 {url}", status=404)
                if status == 429 or status >= 500:
                    last_status = status
                    last_error = f"HTTP {status}"
                else:
                    raise HttpError(f"HTTP {status} {url}", status=status)
            except HttpError:
                raise
            except Exception as exc:  # сетевые сбои, таймауты, TLS
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.max_attempts:
                delay = (2**attempt) + random.uniform(0, 0.5)
                log.debug("retry %s/%s in %.1fs (%s)", attempt, self.max_attempts, delay, last_error)
                time.sleep(delay)

        raise HttpError(f"{last_error} после {self.max_attempts} попыток: {url}", status=last_status)

    def get_json(self, path: str, params=None) -> Any:
        url = path if path.startswith("http") else f"{API}{path}"
        resp = self.get(url, params)
        try:
            return resp.json()
        except Exception as exc:
            raise HttpError(f"Невалидный JSON от {url}: {exc}") from exc

    def get_text(self, url: str, params=None, headers: dict[str, str] | None = None) -> str:
        return self.get(url, params, headers=headers).text

    def close(self):
        with self._lock:
            for session in self._sessions:
                try:
                    session.close()
                except Exception:
                    pass
            self._sessions.clear()


# Заголовки настоящего браузера: Cloudflare смотрит не только на TLS.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class SiteClient(Client):
    """Клиент витрины www.mvlempyr.io.

    Одна сессия на весь прогон: Cloudflare выдаёт куку доступа, её нужно
    переиспользовать между главами. Строго однопоточный — сессия одна, и
    параллелить запросы к витрине нельзя.

    403 и 429 не ретраятся: один блок означает остановку прогона.
    """

    block_statuses = frozenset({403, 429})

    def __init__(self, referer: str | None = None, **kwargs):
        headers = dict(BROWSER_HEADERS)
        if referer:
            headers["Referer"] = referer
        kwargs.setdefault("max_attempts", 2)  # сетевой сбой пережить, блок — нет
        super().__init__(headers=headers, **kwargs)

    def set_referer(self, referer: str) -> None:
        self.headers["Referer"] = referer


def chapter_url(novel_code: int, number: int) -> str:
    """Страница главы на витрине — единственный доступный источник текста."""
    return f"{SITE}/chapter/{novel_code}-{number}"


def novel_url(slug: str) -> str:
    return f"{SITE}/novel/{slug}"


def polite_pause():
    """Пауза между пачками запросов к API."""
    time.sleep(random.uniform(*PAUSE_RANGE))


def site_pause():
    """Пауза между главами на витрине: 2-4 секунды со случайным джиттером."""
    time.sleep(random.uniform(*SITE_PAUSE_RANGE))
