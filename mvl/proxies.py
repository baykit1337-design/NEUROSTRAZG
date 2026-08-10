"""Прокси для витрины: чтение списка, проверка живости, ранжирование.

Домен `www.mvlempyr.io` режется на уровне провайдера, поэтому запросы к нему
идут через прокси. К REST API это не относится — он доступен напрямую.

Пароли не должны попадать в логи. Любая строка, которая может уйти в лог или
в сообщение об ошибке, прогоняется через scrub().
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

PROXY_FILE = "proxies.txt"
CHECK_TIMEOUT = 8
CHECK_CONCURRENCY = 5  # разовая процедура; к скачиванию глав отношения не имеет
GEO_TIMEOUT = 5
GEO_URL = "http://ip-api.com/json/?fields=country,countryCode"

# ---------------------------------------------------------------- маскирование

_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()
_CREDENTIALS_RE = re.compile(r"://([^:/@\s]+):([^@/\s]+)@")
# Короткие пароли не запоминаем: подстрока вроде "p" встречается в любом
# тексте, и подстановочная замена изуродовала бы весь лог. Такие случаи
# закрывает маскирование по шаблону user:pass@host.
MIN_SECRET_LEN = 5


def remember_secret(value: str) -> None:
    """Запоминает пароль, чтобы вычищать его из любых строк."""
    if value and len(value) >= MIN_SECRET_LEN:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def scrub(text) -> str:
    """Убирает пароли из строки. Применять ко всему, что идёт в лог."""
    text = str(text)
    with _SECRETS_LOCK:
        secrets = sorted(_SECRETS, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, "***")
    return _CREDENTIALS_RE.sub(r"://\1:***@", text)


# --------------------------------------------------------------------- прокси


@dataclass
class Proxy:
    host: str
    port: int
    username: str = ""
    password: str = ""

    # Результаты проверки.
    alive: bool | None = None
    status: int | None = None
    elapsed: float | None = None
    country: str = ""
    error: str = ""

    # Состояние во время прогона.
    disabled: bool = False
    disabled_reason: str = ""

    @classmethod
    def parse(cls, line: str) -> Proxy | None:
        """`ip:port:username:password`, авторизация необязательна."""
        line = line.strip()
        if not line or line.startswith("#"):
            return None

        parts = line.split(":")
        if len(parts) not in (2, 4):
            raise ValueError(f"Строка не в формате ip:port:username:password: {line!r}")

        host, port = parts[0].strip(), parts[1].strip()
        if not host or not port.isdigit():
            raise ValueError(f"Плохой адрес прокси: {line!r}")

        username, password = (parts[2].strip(), parts[3].strip()) if len(parts) == 4 else ("", "")
        remember_secret(password)
        return cls(host=host, port=int(port), username=username, password=password)

    @property
    def label(self) -> str:
        """Адрес без учётных данных — для логов и интерфейса."""
        return f"{self.host}:{self.port}"

    @property
    def url(self) -> str:
        if self.username:
            return f"http://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def safe_url(self) -> str:
        if self.username:
            return f"http://{self.username}:***@{self.host}:{self.port}"
        return f"http://{self.host}:{self.port}"

    @property
    def usable(self) -> bool:
        """Прошёл проверку и не помечен непригодным во время прогона."""
        return bool(self.alive) and self.status == 200 and not self.disabled

    @property
    def reachable(self) -> bool:
        """Ответил хоть чем-то. 403 — «не проходит», но в запасе остаётся."""
        return bool(self.alive) and not self.disabled

    def __str__(self) -> str:
        return self.safe_url

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "safe_url": self.safe_url,
            "alive": self.alive,
            "status": self.status,
            "elapsed": round(self.elapsed, 2) if self.elapsed else None,
            "country": self.country,
            "error": scrub(self.error),
            "usable": self.usable,
            "disabled": self.disabled,
            "disabled_reason": scrub(self.disabled_reason),
        }


def load_proxies(path: str | Path) -> list[Proxy]:
    """Читает список из файла. Пустые строки и #-комментарии пропускает."""
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise FileNotFoundError(f"Файл со списком прокси не найден: {file_path}")

    proxies, problems = [], []
    for number, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            proxy = Proxy.parse(line)
        except ValueError as exc:
            problems.append(f"строка {number}: {exc}")
            continue
        if proxy:
            proxies.append(proxy)

    for problem in problems:
        log.warning("%s: %s", file_path.name, problem)
    if not proxies:
        raise ValueError(f"В {file_path} нет ни одного корректного прокси")
    return proxies


# --------------------------------------------------------------------- проверка


def short_reason(exc: Exception | str) -> str:
    """Короткая причина отказа вместо простыни от curl."""
    text = scrub(exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}")
    low = text.lower()

    if "timed out" in low or "timeout" in low:
        return "таймаут"
    if "proxy authentication" in low or "407" in low:
        return "прокси не принял логин/пароль"
    if "could not resolve" in low or "resolve host" in low:
        return "DNS не резолвится"
    if "connection reset" in low or "recv failure" in low:
        return "соединение сброшено"
    if "could not connect" in low or "connection refused" in low:
        return "не подключается"
    if "ssl" in low or "certificate" in low:
        return "ошибка TLS"
    # Отрезаем хвост со ссылкой на документацию curl.
    text = text.split(". See https://", 1)[0]
    return text[:80]


def check_proxy(proxy: Proxy, url: str | None = None, geo: bool = True) -> Proxy:
    """Один запрос к витрине через прокси. Результат кладёт в сам объект."""
    from .client import SITE, BROWSER_HEADERS

    target = url or f"{SITE}/"
    started = time.monotonic()
    try:
        from curl_cffi import requests as curl_requests

        with curl_requests.Session(
            impersonate="chrome", proxies={"http": proxy.url, "https": proxy.url}
        ) as session:
            response = session.get(target, headers=BROWSER_HEADERS, timeout=CHECK_TIMEOUT)
            proxy.elapsed = time.monotonic() - started
            proxy.status = response.status_code
            proxy.alive = True
            proxy.error = ""
    except ImportError:
        proxy.alive = False
        proxy.error = "нужен curl_cffi: pip install curl_cffi"
        return proxy
    except Exception as exc:
        proxy.elapsed = time.monotonic() - started
        proxy.alive = False
        proxy.status = None
        proxy.error = short_reason(exc)
        return proxy

    if geo:
        proxy.country = _lookup_country(proxy)
    return proxy


def _lookup_country(proxy: Proxy) -> str:
    """Страна выходного узла. Не критично: не вышло — оставляем пустым."""
    try:
        from curl_cffi import requests as curl_requests

        with curl_requests.Session(
            impersonate="chrome", proxies={"http": proxy.url, "https": proxy.url}
        ) as session:
            data = session.get(GEO_URL, timeout=GEO_TIMEOUT).json()
        return str(data.get("countryCode") or data.get("country") or "")
    except Exception as exc:
        log.debug("Страну для %s определить не вышло: %s", proxy.label, scrub(exc))
        return ""


# ------------------------------------------------------------------------ пул


@dataclass
class SwitchEvent:
    from_label: str
    to_label: str
    reason: str


class NoProxiesLeft(RuntimeError):
    """Список кончился. Напрямую не идём — прямой путь заблокирован."""


class ProxyPool:
    """Список прокси: проверка, ранжирование, переключение по отказу."""

    def __init__(self, proxies: list[Proxy], source: str = ""):
        self.proxies = proxies
        self.source = source
        self.checked = False
        self.switches: list[SwitchEvent] = []
        # До проверки порядок — как в файле: пул должен быть пригоден к работе
        # и без предварительного check_all().
        self._order: list[Proxy] = list(proxies)
        self._current: Proxy | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path: str | Path) -> ProxyPool:
        return cls(load_proxies(path), source=str(path))

    def __len__(self) -> int:
        return len(self.proxies)

    # ------------------------------------------------------------- проверка

    def check_all(self, on_progress=None, geo: bool = True) -> list[Proxy]:
        """Проверяет весь список, до 5 проверок параллельно."""
        done = 0
        with ThreadPoolExecutor(max_workers=CHECK_CONCURRENCY) as pool:
            for _ in pool.map(lambda p: check_proxy(p, geo=geo), self.proxies):
                done += 1
                if on_progress:
                    on_progress(done, len(self.proxies))

        self.checked = True
        self._rank()
        return self.results()

    def _rank(self) -> None:
        """Пригодные — по возрастанию отклика. 403 — в конец, про запас."""
        usable = sorted(
            (p for p in self.proxies if p.usable), key=lambda p: p.elapsed or 1e9
        )
        fallback = sorted(
            (p for p in self.proxies if p.reachable and not p.usable),
            key=lambda p: p.elapsed or 1e9,
        )
        with self._lock:
            self._order = usable + fallback
            if self._current not in self._order:
                self._current = None

    def results(self) -> list[Proxy]:
        """Все прокси в порядке: пригодные, запасные, мёртвые."""
        rank = {id(p): i for i, p in enumerate(self._order)}
        return sorted(self.proxies, key=lambda p: rank.get(id(p), len(self._order)))

    def table(self) -> str:
        """Таблица результатов проверки. Пароли замаскированы."""
        rows = [f"{'адрес':<24}{'страна':<8}{'отклик':>8}  статус"]
        for proxy in self.results():
            elapsed = f"{proxy.elapsed:.2f} с" if proxy.elapsed else "—"
            if proxy.alive and proxy.status == 200:
                status = "OK"
            elif proxy.alive and proxy.status == 403:
                status = "403, не проходит"
            elif proxy.alive:
                status = f"HTTP {proxy.status}"
            else:
                status = proxy.error or "не отвечает"
            rows.append(f"{proxy.label:<24}{proxy.country or '—':<8}{elapsed:>8}  {status}")
        return "\n".join(rows)

    # --------------------------------------------------------- переключение

    @property
    def usable_count(self) -> int:
        return sum(1 for p in self.proxies if p.usable)

    def current(self) -> Proxy:
        """Текущий прокси. Если не выбран — берёт самый быстрый пригодный."""
        with self._lock:
            if self._current is not None and not self._current.disabled:
                return self._current
            for proxy in self._order:
                if not proxy.disabled:
                    self._current = proxy
                    return proxy
        raise NoProxiesLeft(self.failure_report())

    def switch(self, reason: str) -> Proxy:
        """Помечает текущий непригодным и берёт следующий по скорости."""
        with self._lock:
            previous = self._current
            if previous is None:
                # switch() позвали до current(): в работе был первый по порядку,
                # именно его и надо пометить непригодным.
                previous = next((p for p in self._order if not p.disabled), None)
            if previous is not None:
                previous.disabled = True
                previous.disabled_reason = scrub(reason)

            following = None
            for proxy in self._order:
                if not proxy.disabled:
                    following = proxy
                    break
            self._current = following

        if following is None:
            log.error("Прокси кончились: %s", scrub(reason))
            raise NoProxiesLeft(self.failure_report())

        event = SwitchEvent(
            from_label=previous.label if previous else "—",
            to_label=following.label,
            reason=scrub(reason),
        )
        self.switches.append(event)
        log.warning(
            "Прокси %s отвалился (%s), переходим на %s",
            event.from_label,
            event.reason,
            event.to_label,
        )
        return following

    def failure_report(self) -> str:
        """Что и с каким статусом не подошло."""
        lines = ["Рабочих прокси не осталось. Прямой путь заблокирован, идти напрямую не будем.", ""]
        for proxy in self.results():
            if proxy.disabled:
                why = proxy.disabled_reason or "помечен непригодным"
            elif proxy.alive and proxy.status != 200:
                why = f"HTTP {proxy.status}"
            elif not proxy.alive:
                why = proxy.error or "не отвечает"
            else:
                why = "не использовался"
            lines.append(f"  {proxy.label:<24} {scrub(why)}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "checked": self.checked,
            "total": len(self.proxies),
            "usable": self.usable_count,
            "current": self._current.label if self._current else None,
            "switches": len(self.switches),
            "proxies": [p.to_dict() for p in self.results()],
        }
