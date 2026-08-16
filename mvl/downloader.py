"""Оркестрация скачивания: пачки, кэш, докачка, отчёт."""

from __future__ import annotations

import json
import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import api
from .client import (
    SITE_PAUSE_RANGE,
    Blocked,
    Client,
    HttpError,
    NetworkError,
    RateLimited,
    SiteClient,
    site_pause,
)
from .paths import chapter_filename, write_chapter
from .proxies import NoProxiesLeft, ProxyPool, scrub

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from ops.base import Cancelled as OpCancelled  # noqa: E402

log = logging.getLogger(__name__)

#: Потолок числа потоков. Выше не поднимаем даже вручную.
MAX_THREADS = 6
#: Пауза между пачками при параллельном скачивании (не между главами).
BATCH_PAUSE_RANGE = (1.0, 2.0)

STATE_FILE = "state.json"
ERROR_LOG = "errors.log"
STATE_VERSION = 1

# 429 — «слишком часто»: ждём столько секунд и повторяем на том же прокси.
RATE_LIMIT_COOLDOWN = 60
MAX_RATE_LIMIT_STREAK = 3


@dataclass
class Progress:
    # idle | search | toc | download | done | blocked | cancelled | error
    stage: str = "idle"
    message: str = ""
    done: int = 0
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    #: Через какой прокси идёт работа и сколько было переключений.
    proxy: str = ""
    switches: int = 0
    #: Сколько потоков и прокси реально работают. Показывается в блоке
    #: результата только когда потоков больше одного: «1 поток» сообщать
    #: незачем, а число прокси там, где сеть не используется, — тем более.
    threads: int = 1
    proxies: int = 0
    #: Итог автопробы способа скачивания — интерфейс показывает его
    #: уведомлением внизу справа.
    probe: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    novel: dict = field(default_factory=dict)
    output_dir: str = ""
    mode: str = ""
    requested: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    failed_chapters: list[int] = field(default_factory=list)
    missing_in_toc: list[int] = field(default_factory=list)
    #: Номер главы, на которой сайт закрыл доступ и прогон остановился.
    blocked_at: int | None = None
    #: Почему прогон остановился досрочно (кончились прокси, серия 429).
    stopped_reason: str = ""
    #: Сколько потоков работало и не пришлось ли снизить их до одного.
    threads: int = 1
    threads_downgraded: bool = False
    proxy: str = ""
    proxy_switches: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


class State:
    """state.json в папке книги: что уже скачано, что упало."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {
            "version": STATE_VERSION,
            "novel": {},
            "mode": "",
            "downloaded": {},
            "failed": {},
            "missing_in_toc": [],
            "updated_at": None,
        }
        self._lock = threading.Lock()
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("Битый %s (%s) — начинаем с чистого состояния", self.path.name, exc)
            return
        if isinstance(loaded, dict) and loaded.get("version") == STATE_VERSION:
            self.data.update(loaded)

    def save(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = self.path.with_suffix(".json.tmp")
        try:
            tmp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("Не удалось сохранить состояние: %s", exc)

    def is_done(self, number: int, output_dir: Path) -> bool:
        """Глава считается готовой, только если файл действительно на месте."""
        name = self.data["downloaded"].get(str(number))
        return bool(name) and (output_dir / name).exists()

    def mark_done(self, number: int, filename: str) -> None:
        with self._lock:
            self.data["downloaded"][str(number)] = filename
            self.data["failed"].pop(str(number), None)

    def mark_failed(self, number: int, reason: str) -> None:
        with self._lock:
            self.data["failed"][str(number)] = reason


class Downloader:
    """Скачивает главы книги в отдельные .txt.

    Оглавление берётся из REST API, текст — со страниц витрины: строго один
    поток, одна сессия на прогон, пауза 2-4 секунды между главами.

    Прерывание в любой момент безопасно: прогресс лежит в state.json, при
    следующем запуске готовые главы пропускаются. При блокировке (403/429)
    прогон останавливается целиком — ретраить бессмысленно.
    """

    def __init__(
        self,
        client: Client | None = None,
        site_client: Client | None = None,
        pool: ProxyPool | None = None,
        on_progress=None,
        cancel_event: threading.Event | None = None,
        threads: int = 1,
        probe: bool = True,
        source=None,
        on_event=None,
    ):
        self.client = client or Client()
        #: Откуда качаем. По умолчанию тот сайт, с которого всё начиналось,
        #: — иначе прежние вызовы пришлось бы править все разом.
        if source is None:
            from net.sources.mvlempyr import MvlempyrSource

            source = MvlempyrSource()
        self.source = source
        # Если сессию витрины передали снаружи, закрывать её мы не должны.
        self.site_client = site_client
        self.pool = pool
        self.on_progress = on_progress
        #: Куда писать построчный журнал прогона: раздачу прокси по
        #: потокам и смену адреса с причиной. Прогресс-бар говорит
        #: «сколько», а на вопрос «через что именно» отвечает журнал.
        self.on_event = on_event
        self.cancel = cancel_event or threading.Event()
        self.progress = Progress()
        #: Множитель паузы, растёт после каждого 429.
        self.pause_multiplier = 1.0
        #: Сколько глав качать одновременно. Выше MAX_THREADS не поднимаем:
        #: сайт не наш, заваливать его запросами не нужно.
        self.threads = max(1, min(int(threads or 1), MAX_THREADS))
        #: Подбирать ли способ многопоточности перед прогоном. Выключается
        #: в тестах, когда потоков всё равно один и когда пользователь
        #: выбрал ручной режим: он сам увидит по времени, работает или нет,
        #: и это надёжнее любой эвристики.
        self.probe = probe
        #: Итог автопробы — интерфейс показывает его уведомлением.
        self.probe_report = None
        #: state.json пишут все потоки — доступ к нему только под замком.
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------- служебное

    def _emit(self, **kwargs) -> None:
        for key, value in kwargs.items():
            setattr(self.progress, key, value)
        if self.on_progress:
            self.on_progress(self.progress)

    def _say(self, text: str, kind: str = "info") -> None:
        """Строка в журнал прогона. Без журнала — молча ничего."""
        if self.on_event:
            self.on_event(text, kind)

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    def _log_error(self, output_dir: Path, number: int, reason: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with (output_dir / ERROR_LOG).open("a", encoding="utf-8") as fh:
                fh.write(f"{stamp}\tглава {number}\t{reason}\n")
        except OSError as exc:
            log.warning("Не удалось записать в %s: %s", ERROR_LOG, exc)

    # ----------------------------------------------------------------- поиск

    def find(self, query: str) -> api.Novel:
        self._emit(stage="search", message=f"Ищем книгу: {query}")
        novel = self.source.find(self.client, query)
        self._emit(message=f"Найдено: {novel.name} ({novel.total_chapters} глав)")
        return novel

    # ------------------------------------------------------------- основное

    def run(
        self,
        novel: api.Novel,
        output_dir: Path,
        first: int = 1,
        last: int | None = None,
    ) -> Report:
        state = State(output_dir / STATE_FILE)
        state.data["novel"] = novel.to_dict()

        last = last or novel.total_chapters
        self._emit(stage="toc", message="Собираем оглавление…", done=0, total=last - first + 1)

        toc = self.source.toc(
            self.client,
            novel,
            first=first,
            last=last,
            on_progress=lambda d, t: self._emit(done=d, total=t),
        )
        self._check_cancel()

        state.data["missing_in_toc"] = toc.missing
        if toc.missing:
            self._log_error(
                output_dir, 0, f"нет в оглавлении: {_compact_ranges(toc.missing)}"
            )

        # Уже готовые главы не перекачиваем.
        pending = [ch for ch in toc.chapters if not state.is_done(ch.number, output_dir)]
        skipped = len(toc.chapters) - len(pending)
        state.data["mode"] = api.SOURCE_SITE
        state.save()

        minutes = int(len(pending) * sum(SITE_PAUSE_RANGE) / 2 / 60)
        self._emit(
            stage="download",
            message=(
                f"Качаем {len(pending)} глав с витрины, один поток. "
                f"Это примерно {minutes} мин."
            ),
            done=0,
            total=len(pending),
            skipped=skipped,
        )

        # Одна сессия на весь прогон и на один прокси: кука Cloudflare
        # привязана к IP, при смене адреса нужна новая сессия.
        site = self.site_client or self._new_session(novel)
        self._emit(proxy=self._proxy_label(), switches=self._switch_count())

        downloaded = 0
        failed: list[int] = []
        blocked_at: int | None = None
        stopped_reason = ""
        rate_limit_streak = 0
        threads_downgraded = False

        fetcher = None
        if self.threads > 1 and pending:
            if self.probe:
                # Подбираем способ до основного прогона: заявленная
                # многопоточность и работающая — разные вещи.
                fetcher = self._autoprobe(novel, pending)
            else:
                # Ручной режим пропускает пробу, но не раздачу клиентов.
                # Без неё все потоки делили одну сессию и один прокси, а
                # кука Cloudflare привязана к адресу — запросы вставали в
                # очередь на сайте, и «N потоков» оказывались одним.
                fetcher = self._manual_fetcher(novel)

        if self.threads > 1:
            # Пачками: смена прокси и повтор главы тут не делаются — по ТЗ
            # первый же 403 или 429 останавливает весь прогон.
            downloaded, failed, blocked_at, stopped_reason, threads_downgraded = (
                self._run_batches(pending, novel, output_dir, site, state, last,
                                  fetcher=fetcher)
            )
            if fetcher is not None:
                fetcher.close()
            state.save()
            if site is not self.site_client:
                site.close()
            return self._finish(
                novel, output_dir, toc, downloaded, skipped, failed,
                blocked_at, stopped_reason, threads_downgraded,
            )

        try:
            for index, chapter in enumerate(pending):
                self._check_cancel()
                outcome = "ok"

                # Одну и ту же главу повторяем при смене прокси и при 429.
                while True:
                    try:
                        self._one(chapter, novel, output_dir, site, state)
                        downloaded += 1
                        rate_limit_streak = 0
                        break

                    except RateLimited as exc:
                        # Прокси НЕ меняем: 429 — это «слишком часто», смена
                        # адреса только расширит проблему на весь диапазон.
                        rate_limit_streak += 1
                        if rate_limit_streak >= MAX_RATE_LIMIT_STREAK:
                            stopped_reason = (
                                f"три ответа 429 подряд на главе {chapter.number} — "
                                f"сайт просит притормозить, прогон остановлен"
                            )
                            self._log_error(output_dir, chapter.number, stopped_reason)
                            outcome = "stop"
                            break

                        self.pause_multiplier *= 2
                        self._emit(
                            message=(
                                f"429 на главе {chapter.number}: ждём "
                                f"{RATE_LIMIT_COOLDOWN} с, паузу увеличили "
                                f"до x{self.pause_multiplier:g}"
                            )
                        )
                        self._log_error(output_dir, chapter.number, f"429, ждём: {exc}")
                        if self.cancel.wait(RATE_LIMIT_COOLDOWN):
                            raise Cancelled() from exc
                        continue

                    except (Blocked, NetworkError) as exc:
                        reason = scrub(str(exc))
                        if self.pool is None:
                            # Без прокси менять нечего — останавливаемся.
                            blocked_at = chapter.number
                            self._log_error(output_dir, chapter.number, f"БЛОКИРОВКА: {reason}")
                            state.mark_failed(chapter.number, reason)
                            outcome = "stop"
                            break

                        try:
                            new_proxy = self.pool.switch(reason)
                        except NoProxiesLeft as exhausted:
                            blocked_at = chapter.number
                            stopped_reason = scrub(str(exhausted))
                            self._log_error(output_dir, chapter.number, stopped_reason)
                            outcome = "stop"
                            break

                        self._log_error(
                            output_dir,
                            chapter.number,
                            f"смена прокси: {reason} → {new_proxy.label}",
                        )
                        if site is not self.site_client:
                            site.close()
                        site = self._new_session(novel)
                        self._emit(
                            proxy=self._proxy_label(),
                            switches=self._switch_count(),
                            message=(
                                f"Прокси сменён на {new_proxy.label}, "
                                f"повторяем главу {chapter.number}"
                            ),
                        )
                        continue  # ту же главу заново

                    except (HttpError, ValueError, OSError) as exc:
                        reason = scrub(f"{type(exc).__name__}: {exc}")
                        log.warning("Глава %s не скачана: %s", chapter.number, reason)
                        state.mark_failed(chapter.number, reason)
                        self._log_error(output_dir, chapter.number, reason)
                        failed.append(chapter.number)
                        break

                self._emit(
                    done=downloaded + len(failed),
                    downloaded=downloaded,
                    failed=len(failed),
                    message=f"Глава {chapter.number} из {last}",
                )
                state.save()

                if outcome == "stop":
                    break
                if index < len(pending) - 1:
                    self._pause()
        except Cancelled:
            state.save()
            self._emit(stage="cancelled", message="Остановлено. Прогресс сохранён — можно продолжить.")
            raise
        finally:
            state.save()
            if site is not self.site_client:
                site.close()

        return self._finish(
            novel, output_dir, toc, downloaded, skipped, failed,
            blocked_at, stopped_reason, threads_downgraded,
        )

    def _finish(
        self, novel, output_dir, toc, downloaded, skipped, failed,
        blocked_at, stopped_reason, threads_downgraded=False,
    ) -> Report:
        """Собирает отчёт и последнее сообщение — общее для обоих путей."""
        report = Report(
            novel=novel.to_dict(),
            output_dir=str(output_dir),
            mode=api.SOURCE_SITE,
            requested=len(toc.chapters) + len(toc.missing),
            downloaded=downloaded,
            skipped=skipped,
            failed=len(failed),
            failed_chapters=sorted(failed),
            missing_in_toc=toc.missing,
            blocked_at=blocked_at,
            stopped_reason=stopped_reason,
            proxy=self._proxy_label(),
            proxy_switches=self._switch_count(),
            threads=self.threads,
            threads_downgraded=threads_downgraded,
        )

        if blocked_at is not None or stopped_reason:
            self._emit(
                stage="blocked",
                message=stopped_reason
                or (
                    f"Сайт закрыл доступ на главе {blocked_at}. Прогон остановлен, "
                    f"скачано {downloaded}. Подождите и запустите снова — "
                    f"продолжит с этого места."
                ),
                downloaded=downloaded,
                skipped=skipped,
                failed=len(failed),
            )
        else:
            self._emit(
                stage="done",
                message=(
                    f"Готово. Скачано {downloaded}, пропущено (уже было) {skipped}, "
                    f"ошибок {len(failed)}."
                ),
                downloaded=downloaded,
                skipped=skipped,
                failed=len(failed),
            )
        return report

    # ------------------------------------------------------------ вспомогательное

    def _new_session(self, novel: api.Novel) -> SiteClient:
        """Новая сессия на текущий прокси."""
        proxy = self.pool.current() if self.pool else None
        if proxy is not None:
            log.info("Работаем через прокси %s", proxy.label)
        return SiteClient(
            referer=novel.page_url, proxy_url=proxy.url if proxy else None
        )

    def _proxy_label(self) -> str:
        if self.pool is None:
            return ""
        try:
            return self.pool.current().label
        except NoProxiesLeft:
            return ""

    def _switch_count(self) -> int:
        return len(self.pool.switches) if self.pool else 0

    def _pause(self) -> None:
        """Пауза между главами, с учётом накопленного множителя после 429."""
        if self.pause_multiplier <= 1:
            site_pause()
            return
        low, high = SITE_PAUSE_RANGE
        time.sleep(random.uniform(low, high) * self.pause_multiplier)

    def _make_site_client(self, novel: api.Novel):
        """Как заводить клиента витрины — одинаково для пробы и ручного."""
        def make_client(proxy_url=None, shared_session=False):
            return SiteClient(referer=novel.page_url, proxy_url=proxy_url,
                              shared_session=shared_session,
                              max_attempts=settings.threads.probe_attempts)

        return make_client

    def _manual_fetcher(self, novel: api.Novel):
        """Раздатчик клиентов для ручного режима, без пробы.

        Прокси раздаются по потокам, если их хватает: при восьми адресах и
        трёх потоках каждый поток работает со своего. Адресов меньше двух —
        у каждого потока хотя бы своя сессия.
        """
        from net import pool as netpool

        proxies = []
        if self.pool is not None:
            proxies = [p for p in self.pool.proxies if not p.disabled]

        # Единственный адрес — тоже адрес: раздача по потокам при нём
        # выдаёт его всем, и это правильно. Прежний порог «хотя бы два»
        # уводил такую настройку в прямое соединение, то есть прокси
        # просто не работал, а на Фанкью это ещё и утечка своего адреса.
        method = netpool.PROXY_PER_THREAD if proxies else netpool.OWN_SESSION
        asked = self.threads
        if proxies:
            self.threads = max(1, min(self.threads, len(proxies)))
        log.info("Ручной режим: %s потока, способ «%s», адресов %s",
                 self.threads, method, len(proxies))

        if proxies and self.threads < asked:
            # Прямая формулировка: молчаливое урезание потоков выглядит
            # как «настройка не работает».
            self._say(f"потоков {asked}, живых прокси {len(proxies)} — "
                      f"работаю в {self.threads} "
                      f"{netpool.threads_word(self.threads)}", "warn")
        else:
            self._say(f"качаем в {self.threads} "
                      f"{netpool.threads_word(self.threads)}"
                      + (f", адресов {len(proxies)}" if proxies
                         else ", без прокси"))
        return netpool.Fetcher(method, self._make_site_client(novel), proxies)

    def measure_threads(self, novel: api.Novel, chapters, count: int = 6):
        """Замер многопоточности на живых главах (часть 6 ТЗ).

        Ручной режим чинили вслепую: на живом сайте с прокси проверить
        параллельность было нечем, кроме прогона книги целиком. Здесь
        качаются несколько глав, ничего не сохраняется, а в отчёте видно,
        какой поток через какой адрес работал.
        """
        from net import pool as netpool

        proxies = []
        if self.pool is not None:
            proxies = [p for p in self.pool.proxies if not p.disabled]

        def fetch(client, chapter):
            return self.source.chapter(client, chapter)[1]

        return netpool.measure(
            list(chapters)[:max(2, int(count or 6))],
            self._make_site_client(novel), fetch,
            threads=self.threads, proxies=proxies, cancel=self.cancel,
        )

    def _autoprobe(self, novel: api.Novel, pending):
        """Пробный прогон: 5 глав в 3 потока, способы по порядку из ТЗ.

        Возвращает раздатчика клиентов для выбранного способа либо None,
        если параллельно не вышло ни одним — тогда качаем по очереди.
        Прогон из-за неудачной пробы не отменяется.
        """
        from net import pool as netpool

        sample = pending[:settings.threads.probe_chapters]
        proxies = []
        if self.pool is not None:
            proxies = [p for p in self.pool.proxies if not p.disabled]

        make_client = self._make_site_client(novel)

        def fetch(client, chapter):
            return self.source.chapter(client, chapter)[1]

        self._emit(stage="probe", message="Подбираем способ скачивания…")
        report = netpool.autoprobe(
            sample, make_client, fetch,
            threads=min(self.threads, settings.threads.probe_threads),
            proxies=proxies,
            cancel=self.cancel,
            on_step=lambda name: self._emit(message=f"Пробуем: {name}…"),
        )
        self._check_cancel()

        self.probe_report = report
        self._emit(probe=report.as_dict(), message=report.message)

        if not report.parallel:
            # Последовательный режим работает всегда — это не ошибка.
            self.threads = 1
            log.info("Многопоточность недоступна, качаем по очереди")
            return None

        netpool.remember(report.method)
        # Адресов может оказаться меньше, чем потоков, — проба это учла.
        self.threads = max(1, min(self.threads, report.threads))
        return netpool.Fetcher(report.method, make_client, proxies)

    def _run_batches(self, pending, novel, output_dir, site, state, last,
                     fetcher=None):
        """Качает главы пачками по числу потоков.

        Своя сессия у каждого потока получается сама: `Client` держит сессии
        в thread-local, поэтому куки Cloudflare переиспользуются в пределах
        потока и не мешают друг другу.

        Порядок записи файлов не зависит от порядка ответов: каждая глава
        пишет свой файл, а прогресс считает завершённые.
        """
        downloaded = 0
        failed: list[int] = []
        blocked_at: int | None = None
        stopped_reason = ""

        # Многопоточность действительно включилась — говорим, сколько
        # потоков и прокси работают. В один поток эта строка не рисуется.
        usable = self.pool.usable_count if self.pool is not None else 0
        self._emit(
            stage="download",
            message=f"Качаем {len(pending)} глав в {self.threads} потока…",
            done=0, total=len(pending),
            threads=self.threads, proxies=usable,
        )

        paid = 0
        for start in range(0, len(pending), self.threads):
            self._check_cancel()
            batch = pending[start:start + self.threads]

            with ThreadPoolExecutor(max_workers=self.threads) as pool:
                futures = {
                    pool.submit(self._one_guarded, chapter, novel, output_dir,
                                site, state, fetcher): chapter
                    for chapter in batch
                }
                for future in as_completed(futures):
                    chapter = futures[future]
                    error = future.result()

                    if error is None:
                        downloaded += 1
                    elif _is_paid(error):
                        # Платную главу мы не трогаем. Это не осечка: она
                        # не станет доступной от повторной попытки, и в
                        # «не скачано» ей не место.
                        paid += 1
                        with self._state_lock:
                            state.mark_failed(chapter.number, str(error))
                        self._log_error(output_dir, chapter.number, str(error))
                    elif _is_refusal(error):
                        # Первый же отказ останавливает весь прогон, в каком
                        # бы потоке он ни случился.
                        blocked_at = chapter.number
                        stopped_reason = (
                            f"сайт ответил отказом на главе {chapter.number} "
                            f"({scrub(str(error))}). Прогон остановлен, "
                            f"следующий запуск пойдёт в один поток."
                        )
                        self._log_error(output_dir, chapter.number, stopped_reason)
                    else:
                        reason = scrub(f"{type(error).__name__}: {error}")
                        log.warning("Глава %s не скачана: %s", chapter.number, reason)
                        with self._state_lock:
                            state.mark_failed(chapter.number, reason)
                        self._log_error(output_dir, chapter.number, reason)
                        failed.append(chapter.number)

                    self._emit(
                        done=downloaded + len(failed) + paid,
                        downloaded=downloaded,
                        failed=len(failed),
                        message=(f"Глава {chapter.number} из {last}"
                                 + (f" · платных пропущено {paid}" if paid else "")),
                    )

            with self._state_lock:
                state.save()

            if blocked_at is not None:
                # Потоки снижаем до одного для следующего запуска.
                self.threads = 1
                return downloaded, failed, blocked_at, stopped_reason, True

            if start + self.threads < len(pending):
                # Пауза между пачками, а не между каждой главой.
                low, high = BATCH_PAUSE_RANGE
                if self.cancel.wait(random.uniform(low, high) * self.pause_multiplier):
                    raise Cancelled()

        return downloaded, failed, blocked_at, stopped_reason, False

    def _one_guarded(self, chapter, novel, output_dir, site, state, fetcher=None):
        """`_one` для потока: исключение возвращается, а не улетает наверх."""
        if self.cancel.is_set():
            return Cancelled()
        try:
            # Клиента даёт раздатчик выбранного способа: общая сессия или
            # свой прокси на поток задаются именно там.
            self._one(chapter, novel, output_dir,
                      fetcher.client() if fetcher else site, state)
            return None
        except (Blocked, NetworkError) as exc:
            # Отвалился прокси этого потока — берём следующий свободный и
            # повторяем ту же главу. Отказ сайта (403/429) это не лечит:
            # его разбирает вызывающий и останавливает весь прогон.
            replacement = self._swap_proxy(fetcher, exc)
            if replacement is None:
                return exc
            try:
                self._one(chapter, novel, output_dir, replacement, state)
                return None
            except Exception as retry:  # noqa: BLE001 — разбирает вызывающий
                return retry
        except Exception as exc:  # noqa: BLE001 — разбирает вызывающий
            return exc

    def _swap_proxy(self, fetcher, error: BaseException):
        """Новый клиент потока на другом адресе. None — менять не на что."""
        if fetcher is None or _is_refusal(error):
            return None
        reason = scrub(str(error))
        was = getattr(fetcher.proxy_of_thread(), "label", "")
        try:
            client = fetcher.replace(reason)
        except Exception as exc:  # noqa: BLE001 — замена не должна ронять поток
            log.warning("Не удалось сменить прокси в потоке: %s", exc)
            return None

        # Смена адреса — самое важное событие прогона: по журналу видно,
        # какой поток куда переехал и почему.
        now = getattr(fetcher.proxy_of_thread(), "label", "")
        if client is None:
            self._say(f"адрес {was or 'потока'} отвалился ({reason}), "
                      "менять больше не на что", "warn")
        else:
            self._say(f"адрес {was or '—'} отвалился ({reason}), "
                      f"поток переезжает на {now or 'прямое соединение'}", "warn")
        return client

    def _one(
        self,
        chapter: api.Chapter,
        novel: api.Novel,
        output_dir: Path,
        site: Client,
        state: State,
    ) -> None:
        """Скачивает и сохраняет одну главу. Ошибки пробрасывает наверх."""
        title, text = self.source.chapter(site, chapter)
        if not text.strip():
            raise ValueError("пустой текст главы")

        filename = chapter_filename(chapter.number, title or chapter.title)
        write_chapter(output_dir / filename, novel.name, title or chapter.title, chapter.number, text)
        with self._state_lock:
            state.mark_done(chapter.number, filename)


def _is_paid(error: BaseException) -> bool:
    """Глава платная. Отдельно от осечек: повтор её не откроет."""
    from net.sources.fanqie import PaidChapter

    return isinstance(error, PaidChapter)


def _is_refusal(error: BaseException) -> bool:
    """Сайт отказал: 403 или 429.

    Тип исключения зависит от того, как настроен клиент, поэтому смотрим и
    на сам код ответа — отказ обязан останавливать прогон в любом случае.
    """
    if isinstance(error, (Blocked, RateLimited)):
        return True
    return isinstance(error, HttpError) and error.status in (403, 429)


#: Та же отмена, что и у остальных операций, — см. `ops/base.py`.
Cancelled = OpCancelled


def _compact_ranges(numbers: list[int]) -> str:
    """[1,2,3,7] → '1-3, 7'."""
    if not numbers:
        return ""
    numbers = sorted(numbers)
    parts, start, prev = [], numbers[0], numbers[0]
    for n in numbers[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(parts)


def verify(output_dir: Path) -> dict:
    """Сверяет state.json с реально лежащими файлами."""
    state = State(output_dir / STATE_FILE)
    recorded = state.data.get("downloaded", {})
    present, lost = [], []
    for number, filename in recorded.items():
        (present if (output_dir / filename).exists() else lost).append(int(number))

    total = int((state.data.get("novel") or {}).get("total_chapters") or 0)
    have = set(present)
    missing = [n for n in range(1, total + 1) if n not in have] if total else []

    return {
        "novel": state.data.get("novel", {}),
        "total_chapters": total,
        "on_disk": len(present),
        "lost_files": sorted(lost),
        "missing": missing,
        "missing_compact": _compact_ranges(missing),
        "failed": {int(k): v for k, v in state.data.get("failed", {}).items()},
    }
