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
#: Страница главы весит ~220 КБ и на медленном канале не успевает прийти за
#: 30 секунд — обрыв случался на ~22 КБ. Cloudflare тут ни при чём.
TIMEOUT = 120
#: Соединение либо устанавливается быстро, либо адрес недоступен — ждать
#: столько же, сколько тело ответа, незачем.
CONNECT_TIMEOUT = 15

#: Признаки того, что ответ оборвался на середине, а не «сайт не ответил».
#: Диагноз другой, поэтому и в лог пишется другое.
INCOMPLETE_MARKERS = (
    "partial", "incomplete", "truncated", "transfer closed",
    "connection reset", "chunked", "recv failure",
)

log = logging.getLogger(__name__)


class HttpError(Exception):
    """Запрос не удался после всех попыток."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Blocked(HttpError):
    """Доступ закрыт (403) или пришла заглушка Cloudflare.

    Этот выходной узел до сайта не пропускают — пробуем другую географию.
    Ретраить на том же адресе бессмысленно.
    """


class RateLimited(HttpError):
    """HTTP 429 — «слишком часто», а не «тебе сюда нельзя».

    Прокси менять нельзя: смена адреса только расширит проблему на весь
    диапазон. Правильная реакция — увеличить паузу и подождать.
    """


class NetworkError(HttpError):
    """Таймаут, connection reset/refused, DNS, ошибка авторизации на прокси."""


def _make_session(proxy_url: str | None = None):
    """Сессия curl_cffi, либо requests, либо тонкая обёртка над urllib."""
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None

    try:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(impersonate="chrome", proxies=proxies)
        return session, "curl_cffi"
    except ImportError:
        pass

    try:
        import requests

        session = requests.Session()
        session.headers.update({"User-Agent": _FALLBACK_UA})
        if proxies:
            session.proxies.update(proxies)
        return session, "requests"
    except ImportError:
        if proxies:
            raise RuntimeError("Для работы через прокси нужен curl_cffi") from None
        return _UrllibSession(), "urllib"


_FALLBACK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class _UrllibResponse:
    def __init__(self, status: int, body: bytes, headers: dict | None = None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}

    @property
    def content(self) -> bytes:
        return self._body

    @property
    def text(self) -> str:
        return self._body.decode("utf-8", "replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class _UrllibSession:
    """Последний рубеж: стандартная библиотека, без внешних зависимостей."""

    def get(self, url: str, params=None, timeout=TIMEOUT, **_):
        import urllib.error
        import urllib.request

        # urllib умеет только один таймаут — берём тот, что на чтение.
        if isinstance(timeout, (tuple, list)):
            timeout = timeout[-1]

        if params:
            url = f"{url}?{encode_params(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": _FALLBACK_UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _UrllibResponse(resp.status, resp.read(), dict(resp.headers))
        except urllib.error.HTTPError as exc:
            return _UrllibResponse(exc.code, exc.read(), dict(exc.headers or {}))

    def close(self):
        pass


def _body_length(resp) -> int | None:
    """Сколько байт реально пришло. None, если тело недоступно."""
    for attribute in ("content", "_body"):
        body = getattr(resp, attribute, None)
        if isinstance(body, (bytes, bytearray)):
            return len(body)
    text = getattr(resp, "text", None)
    return len(text.encode("utf-8", "replace")) if isinstance(text, str) else None


def _incomplete(resp) -> str | None:
    """Сверяет Content-Length с тем, что пришло.

    Возвращает готовую строку для лога или None, если ответ целый.
    """
    headers = getattr(resp, "headers", None) or {}
    try:
        declared = int(headers.get("Content-Length") or headers.get("content-length") or 0)
    except (TypeError, ValueError):
        return None
    if declared <= 0:
        return None
    # Сжатый ответ распаковывается, и длина законно расходится с заголовком.
    encoding = str(headers.get("Content-Encoding") or headers.get("content-encoding") or "")
    if encoding.strip():
        return None

    received = _body_length(resp)
    if received is None or received >= declared:
        return None
    return f"получено {received} байт из {declared}, ответ неполный"


def _describe(exc: Exception) -> str:
    """Отличает оборванный ответ от обычного таймаута — диагноз разный."""
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if any(marker in low for marker in INCOMPLETE_MARKERS):
        received = getattr(exc, "received", None) or getattr(exc, "partial", None)
        size = f"получено {len(received)} байт, " if isinstance(received, (bytes, str)) else ""
        return f"{size}ответ неполный ({text})"
    return text


def _scrub(text) -> str:
    """Убирает пароли прокси из строки перед логированием."""
    from .proxies import scrub

    return scrub(text)


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

    #: Статусы, по которым сразу отдаём Blocked — без ретраев.
    block_statuses: frozenset[int] = frozenset()
    #: Отдавать ли RateLimited на 429 вместо ретрая с backoff.
    raise_on_rate_limit: bool = False

    def __init__(
        self,
        max_attempts: int = MAX_ATTEMPTS,
        timeout: int = TIMEOUT,
        headers: dict[str, str] | None = None,
        proxy_url: str | None = None,
        connect_timeout: int = CONNECT_TIMEOUT,
        shared_session: bool = False,
        cancel: threading.Event | None = None,
    ):
        #: Флажок остановки прогона. Между попытками клиент ждёт секунды —
        #: при трёх попытках это шесть, а с подменой прокси и того больше.
        #: Без этого флажка «Остановить» замечалось только на следующей
        #: главе, и кнопка выглядела сломанной.
        self.cancel = cancel
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.headers = dict(headers or {})
        self.proxy_url = proxy_url
        #: Одна сессия на все потоки вместо своей на поток. Некоторые
        #: серверы охотнее отвечают на переиспользуемое соединение —
        #: автопроба перебирает оба способа и оставляет рабочий.
        self.shared_session = shared_session
        self._local = threading.local()
        self._shared: Any = None
        self._sessions: list[Any] = []
        self._lock = threading.Lock()
        self.backend = "?"

    def _session(self):
        if self.shared_session:
            with self._lock:
                if self._shared is None:
                    self._shared, self.backend = _make_session(self.proxy_url)
                    self._sessions.append(self._shared)
                return self._shared

        session = getattr(self._local, "session", None)
        if session is None:
            session, backend = _make_session(self.proxy_url)
            self._local.session = session
            self.backend = backend
            with self._lock:
                self._sessions.append(session)
        return session

    def _stopping(self) -> bool:
        """Попросили остановиться."""
        return self.cancel is not None and self.cancel.is_set()

    def _wait(self, seconds: float) -> bool:
        """Пауза между попытками. True — прервали, ждать больше не надо.

        Обычный `time.sleep` тут держал прогон до конца лесенки ретраев:
        нажатие «Остановить» замечалось только на следующей главе.
        """
        if self.cancel is None:
            time.sleep(seconds)
            return False
        return self.cancel.wait(seconds)

    def get(self, url: str, params=None, headers: dict[str, str] | None = None) -> Any:
        """GET с ретраями. Возвращает объект ответа; кидает HttpError."""
        last_error = "unknown"
        last_status: int | None = None
        network_failure = False
        tried = 0
        request_headers = {**self.headers, **(headers or {})}

        for attempt in range(1, self.max_attempts + 1):
            if self._stopping():
                # Останавливаемся, не начиная новую попытку: смысла в ней
                # нет, а прогон ждёт её до самого таймаута.
                break
            tried = attempt
            try:
                if params is not None:
                    full_url = f"{url}?{encode_params(params)}"
                else:
                    full_url = url
                resp = self._session().get(
                    full_url,
                    # (на соединение, на чтение) — обрыв тела и недоступный
                    # адрес это разные беды с разными сроками ожидания.
                    timeout=(self.connect_timeout, self.timeout),
                    headers=request_headers or None,
                )
                status = resp.status_code
                network_failure = False

                if status == 200:
                    short = _incomplete(resp)
                    if short:
                        # Не «таймаут»: соединение было, ответ пришёл рваным.
                        network_failure = True
                        last_error = short
                        log.warning("%s: %s", url, short)
                    else:
                        return resp
                if status in self.block_statuses:
                    raise Blocked(f"HTTP {status} — доступ закрыт: {url}", status=status)
                if status in (407, 502, 503) and self.proxy_url:
                    # Прокси не пропустил запрос — дело в нём, а не в сайте.
                    raise NetworkError(f"прокси ответил HTTP {status}", status=status)
                if status == 429 and self.raise_on_rate_limit:
                    raise RateLimited(f"HTTP 429 — слишком часто: {url}", status=429)
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
            except Exception as exc:  # сетевые сбои, таймауты, TLS, прокси
                network_failure = True
                last_error = _scrub(_describe(exc))

            if attempt < self.max_attempts:
                delay = (2**attempt) + random.uniform(0, 0.5)
                log.debug("retry %s/%s in %.1fs (%s)", attempt, self.max_attempts, delay, last_error)
                if self._wait(delay):
                    break

        if self._stopping():
            # Число попыток тут ни при чём: мы прервались сами. Врать про
            # «после трёх попыток» не надо — по журналу потом не понять,
            # остановили прогон или он сдался.
            raise NetworkError(f"остановлено: {url}", status=last_status)

        message = f"{last_error} после {tried} попыток: {url}"
        if network_failure:
            raise NetworkError(message, status=last_status)
        raise HttpError(message, status=last_status)

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
            self._shared = None


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

    Одна сессия на весь прогон и на один прокси: кука Cloudflare привязана к
    IP, поэтому при смене прокси нужна новая сессия. Строго однопоточный —
    параллелить запросы к витрине нельзя, даже через прокси.

    403 отдаётся как Blocked (меняем прокси), 429 — как RateLimited
    (прокси не меняем, ждём).
    """

    block_statuses = frozenset({403})
    raise_on_rate_limit = True

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
