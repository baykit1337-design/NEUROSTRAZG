"""Многопоточное скачивание с автопробой способа.

Многопоточность заявлена не первый раз, но по факту главы нередко идут по
очереди: сайт отвечает 403 на параллельные запросы, и код молча падает в
последовательный режим. Здесь способ подбирается заранее — маленьким
пробным прогоном, до основного.

Модуль ничего не знает ни о витрине, ни о файлах: качать одну главу и
создавать клиента ему передают снаружи. Поэтому его можно проверить без
интернета.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from config import settings

log = logging.getLogger(__name__)

#: Способы по порядку из ТЗ. Последовательный работает всегда — он замыкает
#: список и никогда не проверяется пробой.
OWN_SESSION = "threads_own_session"
SHARED_SESSION = "threads_shared_session"
PROXY_PER_THREAD = "threads_proxy_per_thread"
ASYNC = "async"
SEQUENTIAL = "sequential"

METHODS = (OWN_SESSION, SHARED_SESSION, PROXY_PER_THREAD, ASYNC, SEQUENTIAL)

#: Как называть способ в интерфейсе.
NAMES = {
    OWN_SESSION: "потоки, своя сессия на поток",
    SHARED_SESSION: "потоки, общая сессия",
    PROXY_PER_THREAD: "потоки, свой прокси на поток",
    ASYNC: "асинхронный режим",
    SEQUENTIAL: "последовательно",
}


class ProbeFailed(Exception):
    """Способ не прошёл пробу. Причина — в тексте."""


@dataclass
class Attempt:
    """Итог пробы одного способа — целиком, чтобы было что показать."""

    method: str
    ok: bool = False
    reason: str = ""
    seconds: float = 0.0
    #: Оценка последовательного времени: самая быстрая глава × их число.
    expected: float = 0.0
    speedup: float = 0.0
    proxies: int = 0

    @property
    def name(self) -> str:
        return NAMES.get(self.method, self.method)

    def as_dict(self) -> dict:
        return {
            "method": self.method, "name": self.name, "ok": self.ok,
            "reason": self.reason, "seconds": round(self.seconds, 2),
            "speedup": round(self.speedup, 2), "proxies": self.proxies,
        }


@dataclass
class ProbeReport:
    """Что выбрали и почему. Интерфейсу нужен и итог, и путь к нему."""

    method: str = SEQUENTIAL
    threads: int = 1
    proxies: int = 0
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def parallel(self) -> bool:
        return self.method != SEQUENTIAL

    @property
    def message(self) -> str:
        """Уведомление внизу справа — короткое, без подробностей."""
        if not self.parallel:
            return "Многопоточность недоступна. Скачивание идёт по очереди."
        if self.method == PROXY_PER_THREAD:
            return (f"Качаем в {self.threads} потока через {self.proxies} "
                    f"{_plural(self.proxies)}.")
        return f"Качаем в {self.threads} потока."

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "name": NAMES.get(self.method, self.method),
            "threads": self.threads,
            "proxies": self.proxies,
            "parallel": self.parallel,
            "message": self.message,
            "attempts": [a.as_dict() for a in self.attempts],
        }


def _plural(count: int) -> str:
    tail = count % 10
    if count % 100 in range(11, 15) or tail == 0 or tail >= 5:
        return "адресов"
    return "адрес" if tail == 1 else "адреса"


def order_methods(last: str = "") -> list[str]:
    """Способы по порядку; сработавший в прошлый раз идёт первым."""
    methods = [m for m in METHODS if m != SEQUENTIAL]
    if last in methods:
        methods.remove(last)
        methods.insert(0, last)
    return methods


class Fetcher:
    """Раздаёт клиентов потокам по выбранному способу.

    Своя сессия на поток получается сама: `Client` держит сессии в
    thread-local. Общая сессия и свой прокси на поток — отдельные
    настройки, ради которых и существует этот класс.
    """

    def __init__(self, method: str, make_client, proxies: list | None = None):
        self.method = method
        self.make_client = make_client
        self.proxies = list(proxies or [])
        self._local = threading.local()
        self._clients: list = []
        self._lock = threading.Lock()
        self._next = 0

    def client(self):
        """Клиент текущего потока."""
        if self.method == SHARED_SESSION:
            with self._lock:
                if not self._clients:
                    self._clients.append(self.make_client(shared_session=True))
                return self._clients[0]

        client = getattr(self._local, "client", None)
        if client is None:
            proxy_url = None
            if self.method == PROXY_PER_THREAD and self.proxies:
                # Кука Cloudflare привязана к адресу, поэтому у каждого
                # потока свой: нагрузка на адрес втрое ниже.
                with self._lock:
                    proxy = self.proxies[self._next % len(self.proxies)]
                    self._next += 1
                proxy_url = getattr(proxy, "url", proxy)
            client = self.make_client(proxy_url=proxy_url)
            self._local.client = client
            with self._lock:
                self._clients.append(client)
        return client

    def close(self) -> None:
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 — закрытие не должно ломать прогон
                    pass
            self._clients.clear()


def probe_method(method: str, chapters, make_client, fetch, threads: int,
                 proxies: list | None = None, speedup: float | None = None,
                 cancel: threading.Event | None = None) -> Attempt:
    """Пробует один способ на нескольких главах.

    Успех — только если выполнено всё: главы пришли, текст непустой, ни
    одного отказа, и пачка обогнала последовательное скачивание заметно, а
    не на проценты.
    """
    speedup = settings.threads.probe_speedup if speedup is None else speedup
    attempt = Attempt(method=method)

    if method == PROXY_PER_THREAD:
        attempt.proxies = len(proxies or [])
        if attempt.proxies < 2:
            attempt.reason = "нужно хотя бы два прокси"
            return attempt

    fetcher = Fetcher(method, make_client, proxies)
    durations: list[float] = []
    started = time.monotonic()

    def one(chapter):
        if cancel is not None and cancel.is_set():
            raise ProbeFailed("остановлено")
        begin = time.monotonic()
        text = fetch(fetcher.client(), chapter)
        spent = time.monotonic() - begin
        if not (text or "").strip():
            raise ProbeFailed(f"глава {getattr(chapter, 'number', '?')} пришла пустой")
        return spent

    try:
        if method == ASYNC:
            durations = _run_async(chapters, one, threads)
        else:
            with ThreadPoolExecutor(max_workers=threads) as pool:
                futures = [pool.submit(one, chapter) for chapter in chapters]
                for future in as_completed(futures):
                    durations.append(future.result())
    except ProbeFailed as exc:
        attempt.reason = str(exc)
        return attempt
    except Exception as exc:  # noqa: BLE001 — любая осечка отбраковывает способ
        attempt.reason = _reason(exc)
        return attempt
    finally:
        fetcher.close()

    attempt.seconds = time.monotonic() - started
    if not durations:
        attempt.reason = "нечего было качать"
        return attempt

    # Оценка последовательного времени: самая быстрая глава показывает, во
    # что обходится один запрос без соседей.
    attempt.expected = min(durations) * len(durations)
    attempt.speedup = attempt.expected / attempt.seconds if attempt.seconds else 0.0
    if attempt.speedup < speedup:
        attempt.reason = (f"быстрее лишь в {attempt.speedup:.1f} раза, "
                          f"нужно от {speedup:g}")
        return attempt

    attempt.ok = True
    return attempt


def _reason(exc: BaseException) -> str:
    """Короткая причина отказа. 403 и 429 называем прямо."""
    status = getattr(exc, "status", None)
    if status in (403, 429):
        return f"сайт ответил {status}"
    from mvl.proxies import scrub

    return scrub(f"{type(exc).__name__}: {exc}")


def _run_async(chapters, one, threads: int) -> list[float]:
    """Асинхронный прогон. Ограничение — семафором, а не числом задач."""
    import asyncio

    async def main():
        limit = asyncio.Semaphore(threads)
        loop = asyncio.get_running_loop()

        async def task(chapter):
            async with limit:
                return await loop.run_in_executor(None, one, chapter)

        return await asyncio.gather(*(task(c) for c in chapters))

    return list(asyncio.run(main()))


def autoprobe(chapters, make_client, fetch, threads: int | None = None,
              proxies: list | None = None, last: str | None = None,
              cancel: threading.Event | None = None, on_step=None) -> ProbeReport:
    """Подбирает способ скачивания до основного прогона.

    Перебирает способы по порядку и останавливается на первом, прошедшем
    пробу. Если не прошёл ни один — последовательный режим: он работает
    всегда, и прогон из-за этого не отменяется.
    """
    threads = threads or settings.threads.probe_threads
    last = settings.last_download_method if last is None else last
    report = ProbeReport(threads=threads, proxies=len(proxies or []))

    if not chapters:
        return report

    for method in order_methods(last):
        if cancel is not None and cancel.is_set():
            break
        if on_step:
            on_step(NAMES.get(method, method))

        attempt = probe_method(method, chapters, make_client, fetch, threads,
                               proxies=proxies, cancel=cancel)
        report.attempts.append(attempt)
        log.info("Проба «%s»: %s", attempt.name,
                 "прошла" if attempt.ok else attempt.reason)

        if attempt.ok:
            report.method = method
            report.proxies = attempt.proxies
            return report

    report.method = SEQUENTIAL
    report.threads = 1
    return report


def remember(method: str) -> None:
    """Запоминает рабочий способ: в следующий раз он пробуется первым."""
    if method == settings.last_download_method:
        return
    settings.last_download_method = method
    try:
        settings.save()
    except OSError as exc:
        # Не смогли записать настройки — это не повод ронять скачивание.
        log.warning("Не удалось запомнить способ скачивания: %s", exc)
