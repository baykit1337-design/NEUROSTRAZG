"""Локальный веб-интерфейс к качалке.

Сервер слушает только 127.0.0.1: он даёт доступ к файловой системе (выбор
папки), поэтому наружу его выставлять нельзя.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from flask import (Flask, Response, jsonify, request, send_file,
                   send_from_directory)

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import formats, naming, platform  # noqa: E402
from core.headings import HeadingsNotFound  # noqa: E402
from core.readers.base import ReadError  # noqa: E402
from core.registry import TYPES as ENTITY_TYPES  # noqa: E402
from core.text import PrepOptions  # noqa: E402
from core.writers.txt import ENCODINGS  # noqa: E402
from net import sources  # noqa: E402
from net.sources import categories as rank_cats  # noqa: E402
from net.sources import rank as rank_net  # noqa: E402
from ops import books as books_op  # noqa: E402
from ops import covers  # noqa: E402
from ops import rank as rank_op  # noqa: E402
from ops import titles as titles_op  # noqa: E402
from ops import merge as merge_op  # noqa: E402
from llm.client import BadKey, LlmClient, LlmError, NoKeysLeft, mask, short  # noqa: E402
from llm import keys as keys_mod  # noqa: E402
from llm.keys import store as keystore  # noqa: E402
from ops import analyze as analyze_op  # noqa: E402
from ops import compare as compare_op  # noqa: E402
from ops import contradictions as contra_op  # noqa: E402
from ops import glossary as glossary_op  # noqa: E402
from ops import diff as diff_op  # noqa: E402
from ops import docs as docs_op  # noqa: E402
from ops import retell as retell_op  # noqa: E402
from ops import headers as headers_op  # noqa: E402
from ops import history as history_op  # noqa: E402
from ops import joblog  # noqa: E402
from ops import session as session_op  # noqa: E402
from ops import queue as queue_op  # noqa: E402
from ops import reader as reader_op  # noqa: E402
from ops import replace as replace_op  # noqa: E402
from ops import signature as signature_op  # noqa: E402
from ops import spelling as spelling_op  # noqa: E402
from ops import stats as stats_op  # noqa: E402
from ops import split as split_op  # noqa: E402
from ops.base import Cancelled as OpCancelled  # noqa: E402
from ops.base import Progress  # noqa: E402
from mvl import api, checks, cleanup, nativedialog, rename  # noqa: E402
from mvl import textcheck  # noqa: E402
from mvl.cleanup import CleanError  # noqa: E402
from mvl.source import SourceError  # noqa: E402
from mvl.rename import RenameError  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl.client import Client, HttpError  # noqa: E402
from mvl import downloader as downloader_mod  # noqa: E402
from mvl.downloader import Cancelled, Downloader, verify  # noqa: E402
from mvl.paths import list_dirs, prepare_output_dir  # noqa: E402
from mvl import proxies as proxies_mod  # noqa: E402
from mvl.proxies import PROXY_FILE, ProxyPool, scrub  # noqa: E402
from mvl.word import Style  # noqa: E402
from config import settings  # noqa: E402

log = logging.getLogger(__name__)

#: Потолок таймаута из ТЗ: прокси иногда подключается очень долго.
MAX_TIMEOUT = 300

#: Событий в книге тысячи — в интерфейс отдаём только начало.
MAX_EVENTS = 500

#: Сколько глав качать при замере многопоточности. Шести хватает, чтобы
#: на трёх потоках каждому досталось по две, а книга при этом не качается.
CHECK_CHAPTERS = 6

STATIC_DIR = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR))


@dataclass
class Job:
    """Фоновая задача: скачивание книги или разбивка на главы."""

    id: str
    kind: str = "download"  # download | split | rename | word | check
    meta: dict = field(default_factory=dict)
    output_dir: str = ""
    progress: dict = field(default_factory=dict)
    report: dict | None = None
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    #: Когда началась и когда закончилась. Время меряет сервер, а не
    #: страница: перезагрузка вкладки не должна сбрасывать секундомер.
    started: float = field(default_factory=time.monotonic)
    finished: float = 0.0
    #: Построчный журнал работы — заводится там, где он нужен (7.7).
    log: object = None

    @property
    def elapsed(self) -> float:
        return (self.finished or time.monotonic()) - self.started

    @property
    def running(self) -> bool:
        return not self.finished

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "meta": self.meta,
            "output_dir": self.output_dir,
            "progress": self.progress,
            "report": self.report,
            "error": self.error,
            "cancelled": self.cancel.is_set(),
            "elapsed": round(self.elapsed, 1),
            "running": self.running,
        }


def start_job(job: Job, work) -> Job:
    """Запускает работу в фоне, ошибки складывает в саму задачу."""

    def runner():
        try:
            work(job)
        except OpCancelled:
            # Отмена в проекте одна на всех — см. `ops/base.py`. Раньше
            # классов было три, остановку ловил не тот `except`, и она
            # показывалась ошибкой.
            job.progress["stage"] = "cancelled"
            job.progress["message"] = "Остановлено. Что успело — сохранено."
        except Exception as exc:  # noqa: BLE001 — показываем пользователю любую поломку
            log.exception("Задача %s упала", job.id)
            job.error = scrub(f"{type(exc).__name__}: {exc}")
            job.progress["stage"] = "error"
            job.progress["message"] = job.error
        finally:
            job.finished = time.monotonic()

    job.thread = threading.Thread(target=runner, daemon=True)
    with JOBS_LOCK:
        JOBS[job.id] = job
    job.thread.start()
    return job


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()

#: Текущий пул прокси. Список меняется часто, поэтому перезагружается по
#: кнопке — перезапуск программы для этого не нужен.
POOL: ProxyPool | None = None
POOL_LOCK = threading.Lock()


def load_pool(path: str) -> ProxyPool:
    """Перечитывает файл со списком и заменяет текущий пул."""
    global POOL
    pool = ProxyPool.from_file(path)
    with POOL_LOCK:
        POOL = pool
    return pool


def _targets(payload: dict) -> list[str]:
    """Что выбрано: список файлов и/или папок."""
    targets = payload.get("targets")
    if isinstance(targets, str):
        targets = [targets]
    if not targets:
        one = (payload.get("folder_in") or payload.get("target")
               or payload.get("path") or "").strip()
        targets = [one] if one else []
    return [str(t).strip() for t in targets if str(t).strip()]


def _out_format(payload: dict) -> str:
    """Расширение на выходе, всегда с точкой: и «docx», и «.docx» подойдут."""
    value = (payload.get("format") or payload.get("out_format") or ".txt").strip().lower()
    return value if value.startswith(".") else f".{value}"


def _pattern(payload: dict) -> str | None:
    return (payload.get("pattern") or "").strip() or None


def _order(payload: dict) -> str:
    return (payload.get("order") or merge_op.ORDER_NUMBER).strip()


def _encoding(payload: dict) -> str:
    """Кодировка для текстовых форматов. Проверяется до запуска задачи."""
    value = (payload.get("encoding") or "utf-8").strip()
    if value not in ENCODINGS:
        raise ValueError(f"Неизвестная кодировка: {value}")
    return value


def _parts(payload: dict) -> int:
    """На сколько частей делить каждую главу. Меньше двух — не делить."""
    try:
        return max(1, int(payload.get("parts") or 1))
    except (TypeError, ValueError):
        return 1


def _progress(job: Job, unit: str) -> Progress:
    """Единый прогресс операции: колбэк и флаг отмены задачи."""
    def on_progress(done: int, total: int, message: str = "") -> None:
        job.progress.update(done=done, total=total,
                            message=message or f"{unit} {done} из {total}")

    return Progress(on_progress, job.cancel)


def _prepare(base: str, folder: str, operation: str) -> Path:
    """Папка для результата, с копией прежнего содержимого в корзину.

    Существующая папка используется как есть — на это опирается докачка,
    — поэтому перезапись возможна. Если в папке уже что-то лежит, старая
    версия сперва уходит в корзину: иначе восстанавливать будет нечего.
    """
    output_dir = prepare_output_dir(base, folder)
    saved = history_op.backup(output_dir, operation)
    if saved:
        log.info("Прежнее содержимое %s скопировано в %s", output_dir, saved)
    BACKUPS[str(output_dir)] = saved
    return output_dir


#: Куда легла копия перед перезаписью — чтобы записать это в журнал.
BACKUPS: dict[str, str] = {}


def _finish(job: Job, report, verb: str) -> None:
    """Итог операции в задачу — одинаково для всех вкладок.

    Здесь же строка журнала: через `_finish` проходит каждая пишущая
    операция, поэтому вести журнал в одном месте достаточно.
    """
    job.report = report.as_dict()
    job.progress.update(
        stage="done", written=report.written, failed=report.failed,
        message=(f"Готово. {verb} {report.written} из {report.total}"
                 + (f", ошибок {report.failed}" if report.failed else "")),
    )

    sources = job.meta.get("targets") or job.meta.get("source") or ""
    if isinstance(sources, list):
        sources = "; ".join(str(s) for s in sources[:3])
    history_op.add(
        operation=job.kind,
        source=str(sources),
        output=job.output_dir,
        files=report.written,
        failed=report.failed,
        backup=BACKUPS.pop(job.output_dir, ""),
    )


def _novel_from_payload(data: dict) -> api.Novel:
    """Книга из тела запроса — её уже нашли через /api/find."""
    return api.Novel(
        code=int(data["code"]),
        name=data.get("name") or f"novel-{data['code']}",
        slug=data.get("slug", ""),
        total_chapters=int(data.get("total_chapters") or 0),
        author=data.get("author", ""),
    )


# ---------------------------------------------------------------- страницы


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


# ------------------------------------------------------- отказы модели


#: Клиент модели заводится ДО `try` — иначе его нечем было бы закрыть в
#: `finally`. Значит, «ключей нет» вылетало мимо всех перехватов и
#: доезжало до браузера пятисоткой со стеком вместо строчки «добавьте
#: ключ». Обработчики ловят это один раз на всё приложение: шесть
#: одинаковых `try` вокруг шести вызовов разъехались бы через месяц.
@app.errorhandler(NoKeysLeft)
def _no_keys_left(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(BadKey)
def _bad_key(exc):
    return jsonify(error=str(exc)), 401


@app.errorhandler(LlmError)
def _llm_failed(exc):
    return jsonify(error=str(exc)), 502


# ------------------------------------------------------------------- API


@app.get("/api/sources")
def api_sources():
    """Откуда можно качать. Интерфейс строит список по этому ответу."""
    return jsonify(sources=[s.as_dict() for s in sources.all_sources()])


def _toc_any_proxy(source, novel, client, live, count):
    """Оглавление через любой живой прокси, а не только через первый.

    Список прокси на то и список: один адрес отвалился — это не повод
    сказать «не удалось собрать оглавление». Раньше замер брал `live[0]`
    и падал по таймауту, хотя рядом были рабочие адреса.
    """
    try:
        return source.toc(client, novel, first=1, last=count)
    except HttpError as first_error:
        for proxy in live[1:]:
            spare = Client(proxy_url=proxy.url)
            try:
                found = source.toc(spare, novel, first=1, last=count)
                log.info("Оглавление собралось через запасной прокси %s",
                         mask(proxy.url))
                return found
            except HttpError:
                continue
            finally:
                spare.close()
        raise first_error


def _found(novel) -> dict:
    """Книга для интерфейса: к своим полям добавлены перевод и имя папки.

    Имя папки считается здесь, а не в браузере (3.2 ТЗ): перевод названия
    лежит на сервере, и правило «в пути не бывает иероглифов» должно быть
    одно на всё приложение, а не двумя расходящимися копиями.
    """
    data = novel.to_dict()
    translated = titles_op.known().get(str(novel.code), "")
    data["translated"] = translated
    data["folder"] = naming.folder_name(
        novel.name, code=novel.code, translated=translated)
    return data


@app.post("/api/find")
def api_find():
    payload = request.json or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify(error="Введите ссылку, слаг или код книги"), 400

    try:
        source = sources.get(payload.get("source") or "")
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 400

    client = Client()
    try:
        novel = source.find(client, query)
        return jsonify(novel=_found(novel), source=source.key)
    except sources.SourceBroken as exc:
        # «Источник изменился» — не «не нашли»: жать «повторить» бесполезно.
        return jsonify(error=str(exc)), 502
    except api.StrippedResponse as exc:
        # Не «не найдено», а испорченный запрос — сообщаем отдельно.
        return jsonify(error=str(exc)), 502
    except (LookupError, ValueError) as exc:
        return jsonify(error=str(exc)), 404
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()


@app.post("/api/search")
def api_search():
    query = (request.json or {}).get("query", "").strip()
    if not query:
        return jsonify(novels=[])

    client = Client()
    try:
        novels = api.search_novels(client, query, limit=20)
        return jsonify(novels=[n.to_dict() for n in novels])
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()


@app.get("/api/proxies")
def api_proxies_state():
    """Текущее состояние пула, без повторной проверки."""
    with POOL_LOCK:
        pool = POOL
    if pool is None:
        return jsonify(pool=None, default_path=PROXY_FILE)
    return jsonify(pool=pool.to_dict(), default_path=PROXY_FILE)


@app.post("/api/proxies/reload")
def api_proxies_reload():
    """Перечитать файл со списком. Перезапуск программы не нужен."""
    path = (request.json or {}).get("path", "").strip() or PROXY_FILE
    try:
        pool = load_pool(path)
    except (OSError, ValueError) as exc:
        return jsonify(error=scrub(str(exc))), 400
    return jsonify(pool=pool.to_dict(), default_path=PROXY_FILE)


@app.post("/api/proxies/check")
def api_proxies_check():
    """Проверка живости всего списка. Пароли в ответ не попадают."""
    payload = request.json or {}
    path = payload.get("path", "").strip() or PROXY_FILE

    try:
        timeout = int(payload.get("timeout") or proxies_mod.CHECK_TIMEOUT)
    except (TypeError, ValueError):
        return jsonify(error="Таймаут должен быть числом секунд"), 400
    if not 1 <= timeout <= MAX_TIMEOUT:
        return jsonify(error=f"Таймаут проверки: от 1 до {MAX_TIMEOUT} секунд"), 400

    try:
        pool = load_pool(path)
    except (OSError, ValueError) as exc:
        return jsonify(error=scrub(str(exc))), 400

    pool.check_all(timeout=timeout)
    result = pool.to_dict()
    if pool.usable_count == 0:
        result["warning"] = (
            "Ни один прокси не пропускает до сайта. Напрямую не идём — "
            "этот путь заблокирован. Обновите список и проверьте снова."
        )
    return jsonify(pool=result, default_path=PROXY_FILE)


@app.post("/api/links")
def api_links():
    """Список ссылок на главы — для запасного плана через WebToEpub."""
    payload = request.json or {}
    novel_data = payload.get("novel") or {}
    if not novel_data.get("code"):
        return jsonify(error="Сначала найдите книгу"), 400

    novel = _novel_from_payload(novel_data)
    client = Client()
    try:
        toc = api.fetch_toc(
            client,
            novel,
            first=max(1, int(payload.get("first") or 1)),
            last=int(payload.get("last") or novel.total_chapters) or novel.total_chapters,
        )
        return jsonify(links=api.chapter_links(novel, toc.chapters), missing=toc.missing)
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()


@app.get("/api/pick/available")
def api_pick_available():
    """Есть ли системный проводник — если нет, интерфейс прячет кнопку."""
    return jsonify(available=nativedialog.available())


@app.post("/api/pick/<kind>")
def api_pick(kind: str):
    """Открывает настоящее окно проводника и возвращает выбранный путь.

    Пустой path — нажали «Отмена», это не ошибка.
    """
    if kind not in ("folder", "file", "files", "any"):
        return jsonify(error=f"Неизвестный выбор: {kind}"), 404

    payload = request.json or {}
    initial = (payload.get("initial") or "").strip()
    title = (payload.get("title") or "").strip()

    try:
        if kind == "folder":
            paths = [nativedialog.ask_directory(title or "Выберите папку", initial)]
        elif kind == "file":
            paths = [nativedialog.ask_open_file(title or "Выберите файл", initial)]
        elif kind == "files":
            paths = nativedialog.ask_open_files(title or "Выберите файлы", initial)
        else:
            # «Выбрать…» — принимает и файлы, и папку.
            paths = nativedialog.ask_any(title or "Выберите файлы или папку", initial)
    except nativedialog.DialogUnavailable as exc:
        # Не ошибка сервера: интерфейс просто остаётся на встроенном обзоре.
        return jsonify(error=str(exc), fallback=True), 503

    paths = [p for p in paths if p]
    return jsonify(paths=paths, path=paths[0] if paths else "", cancelled=not paths)


@app.get("/api/browse")
def api_browse():
    """Обзор папок на этой машине — чтобы выбрать место или файл книги.

    Параметр `files=epub,txt` включает показ файлов с этими расширениями.
    """
    raw = (request.args.get("files") or "").strip()
    suffixes = tuple(f".{s.strip().lstrip('.').lower()}" for s in raw.split(",") if s.strip())
    try:
        return jsonify(list_dirs(request.args.get("path"), suffixes or None))
    except OSError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/start")
def api_start():
    payload = request.json or {}
    novel_data = payload.get("novel") or {}
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()

    if not novel_data.get("code"):
        return jsonify(error="Сначала найдите книгу"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог книги"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400

    novel = _novel_from_payload(novel_data)

    try:
        output_dir = _prepare(base, folder, "download")
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    first = max(1, int(payload.get("first") or 1))
    last = int(payload.get("last") or novel.total_chapters) or novel.total_chapters
    if last < first:
        return jsonify(error="Конечная глава меньше начальной"), 400

    with POOL_LOCK:
        pool = POOL
    if pool is not None and pool.checked and pool.usable_count == 0:
        return jsonify(
            error="Ни один прокси не пропускает до сайта. Напрямую не идём — "
            "этот путь заблокирован. Обновите список и проверьте снова."
        ), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="download",
        meta={"novel": novel.to_dict()},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "queued", "message": "Запускаем…", "done": 0, "total": last - first + 1,
                    "downloaded": 0, "skipped": 0, "failed": 0,
                    "proxy": pool.current().label if pool and pool.usable_count else "",
                    "switches": 0}

    try:
        read_timeout = int(payload.get("timeout") or client_mod.TIMEOUT)
        connect_timeout = int(payload.get("connect_timeout") or client_mod.CONNECT_TIMEOUT)
    except (TypeError, ValueError):
        return jsonify(error="Таймаут должен быть числом секунд"), 400
    if read_timeout < 5 or connect_timeout < 1:
        return jsonify(error="Слишком маленький таймаут"), 400
    if read_timeout > MAX_TIMEOUT or connect_timeout > MAX_TIMEOUT:
        return jsonify(error=f"Таймаут больше {MAX_TIMEOUT} секунд не имеет смысла"), 400

    try:
        threads = int(payload.get("threads") or 1)
    except (TypeError, ValueError):
        return jsonify(error="Потоков должно быть числом"), 400
    if not 1 <= threads <= downloader_mod.MAX_THREADS:
        return jsonify(
            error=f"Потоков: от 1 до {downloader_mod.MAX_THREADS}"
        ), 400

    # Ручной режим пропускает пробу: пользователь сам увидит по времени,
    # работает многопоточность или нет, — это надёжнее любой эвристики.
    probe = str(payload.get("mode") or "auto").strip() != "manual"

    try:
        source = sources.get(payload.get("source") or "")
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 400

    job.meta["threads"] = threads

    # Журнал прогона: раздача прокси по потокам и смена адреса с причиной.
    job.log = joblog.JobLog()

    def work(job: Job):
        client = Client(timeout=read_timeout, connect_timeout=connect_timeout)
        downloader = Downloader(
            client=client,
            pool=pool,
            on_progress=lambda p: job.progress.update(p.as_dict()),
            on_event=job.log.add,
            cancel_event=job.cancel,
            threads=threads,
            probe=probe,
            source=source,
        )
        try:
            job.report = downloader.run(novel, output_dir, first=first, last=last).as_dict()
        finally:
            client.close()

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/threads/check")
def api_threads_check():
    """Замер многопоточности на живых главах (часть 6 ТЗ).

    Ручной режим чинили вслепую: убедиться, что параллельность работает,
    можно было только прогоном книги целиком. Здесь качаются несколько
    глав, ничего не сохраняется, а в ответе видно, какой поток через
    какой адрес шёл.
    """
    payload = request.json or {}
    novel_data = payload.get("novel") or {}
    if not novel_data.get("code"):
        return jsonify(error="Сначала найдите книгу"), 400

    try:
        source = sources.get(payload.get("source") or "")
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 400

    try:
        threads = max(1, int(payload.get("threads") or 1))
        count = max(2, min(int(payload.get("chapters") or CHECK_CHAPTERS), 20))
    except (TypeError, ValueError):
        return jsonify(error="Потоки и число глав должны быть числами"), 400

    novel = _novel_from_payload(novel_data)
    with POOL_LOCK:
        pool = POOL

    # Порядок важен: первым должен идти проверенный адрес, а не первый по
    # порядку в файле. Иначе замер утыкается в мёртвый прокси и обрывается,
    # хотя рядом лежит восемь рабочих.
    live = _working_proxies(pool)
    if source.needs_proxy and not live:
        # Источник без прокси не отвечает вовсе, и замер выродился бы в
        # «сайт недоступен» — причина при этом не в потоках (3.3 ТЗ).
        return jsonify(error=f"Источник «{source.name}» работает только через "
                             "прокси, а живых адресов нет. Проверьте список "
                             "на вкладке «Качалка».",
                       step="прокси"), 400

    # Оглавление берём через тот же прокси, что и всё остальное: голым
    # клиентом сайт не отвечает, и замер падал с невнятным 502.
    client = Client(proxy_url=live[0].url if live else None)
    downloader = Downloader(client=client, pool=pool, threads=threads,
                            source=source)
    try:
        try:
            toc = _toc_any_proxy(source, novel, client, live, count)
        except (sources.SourceBroken, HttpError, LookupError, ValueError) as exc:
            # Разделяем шаги: «не собралось оглавление» и «не пошли потоки»
            # чинятся по-разному, а общий 502 не говорит ни о том, ни о другом.
            return jsonify(error=f"Не удалось собрать оглавление: {exc}",
                           step="оглавление"), 502
        if not toc.chapters:
            return jsonify(error="У книги не нашлось глав — замерять нечего.",
                           step="оглавление"), 400

        found = downloader.measure_threads(novel, toc.chapters, count)
    except Exception as exc:  # noqa: BLE001 — замер не должен ронять сервер
        log.exception("Замер многопоточности не удался")
        return jsonify(error=f"Замер не удался: {type(exc).__name__}: {exc}",
                       step="замер"), 502
    finally:
        client.close()

    # Сам замер о своих бедах рассказывает в отчёте, а не кодом ответа:
    # «ни один поток не создался» — это результат, а не отказ сервера.
    return jsonify(**found.as_dict())


# --------------------------------------------- вкладка «Разбить»


@app.get("/api/formats")
def api_formats():
    """Что можно прочитать и во что записать.

    Интерфейс строит списки по этому ответу, а не по своему перечню:
    иначе новый формат приходится добавлять в двух местах.
    """
    return jsonify(readable=list(formats.READABLE), writable=list(formats.WRITABLE))


@app.post("/api/split/scan")
def api_split_scan():
    """Сколько глав нашлось и первые названия — до записи на диск."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файл книги или папку"), 400
    try:
        return jsonify(**split_op.scan(targets, _pattern(payload), _parts(payload)))
    except HeadingsNotFound as exc:
        # Наугад не режем — просим своё регулярное выражение.
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/split/start")
def api_split_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    out_format = _out_format(payload)
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not targets:
        return jsonify(error="Выберите файл книги или папку"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400
    if out_format not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {out_format}"), 400

    # Читаем до создания папки, чтобы не плодить пустые каталоги.
    try:
        info = split_op.scan(targets, _pattern(payload), _parts(payload))
    except HeadingsNotFound as exc:
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    try:
        output_dir = _prepare(base, folder, "split")
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    total = info["total"]
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="split",
        meta={"targets": targets, "format": out_format, "total": total},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "split", "message": f"Пишем {total} глав…",
                    "done": 0, "total": total, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, split_op.run(
            targets, Path(job.output_dir),
            out_format=out_format,
            parts=_parts(payload),
            pattern=_pattern(payload),
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            titles=bool(payload.get("headings", True)),
            encoding=encoding,
            progress=_progress(job, "Глава"),
        ), "Записано")

    return jsonify(job=start_job(job, work).snapshot())


# --------------------------------------- вкладка «Переименование и деление»


def _chosen_paths(payload: dict) -> set[str] | None:
    """Отмеченные галочками пути. `None` — «галочек не присылали»."""
    chosen = payload.get("chosen")
    if chosen is None:
        return None
    return {str(path) for path in chosen}


def _plan_from_payload(payload: dict):
    """Собирает план по параметрам запроса. Общее для предпросмотра и записи."""
    folder = (payload.get("folder_in") or "").strip()
    if not folder:
        raise RenameError("Выберите папку с главами")

    pattern = (payload.get("pattern") or "").strip() or None
    chapters = rename.scan(folder, pattern)

    start = payload.get("renumber_from")
    renumber_from = None
    if payload.get("renumber") and str(start or "").strip():
        try:
            renumber_from = int(start)
        except (TypeError, ValueError):
            raise RenameError("Начальный номер должен быть числом") from None

    rows = rename.make_plan(
        chapters,
        rename.NameFormat.from_dict(payload.get("format")),
        splits={str(k): int(v) for k, v in (payload.get("splits") or {}).items()},
        renumber_from=renumber_from,
        # Отмеченные галочками пути. Пустой список и отсутствие списка —
        # разные вещи: первое значит «не отмечено ничего», второе — «про
        # галочки не спрашивали, берём все». Раньше они были одним и тем
        # же, и снятие всех галочек означало «переименовать всё».
        chosen=_chosen_paths(payload),
    )
    return chapters, rows


@app.post("/api/rename/scan")
def api_rename_scan():
    """Список глав в папке: имя, номер, объём, пометка сомнительного разбора."""
    payload = request.json or {}
    folder = (payload.get("folder_in") or "").strip()
    if not folder:
        return jsonify(error="Выберите папку с главами"), 400
    try:
        chapters = rename.scan(folder, (payload.get("pattern") or "").strip() or None)
    except RenameError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        chapters=[c.as_dict() for c in chapters],
        suspect=sum(1 for c in chapters if c.suspect),
        total=len(chapters),
    )


@app.post("/api/rename/plan")
def api_rename_plan():
    """Предпросмотр «старое имя → новое имя». На диск ничего не пишется."""
    payload = request.json or {}
    try:
        _, rows = _plan_from_payload(payload)
    except RenameError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        rows=[r.as_dict() for r in rows],
        total=len(rows),
        # Двоеточие в именах файлов Windows не разрешает — предупредим один раз.
        forbidden=rename.has_forbidden(
            rename.NameFormat.from_dict(payload.get("format")).separator
        ),
    )


@app.post("/api/rename/apply")
def api_rename_apply():
    """Пишет результат в новую папку. Оригиналы не трогаются."""
    payload = request.json or {}
    base = (payload.get("base") or "").strip()
    out_name = (payload.get("folder_out") or "").strip()
    fmt = (payload.get("out_format") or "txt").strip().lower().lstrip(".")
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not out_name:
        return jsonify(error="Введите имя новой папки"), 400
    # Список форматов один на все вкладки и берётся из `core/formats.py`.
    if f".{fmt}" not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {fmt}"), 400

    try:
        _, rows = _plan_from_payload(payload)
    except RenameError as exc:
        return jsonify(error=str(exc)), 400
    if not rows:
        return jsonify(error="Нечего переименовывать"), 400

    # Правки из предпросмотра: приходят по индексу строки, текст глав через
    # клиент не гоняем — план пересобирается на сервере.
    for index, name in enumerate(payload.get("names") or []):
        if index < len(rows) and str(name).strip():
            rows[index].new_name = str(name).strip()

    try:
        output_dir = _prepare(base, out_name, "rename")
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    style = Style.from_dict(payload.get("style"))
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="rename",
        meta={"source": payload.get("folder_in"), "format": fmt, "total": len(rows)},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "rename", "message": f"Пишем {len(rows)} файлов…",
                    "done": 0, "total": len(rows), "written": 0, "failed": 0}

    def work(job: Job):
        report = rename.apply_plan(
            rows, Path(job.output_dir), fmt=fmt, style=style,
            prep=PrepOptions.from_dict(payload.get("prep")),
            headings=bool(payload.get("headings", True)),
            encoding=encoding,
            on_progress=lambda done, total: job.progress.update(
                done=done, total=total, message=f"Файл {done} из {total}"),
            cancel=job.cancel,
        )
        job.report = report.as_dict()
        job.progress.update(
            stage="done", written=report.written, failed=report.failed,
            message=(f"Готово. Записано {report.written} из {report.total}"
                     + (f", ошибок {report.failed}" if report.failed else "")),
        )

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------------ модель и ключ


def _llm_client(payload: dict | None = None, log_to=None) -> LlmClient:
    """Единственный способ завести клиента модели (1.3 ТЗ).

    Хранилище ключей одно на всё приложение, и подставляется оно здесь.
    Заводить клиента в обход этой функции нельзя: про ключи слишком легко
    забыть — так и вышло с аннотацией, которая падала с «ключ не задан»
    при полном списке ключей, пока разбор глав работал.

    Список обязателен и по второй причине: без него клиент искал ключ в
    старом одиночном поле настроек, а список это поле как раз и очищает.
    """
    payload = payload or {}
    with POOL_LOCK:
        pool = POOL
    typed = (payload.get("key") or "").strip()
    return LlmClient(key=typed, pool=pool,
                     # Введённый вручную ключ проверяется как есть: он ещё
                     # не сохранён, и ротации для него нет.
                     keys=None if typed else keystore,
                     on_event=(lambda text: log_to.add(text, "key")) if log_to else None)


@app.get("/api/llm/state")
def api_llm_state():
    """Что настроено. Ключи отдаются только сокращёнными."""
    state = keystore.state()
    return jsonify(configured=state["total"] > 0,
                   provider=settings.llm.provider, **state)


@app.post("/api/llm/keys/add")
def api_llm_keys_add():
    """Добавляет ключ или сразу несколько строк."""
    payload = request.json or {}
    text = str(payload.get("key") or "")
    if not text.strip():
        return jsonify(error="Введите ключ"), 400
    keystore.add(text, name=str(payload.get("name") or "").strip(),
                 limit=int(payload.get("limit") or 0))
    return jsonify(**keystore.state())


@app.post("/api/llm/keys/remove")
def api_llm_keys_remove():
    keystore.remove(str((request.json or {}).get("id") or ""))
    return jsonify(**keystore.state())


@app.post("/api/llm/keys/update")
def api_llm_keys_update():
    """Правка имени, лимита и статуса вручную (7.2 и 7.3)."""
    payload = request.json or {}
    ident = str(payload.get("id") or "")
    if not ident:
        return jsonify(error="Не указан ключ"), 400

    fields = {}
    if "name" in payload:
        fields["name"] = str(payload.get("name") or "")
    if "limit" in payload:
        try:
            fields["limit"] = max(0, int(payload.get("limit") or 0))
        except (TypeError, ValueError):
            return jsonify(error="Лимит должен быть числом"), 400
    if "state" in payload:
        wanted = str(payload.get("state") or "").strip()
        if wanted not in (keys_mod.ACTIVE, keys_mod.EXHAUSTED):
            return jsonify(error=f"Неизвестное состояние: {wanted}"), 400
        fields["state"] = wanted
        # Сняли пометку вручную — счётчик и срок сброса больше не в счёт,
        # иначе ключ тут же снова окажется исчерпанным.
        if wanted == keys_mod.ACTIVE:
            fields.update(used=0, exhausted_at="", reset_at="")

    keystore.update(ident, **fields)
    return jsonify(**keystore.state())


@app.post("/api/llm/estimate")
def api_llm_estimate():
    """«Оценить расход»: объём работы и сколько класть на ключ (7.2)."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        info = analyze_op.scan(targets, _book_root(payload))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    keys = keystore.state()["total"] or 1
    estimate = info.get("estimate") or {}
    from llm.client import Estimate

    full = Estimate(chapters=int(estimate.get("chapters") or 0),
                    characters=int(estimate.get("characters") or 0),
                    tokens=int(estimate.get("tokens") or 0),
                    cached=int(estimate.get("cached") or 0),
                    keys=keys)
    return jsonify(**full.as_dict())


@app.post("/api/llm/check")
def api_llm_check():
    """Проверяет ключ и отдаёт список моделей.

    Зовётся сразу при вводе ключа: недействительный ключ должен быть виден
    здесь, а не при первом разборе главы.
    """
    payload = request.json or {}
    typed = (payload.get("key") or "").strip()
    if not typed and not keystore.state()["total"]:
        return jsonify(error="Ключей в списке нет — добавьте хотя бы один",
                       need_keys=True), 400

    # Проверка — не задача, прогресс-бара у неё нет, но журнал тот же:
    # он и отвечает на вопрос «через какой адрес ушёл запрос».
    trace = joblog.JobLog()
    client = _llm_client(payload, log_to=trace)
    try:
        found = client.check()
        # По какому ключу проверяли — видно и в ответе, и в журнале.
        return jsonify(**found, checked=short(client.key), log=trace.lines())
    except NoKeysLeft as exc:
        trace.add(str(exc), "error")
        return jsonify(error=str(exc), need_keys=True, log=trace.lines()), 400
    except BadKey as exc:
        # Причина словами: «наш сервер отказал» и «Gemini отклонил ключ» —
        # разные беды, и чинить их надо по-разному.
        text = f"Gemini отклонил ключ {short(client.key)}: {exc}"
        trace.add(text, "error")
        return jsonify(error=text, key=short(client.key),
                       log=trace.lines()), 400
    except LlmError as exc:
        trace.add(str(exc), "error")
        return jsonify(error=str(exc), key=short(client.key),
                       log=trace.lines()), 502
    finally:
        client.close()


@app.post("/api/llm/save")
def api_llm_save():
    """Сохраняет ключ и модель в config.json — он в .gitignore."""
    payload = request.json or {}
    key = (payload.get("key") or "").strip()
    model = (payload.get("model") or "").strip()

    if key:
        # Ключи живут списком: добавляем, а не заменяем единственный.
        keystore.add(key, name=str(payload.get("name") or "").strip(),
                     limit=int(payload.get("limit") or 0))
    if model:
        settings.llm.model = model
    if "use_proxies" in payload:
        settings.llm.use_proxies = bool(payload.get("use_proxies"))

    try:
        settings.save()
    except OSError as exc:
        return jsonify(error=f"Не удалось сохранить настройки: {exc}"), 500

    return jsonify(saved=True, **keystore.state())


# --------------------------------------------- очистка мусорной шапки


@app.post("/api/headers/scan")
def api_headers_scan():
    """Что похоже на шапку: и между файлами, и внутри каждого из них."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        repeat = max(1, int(payload.get("repeat") or 0)) \
            if payload.get("repeat") else 0
        offset = max(0, int(payload.get("offset") or 0))
    except (TypeError, ValueError):
        return jsonify(error="Порог и номер строки должны быть числами"), 400

    try:
        return jsonify(**headers_op.scan(
            targets, repeat=repeat,
            pattern=str(payload.get("pattern") or "").strip(),
            offset=offset))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/headers/clean")
def api_headers_clean():
    """Пишет очищенные главы в новую папку. Оригиналы не трогаются."""
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    texts = payload.get("texts")
    rules = payload.get("rules")
    texts = texts if isinstance(texts, list) else []
    rules = rules if isinstance(rules, list) else []

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400
    # Пустой список — это «ничего не отмечено», а не «убрать всё».
    if not texts and not rules:
        return jsonify(error="Отметьте, что убрать"), 400

    try:
        output_dir = _prepare(base, folder, "headers")
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="headers",
        meta={"targets": targets},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "headers", "message": "Чистим шапки…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, headers_op.run(
            targets, Path(job.output_dir), texts,
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Файл"),
            rules=rules,
        ), "Очищено")

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------- вкладка «Объединить»


@app.post("/api/merge/scan")
def api_merge_scan():
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**merge_op.scan(targets, _order(payload)))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/merge/start")
def api_merge_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    name = (payload.get("name") or "").strip()
    out_format = _out_format(payload)
    order = _order(payload)
    try:
        encoding = _encoding(payload)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if not name:
        return jsonify(error="Введите имя файла"), 400
    if out_format not in formats.WRITABLE:
        return jsonify(error=f"Неизвестный формат: {out_format}"), 400
    if order not in merge_op.ORDERS:
        return jsonify(error=f"Неизвестный порядок: {order}"), 400

    base_dir = Path(base).expanduser()
    if not base_dir.is_dir():
        return jsonify(error=f"Папка не найдена: {base_dir}"), 400

    try:
        info = merge_op.scan(targets, order)
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    output = base_dir / f"{naming.safe_filename(name)}{out_format}"
    total = info["total"]
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="merge",
        meta={"targets": targets, "format": out_format, "total": total},
        output_dir=str(output),
    )
    job.progress = {"stage": "merge", "message": f"Собираем {total} глав…",
                    "done": 0, "total": total, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, merge_op.run(
            targets, Path(job.output_dir),
            order=order,
            headings=bool(payload.get("headings", True)),
            separator=(payload.get("separator") or merge_op.DEFAULT_SEPARATOR),
            custom_separator=(payload.get("custom_separator") or ""),
            encoding=encoding,
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Файл"),
        ), "Собрано")

    return jsonify(job=start_job(job, work).snapshot())



# ------------------------------------------------ вкладка «Анализ»


def _book_root(payload: dict) -> Path:
    """Папка книги: рядом с ней лежит analysis/."""
    root = (payload.get("root") or "").strip()
    if root:
        return Path(root).expanduser()
    targets = _targets(payload)
    first = Path(targets[0]).expanduser() if targets else Path.cwd()
    return first.parent if first.is_file() else first


@app.post("/api/analyze/scan")
def api_analyze_scan():
    """Сколько глав предстоит разобрать и во что это обойдётся."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**analyze_op.scan(targets, _book_root(payload)))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


def _analysis_result(job: Job, report=None, reason: str = "") -> dict:
    """Блок результата разбора — обязателен в любом исходе (7.5).

    Раньше при остановке на экране оставалось «разобрано 16, ошибок 0» и
    больше ничего: было непонятно ни почему встало, ни что делать дальше.
    """
    keys = keystore.state()
    soon = [k["resets_in"] for k in keys["keys"]
            if k["resets_in"] is not None]
    progress = job.progress or {}
    if report is not None:
        # Обработанное — это разобранное и взятое из кэша. Прогресс сюда не
        # годится: он считает и осечки тоже, и «обработано 3, ошибок 3»
        # выглядело бы враньём.
        done = int(report.parsed) + int(report.cached)
    else:
        done = int(progress.get("done") or 0)

    return {
        "reason": reason,
        "done": done,
        "total": int(progress.get("total") or 0),
        "failed": int(getattr(report, "failed", 0) or progress.get("failed") or 0),
        "tokens": int(job.meta.get("tokens") or 0),
        "keys_total": keys["total"],
        "keys_exhausted": keys["exhausted"],
        "keys_active": keys["active"],
        "resets_in": min(soon) if soon else None,
        "output": job.output_dir,
        # «Продолжить» имеет смысл, только если есть чем продолжать.
        "can_continue": keys["active"] > 0 and
                        int(progress.get("done") or 0) < int(progress.get("total") or 0),
    }


@app.post("/api/analyze/start")
def api_analyze_start():
    """Этап 1: разбор глав моделью."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400

    try:
        keystore.active()
    except NoKeysLeft as exc:
        return jsonify(error=str(exc), need_keys=True), 400

    root = _book_root(payload)
    try:
        info = analyze_op.scan(targets, root)
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    if payload.get("restart"):
        # «Начать заново» стирает только отметку о ходе работы: кэш глав
        # трогать нельзя, за него уже заплачено.
        session_op.forget(root)

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="analyze",
        meta={"targets": targets, "total": info["total"]},
        output_dir=str(root / "analysis"),
    )
    job.log = joblog.JobLog()
    job.progress = {"stage": "analyze", "message": "Разбираем главы…",
                    "done": 0, "total": info["total"], "written": 0, "failed": 0}

    model = (payload.get("model") or "").strip()
    session_op.start(root, targets, info["total"], model=model,
                     keys=[k["id"] for k in keystore.state()["keys"]])

    def work(job: Job):
        with POOL_LOCK:
            pool = POOL
        client = _llm_client(log_to=job.log)
        report = None
        try:
            report = analyze_op.collect(
                targets, client, root=root, model=model,
                force=bool(payload.get("force")),
                progress=_progress(job, "Глава"),
                log_to=job.log,
            )
            # Реестр пересобираем сразу: без него разбор бесполезен.
            registry = analyze_op.rebuild(root)
            session_op.finish(root, done=report.parsed + report.cached)
            job.report = {**report.as_dict(), "registry": registry.stats(),
                          "result": _analysis_result(job, report)}
            job.progress.update(
                stage="done", written=report.parsed + report.cached,
                failed=report.failed,
                message=(f"Готово. Разобрано {report.parsed}, из кэша "
                         f"{report.cached}"
                         + (f", не вышло {report.failed}" if report.failed else "")),
            )
        except NoKeysLeft as exc:
            # Работа встала, но результат сохраняется и продолжается (7.5).
            done = int(job.progress.get("done") or 0)
            session_op.stop(root, "ключи исчерпаны", done=done)
            job.log.add(str(exc), "stop")
            job.report = {"result": _analysis_result(job, report, str(exc))}
            job.progress.update(stage="cancelled", message=str(exc))
        except OpCancelled:
            session_op.stop(root, "остановлено",
                            done=int(job.progress.get("done") or 0))
            job.log.add("остановлено человеком", "stop")
            job.report = {"result": _analysis_result(
                job, report, "Работа остановлена")}
            job.progress.update(stage="cancelled",
                                message="Остановлено. Что успело — сохранено.")
        finally:
            client.close()

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/analyze/session")
def api_analyze_session():
    """Незавершённая сессия по этой папке — чтобы предложить продолжить."""
    payload = request.json or {}
    session = session_op.load(_book_root(payload))
    if session is None or session.finished:
        return jsonify(session=None)
    return jsonify(session=session.as_dict())


@app.post("/api/analyze/sessions")
def api_analyze_sessions():
    """Все незавершённые сессии по выбранным папкам.

    Сессий бывает несколько — по одной на книгу, — поэтому список, а не
    одна: иначе вторая книга была бы не видна вовсе.
    """
    payload = request.json or {}
    found = []
    for target in _targets(payload) or []:
        path = Path(target).expanduser()
        root = path if path.is_dir() else path.parent
        session = session_op.load(root)
        if session is not None and not session.finished:
            found.append(session.as_dict())
    return jsonify(sessions=found)


@app.post("/api/analyze/forget")
def api_analyze_forget():
    """«Начать заново»: стирает ход сессии, кэш глав не трогает."""
    payload = request.json or {}
    return jsonify(forgotten=session_op.forget(_book_root(payload)))


@app.get("/api/job/<job_id>/log")
def api_job_log(job_id: str):
    """Журнал работы под прогресс-баром (7.7)."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.log is None:
        return jsonify(lines=[], total=0)
    try:
        since = int(request.args.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    return jsonify(**job.log.state(since))


@app.get("/api/job/<job_id>/log.txt")
def api_job_log_file(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.log is None:
        return jsonify(error="Журнала нет"), 404
    return Response(
        job.log.as_text(),
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="analysis-log.txt"'},
    )


@app.post("/api/registry/state")
def api_registry_state():
    """Реестр целиком: сущности, связи, события."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    return jsonify(
        root=str(root),
        stats=registry.stats(),
        entities=[e.as_dict() for e in registry.entities.values()],
        links=[l.as_dict() for l in registry.links],
        events=[e.as_dict() for e in registry.events[:MAX_EVENTS]],
        duplicates=[
            {"keep": a, "drop": b,
             "keep_name": registry.entities[a].name,
             "drop_name": registry.entities[b].name}
            for a, b in registry.duplicates()
        ],
        types=list(ENTITY_TYPES),
    )


@app.post("/api/registry/edit")
def api_registry_edit():
    """Правка записи вручную. Отредактированная считается истиной."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)

    entity = registry.entities.get((payload.get("id") or "").strip())
    if entity is None:
        return jsonify(error="Запись не найдена"), 404

    for field_name in ("name", "type", "status"):
        if field_name in payload:
            setattr(entity, field_name, str(payload[field_name]).strip()
                    or getattr(entity, field_name))
    if "aliases" in payload:
        entity.aliases = [str(a).strip() for a in payload["aliases"] if str(a).strip()]
    if "attributes" in payload and isinstance(payload["attributes"], dict):
        entity.attributes = {str(k): v for k, v in payload["attributes"].items()}
    # Правка руками — значит, модель больше эту запись не переписывает.
    entity.confirmed = True

    analyze_op.save_registry(root, registry)
    return jsonify(entity=entity.as_dict())


@app.post("/api/registry/merge")
def api_registry_merge():
    """Слияние двух записей: вторая уходит в варианты имени первой."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)

    keep = (payload.get("keep") or "").strip()
    drop = (payload.get("drop") or "").strip()
    if keep not in registry.entities or drop not in registry.entities:
        return jsonify(error="Запись не найдена"), 404

    merged = registry.merge(keep, drop)
    if merged is not None:
        merged.confirmed = True
    analyze_op.save_registry(root, registry)
    return jsonify(entity=merged.as_dict() if merged else None,
                   stats=registry.stats())


@app.post("/api/registry/rebuild")
def api_registry_rebuild():
    """Пересобрать реестр из кэша, сохранив подтверждённое."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.rebuild(root)
    return jsonify(stats=registry.stats())


@app.post("/api/glossary/import")
def api_glossary_import():
    """Глоссарий от переводчика. Записи сразу подтверждённые."""
    payload = request.json or {}
    root = _book_root(payload)
    text = payload.get("text") or ""
    path = (payload.get("path") or "").strip()

    if not text and path:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8",
                                                     errors="replace")
        except OSError as exc:
            return jsonify(error=f"Не удалось прочитать файл: {exc}"), 400
    if not text.strip():
        return jsonify(error="Глоссарий пуст"), 400

    registry = analyze_op.load_registry(root)
    added = glossary_op.load_into(registry, text)
    analyze_op.save_registry(root, registry)
    return jsonify(added=added, total=len(glossary_op.parse(text)),
                   stats=registry.stats())


@app.post("/api/glossary/export")
def api_glossary_export():
    """Выгрузка глоссария в формате переводчика."""
    payload = request.json or {}
    root = _book_root(payload)
    fmt = (payload.get("format") or "txt").strip().lower().lstrip(".")
    if fmt not in glossary_op.FORMATS:
        return jsonify(error=f"Неизвестный формат: {fmt}"), 400

    registry = analyze_op.load_registry(root)
    text = glossary_op.dump(registry, fmt, payload.get("types"))
    return jsonify(text=text, format=fmt, lines=text.count("\n"))


@app.post("/api/analyze/check")
def api_analyze_check():
    """Этап 3: поиск противоречий по реестру."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    if not registry.entities:
        return jsonify(error="Реестр пуст — сначала разберите главы"), 400

    kinds = payload.get("kinds")
    kinds = [k for k in kinds if k in contra_op.KINDS] if isinstance(kinds, list) else None
    report = contra_op.check(registry, root, kinds=kinds)
    return jsonify(**report.as_dict())


@app.get("/api/analyze/kinds")
def api_analyze_kinds():
    return jsonify(kinds=[{"key": k, "name": v} for k, v in contra_op.KINDS.items()],
                   formats=list(glossary_op.FORMATS))


@app.post("/api/analyze/cards")
def api_analyze_cards():
    """Карточки персонажей."""
    payload = request.json or {}
    root = _book_root(payload)
    registry = analyze_op.load_registry(root)
    kind = (payload.get("type") or "персонаж").strip()
    return jsonify(cards=glossary_op.cards(registry, kind),
                   text=glossary_op.cards_text(registry, kind))



# ------------------------------------------- рейтинг Фанкью (5.2)

#: Список категорий забирается с сайта один раз и живёт до перезапуска:
#: жанры не меняются, а запрос ради них — лишний.
RANK_CATEGORIES: dict = {}
RANK_LOCK = threading.Lock()


def _rank_client():
    """Клиент для рейтинга — через прокси, даже если их ещё не проверяли.

    `usable` значит «проверен и ответил двухсоткой», а до нажатия кнопки
    проверки это ложь у всех адресов сразу. Рейтинг из-за этого уходил на
    китайский сайт напрямую и молча ничего не привозил: снаружи выглядело
    как «нажал срез — не произошло ничего». Непроверенный прокси мёртвым
    не является; отключённый — является, его и пропускаем.
    """
    with POOL_LOCK:
        pool = POOL
    return Client(proxy_url=_any_proxy(pool))


def _working_proxies(pool) -> list:
    """Прокси в порядке пригодности: сперва проверенные, потом остальные.

    `disabled` ставится только на ходу, когда адрес подвёл во время
    прогона. Проверка кнопкой помечает иначе — через `alive` и `status`,
    — поэтому «не disabled» включает и те, что проверку провалили.
    Раньше отсюда брался первый по порядку в файле, и замер утыкался в
    мёртвый адрес, хотя рядом было восемь рабочих.
    """
    if not pool:
        return []
    everything = [p for p in getattr(pool, "proxies", []) if not p.disabled]
    good = [p for p in everything if p.usable]
    # Непроверенные идут следом: пока кнопку не нажимали, пригодных нет
    # вовсе, и остаться совсем без адреса хуже, чем взять неизвестный.
    return good + [p for p in everything if not p.usable]


def _any_proxy(pool) -> str | None:
    """Адрес лучшего доступного прокси."""
    found = _working_proxies(pool)
    return found[0].url if found else None


def _rank_where(payload) -> tuple[str, str, str]:
    """Аудитория, вид и категория из запроса."""
    get = payload.get if hasattr(payload, "get") else (lambda k, d=None: d)
    audience = str(get("audience") or rank_cats.MALE)
    kind = str(get("kind") or rank_cats.READING)
    category = str(get("category") or "")
    return audience, kind, category


@app.get("/api/rank/categories")
def api_rank_categories():
    """Разделы и категории. С сайта один раз, дальше из памяти."""
    global RANK_CATEGORIES
    with RANK_LOCK:
        have = dict(RANK_CATEGORIES)

    if not have and str(request.args.get("fetch") or "") == "1":
        client = _rank_client()
        try:
            have = rank_net.fetch_categories(client, rank_cats.MALE)
        except Exception as exc:  # noqa: BLE001 — есть запасной список
            log.warning("Категории рейтинга не забрались: %s", exc)
            have = {}
        finally:
            client.close()
        if have:
            with RANK_LOCK:
                RANK_CATEGORIES = have

    if not have:
        # Пустой выбор хуже известного набора: жанры не меняются годами.
        have = {side: [rank_cats.translate(c) for c in ids]
                for side, ids in rank_cats.FALLBACK.items()}

    return jsonify(
        categories=have,
        audiences=[{"key": k, "name": v} for k, v in rank_cats.AUDIENCES.items()],
        kinds=[{"key": k, "name": v} for k, v in rank_cats.KINDS.items()],
        boards=[{"key": k, "name": v} for k, v in rank_cats.BOARDS.items()],
    )


@app.get("/api/rank/state")
def api_rank_state():
    """Что уже накоплено по этому разделу и категории."""
    audience, kind, category = _rank_where(request.args)
    board = rank_cats.board_key(audience, kind)
    try:
        moved = rank_op.movement(board, category=category)
    except rank_op.RankError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(titles=titles_op.known(), audience=audience, kind=kind,
                   **moved)


@app.post("/api/rank/refresh")
def api_rank_refresh():
    """Запрашивает рейтинг и дописывает сегодняшний день.

    Только по кнопке: по расписанию сайт не опрашивается.
    """
    payload = request.json or {}
    audience, kind, category = _rank_where(payload)
    board = rank_cats.board_key(audience, kind)

    client = _rank_client()
    try:
        found = rank_net.fetch(client, audience=audience, kind=kind,
                               category=category)
    except rank_net.Diagnosis as exc:
        # Подробности вместо общих слов: по ним видно, сел ли сайт,
        # сменилась ли разметка или дело только в шрифте.
        return jsonify(error=str(exc), details=exc.details), 502
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 502
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}",
                       details={"http": str(exc)}), 502
    finally:
        client.close()

    previous = rank_op.load(rank_op.days(board, category)[0], board, category) \
        if rank_op.days(board, category) else None
    same = previous is not None and previous.version and \
        previous.version == found["version"]

    rank_op.save(found["rows"], board, category=found["category"],
                 version=found["version"], stats_date=found["stats_date"])
    return jsonify(saved=len(found["rows"]), decoded=found["decoded"],
                   same_version=same, audience=audience, kind=kind,
                   # 2.5: подробности разбора шрифта. Без них «названия
                   # расшифровать не удалось» не говорит, что чинить.
                   font=found.get("font") or {},
                   **rank_op.movement(board, category=found["category"]))


@app.get("/api/rank/cover/<book_id>")
def api_rank_cover(book_id: str):
    """Отдаёт обложку из своего кэша (2.3 ТЗ).

    Адрес на сайте подписан и с сроком действия: в сохранённом срезе он
    протухает, а срезы хранятся месяцами. Поэтому картинка берётся из
    `data/covers`, а если её там нет — скачивается по адресу из среза и
    остаётся в кэше навсегда.
    """
    if not covers.safe_id(book_id):
        return jsonify(error="Плохой код книги"), 400

    if not covers.have(book_id):
        source = (request.args.get("url") or "").strip()
        if not source:
            return jsonify(error="Обложки нет в кэше"), 404
        client = _rank_client()
        try:
            if not covers.fetch(client, book_id, source):
                return jsonify(error="Обложку скачать не удалось"), 502
        finally:
            client.close()

    path = covers.path_for(book_id)
    # Тип определяем по самим байтам: расширение у нас одно на все, а
    # объявленный не тот формат браузер просто не покажет.
    # Кэш навсегда: имя файла — код книги, а картинка у книги одна.
    return send_file(path, mimetype=covers.mimetype_of(path),
                     max_age=31536000)


@app.get("/api/rank/book/<book_id>")
def api_rank_book(book_id: str):
    """Подробности книги для раскрытой строки (2.4 ТЗ).

    Данные подтягиваются лениво — по первому раскрытию — и кладутся в
    `data/books/{bookId}.json`. Ходить на сайт при каждом клике незачем:
    описание и жанр у книги меняются раз в месяц.
    """
    if not covers.safe_id(book_id):
        return jsonify(error="Плохой код книги"), 400

    # Перевод описания приезжает вместе с карточкой (3.1 ТЗ): переключатель
    # «原/RU» должен знать сразу, есть ли что показывать по второй кнопке.
    ru_text = titles_op.abstract_of(book_id)

    fresh = request.args.get("fresh") == "1"
    if not fresh:
        found = books_op.load(book_id)
        if found is not None:
            return jsonify(**found, abstract_ru=ru_text, cached=True)

    client = _rank_client()
    try:
        found = rank_net.fetch_book(client, book_id)
    except rank_net.Diagnosis as exc:
        return jsonify(error=str(exc), details=exc.details), 502
    except sources.SourceBroken as exc:
        return jsonify(error=str(exc)), 502
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except HttpError as exc:
        return jsonify(error=f"Сайт недоступен: {exc}"), 502
    finally:
        client.close()

    return jsonify(**books_op.save(book_id, found), abstract_ru=ru_text,
                   cached=False)


@app.post("/api/rank/abstract")
def api_rank_abstract():
    """Перевод описания одной книги (3.1 ТЗ).

    По кнопке и по одной книге: описаний полсотни на срез, а читают из них
    два-три. Гнать все в модель ради «вдруг откроют» — полсотни лишних
    запросов на каждый снятый рейтинг.
    """
    payload = request.json or {}
    book_id = str(payload.get("book_id") or "").strip()
    if not covers.safe_id(book_id):
        return jsonify(error="Плохой код книги"), 400

    text = (payload.get("text") or "").strip()
    if not text:
        # Описание уже лежит в кэше карточки: строку раскрывали, иначе
        # кнопке «перевести» было бы неоткуда взяться.
        card = books_op.load(book_id) or {}
        text = str(card.get("abstract") or "").strip()

    client = _llm_client(payload)
    try:
        return jsonify(book_id=book_id, abstract=titles_op.translate_abstract(
            book_id, text, client,
            model=(payload.get("model") or "").strip(),
            force=bool(payload.get("force"))))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except NoKeysLeft as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


@app.post("/api/find/translate")
def api_find_translate():
    """Перевод названия одной найденной книги.

    Книгу могли найти по коду, мимо рейтинга — тогда перевода у неё нет
    ниоткуда, а имя папки из иероглифов не собрать (3.2 ТЗ). Кладём в то
    же хранилище, что и рейтинг: у книги один код и один перевод.
    """
    payload = request.json or {}
    code = str(payload.get("code") or "").strip()
    name = (payload.get("name") or "").strip()
    if not code or not name:
        return jsonify(error="Нужны код книги и её название."), 400

    client = _llm_client(payload)
    try:
        row = rank_net.RankRow(book_id=code, name=name)
        done = titles_op.translate([row], client,
                                  model=(payload.get("model") or "").strip(),
                                  force=bool(payload.get("force")))
        translated = (done.get("titles") or {}).get(code, "")
        if not translated:
            return jsonify(error="Модель не вернула перевод названия."), 502
        return jsonify(code=code, translated=translated,
                       folder=naming.folder_name(name, code=code,
                                                 translated=translated))
    except NoKeysLeft as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


@app.post("/api/rank/translate")
def api_rank_translate():
    """Прогоняет названия через модель. Кэш по book_id."""
    payload = request.json or {}
    audience, kind, category = _rank_where(payload)
    board = rank_cats.board_key(audience, kind)
    day = (payload.get("day") or "").strip()

    snapshot = rank_op.load(day, board, category) if day else None
    if snapshot is None:
        found = rank_op.days(board, category)
        snapshot = rank_op.load(found[0], board, category) if found else None
    if snapshot is None:
        return jsonify(error="Срезов пока нет — сначала обновите рейтинг"), 400

    client = _llm_client()
    try:
        return jsonify(**titles_op.translate(
            snapshot.rows, client,
            model=(payload.get("model") or "").strip(),
            force=bool(payload.get("force"))))
    except NoKeysLeft as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


# ------------------------------------------- пересказ и выгрузка (3.5)


def _export_path(payload: dict, root: Path, default: str) -> Path:
    """Куда писать выгрузку. По умолчанию — рядом с реестром."""
    chosen = (payload.get("path") or "").strip()
    if chosen:
        return Path(chosen).expanduser()
    fmt = (payload.get("format") or ".md").strip().lower()
    if not fmt.startswith("."):
        fmt = "." + fmt
    return root / "analysis" / f"{default}{fmt}"


@app.post("/api/retell/chapters")
def api_retell_chapters():
    """Пересказ по главам. Из собранных фактов, без новых запросов."""
    payload = request.json or {}
    registry = analyze_op.load_registry(_book_root(payload))
    items = retell_op.chapters(registry)
    return jsonify(chapters=[i.as_dict() for i in items],
                   total=len(items),
                   text=retell_op.chapters_text(registry))


@app.post("/api/retell/annotation")
def api_retell_annotation():
    """Аннотация книги. Один запрос к модели."""
    payload = request.json or {}
    registry = analyze_op.load_registry(_book_root(payload))
    client = _llm_client()
    try:
        return jsonify(**retell_op.annotation(
            registry, client, model=(payload.get("model") or "").strip()))
    except retell_op.RetellError as exc:
        return jsonify(error=str(exc)), 400
    except BadKey as exc:
        return jsonify(error=str(exc)), 401
    except LlmError as exc:
        return jsonify(error=str(exc)), 502
    finally:
        client.close()


@app.post("/api/export")
def api_export():
    """Выгрузка карточек, пересказа или аннотации в .md или .docx."""
    payload = request.json or {}
    root = _book_root(payload)
    what = (payload.get("what") or "cards").strip()
    registry = analyze_op.load_registry(root)

    if what == "cards":
        kind = (payload.get("type") or "персонаж").strip()
        text = glossary_op.cards_text(registry, kind)
        default = f"карточки-{kind}"
    elif what == "retell":
        text = retell_op.chapters_text(registry)
        default = "пересказ"
    elif what == "glossary":
        text = glossary_op.dump(registry, (payload.get("glossary_format") or "txt"))
        default = "глоссарий"
    elif what == "text":
        # Аннотация уже показана на экране — второй раз её не запрашиваем.
        text = str(payload.get("text") or "")
        default = "аннотация"
    else:
        return jsonify(error=f"Нечего выгружать: {what}"), 400

    try:
        saved = docs_op.save(text, _export_path(payload, root, default),
                             style=Style.from_dict(payload.get("style")))
    except docs_op.ExportError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(saved=saved, length=len(text))


# ------------------------------------------- вкладка «Инструменты»


def _rules(payload: dict) -> list:
    """Правила замены из запроса либо из словаря книги."""
    rules = payload.get("rules")
    if isinstance(rules, list) and rules:
        return [replace_op.Rule.from_dict(r) for r in rules]
    text = payload.get("dictionary")
    if isinstance(text, str) and text.strip():
        return replace_op.parse_dictionary(text)
    return []


@app.post("/api/replace/preview")
def api_replace_preview():
    """Все совпадения с контекстом. На диск ничего не пишется."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**replace_op.preview(targets, _rules(payload)).as_dict())
    except replace_op.ReplaceError as exc:
        return jsonify(error=str(exc)), 400
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/replace/start")
def api_replace_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400

    try:
        rules = _rules(payload)
        if not rules:
            return jsonify(error="Нечего заменять: правило пустое"), 400
        output_dir = _prepare(base, folder, "replace")
    except replace_op.ReplaceError as exc:
        return jsonify(error=str(exc)), 400
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    # Снятые галочки приходят четвёрками «файл, абзац, правило, номер».
    skip = {(str(s[0]), int(s[1]), int(s[2]), int(s[3]))
            for s in (payload.get("skip") or []) if len(s) == 4}

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="replace",
        meta={"targets": targets, "rules": len(rules)},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "replace", "message": "Заменяем…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, replace_op.run(
            targets, Path(job.output_dir), rules, skip=skip,
            progress=_progress(job, "Файл"),
        ), "Записано")

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/dictionary/load")
def api_dictionary_load():
    """Словарь автозамен книги. Свой у каждой — лежит рядом с ней."""
    payload = request.json or {}
    root = _book_root(payload)
    path = replace_op.dictionary_path(root)
    text = ""
    if path.is_file():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return jsonify(error=f"Не удалось прочитать словарь: {exc}"), 400
    return jsonify(text=text, path=str(path),
                   rules=len(replace_op.parse_dictionary(text)))


@app.post("/api/dictionary/save")
def api_dictionary_save():
    payload = request.json or {}
    root = _book_root(payload)
    try:
        path = replace_op.save_dictionary(root, payload.get("text") or "")
    except OSError as exc:
        return jsonify(error=f"Не удалось сохранить словарь: {exc}"), 400
    return jsonify(path=str(path),
                   rules=len(replace_op.parse_dictionary(payload.get("text") or "")))


@app.post("/api/dictionary/summary")
def api_dictionary_summary():
    """Сколько замен даст каждое правило — сводка до применения."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    rules = _rules(payload)
    if not rules:
        return jsonify(error="Словарь пуст"), 400
    try:
        return jsonify(**replace_op.dictionary_summary(targets, rules))
    except replace_op.ReplaceError as exc:
        return jsonify(error=str(exc)), 400
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/compare/start")
def api_compare_start():
    """Сверка оригинала и перевода по номерам глав."""
    payload = request.json or {}
    original = _targets({"targets": payload.get("original")})
    translated = _targets({"targets": payload.get("translated")})

    if not original or not translated:
        return jsonify(error="Выберите обе папки: оригинал и перевод"), 400

    kinds = payload.get("kinds")
    kinds = [k for k in kinds if k in compare_op.KINDS] if isinstance(kinds, list) else None
    try:
        return jsonify(**compare_op.check(original, translated, kinds).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/api/compare/kinds")
def api_compare_kinds():
    return jsonify(kinds=[{"key": k, "name": v} for k, v in compare_op.KINDS.items()])



# ------------------------------- журнал, корзина и сравнение версий


@app.get("/api/history/state")
def api_history_state():
    """Что делалось и что можно вернуть."""
    return jsonify(**history_op.state())


@app.post("/api/history/restore")
def api_history_restore():
    """Возвращает файлы из копии на место."""
    payload = request.json or {}
    backup = (payload.get("backup") or "").strip()
    target = (payload.get("target") or "").strip()
    if not backup or not target:
        return jsonify(error="Нужны и копия, и папка, куда возвращать"), 400
    try:
        count = history_op.restore(Path(backup), Path(target))
    except history_op.RestoreError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(restored=count, **history_op.state())


@app.post("/api/diff")
def api_diff():
    """Что изменилось: до операции и после."""
    payload = request.json or {}
    before = (payload.get("before") or "").strip()
    after = (payload.get("after") or "").strip()
    if not before or not after:
        return jsonify(error="Укажите обе стороны сравнения"), 400
    try:
        return jsonify(**diff_op.compare(before, after).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400



# ------------------------------- статистика, шапка и подпись


@app.post("/api/stats")
def api_stats():
    """Сколько глав, символов, слов и сколько это читать."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**stats_op.collect(targets).as_dict())
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/api/signature/placeholders")
def api_signature_placeholders():
    return jsonify(placeholders=[{"key": k, "name": v}
                                 for k, v in signature_op.PLACEHOLDERS.items()])


@app.post("/api/signature/preview")
def api_signature_preview():
    """Как будет выглядеть первая глава. На диск ничего не пишется."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        template = signature_op.Template.from_dict(payload.get("template"))
        return jsonify(**signature_op.preview(targets, template))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/signature/start")
def api_signature_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    template = signature_op.Template.from_dict(payload.get("template"))

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base or not folder:
        return jsonify(error="Укажите, куда сохранить"), 400
    if template.empty:
        return jsonify(error="Шаблоны пусты: нечего добавлять"), 400

    try:
        output_dir = _prepare(base, folder, "signature")
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="signature",
        meta={"targets": targets},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "signature", "message": "Дописываем…",
                    "done": 0, "total": 0, "written": 0, "failed": 0}

    def work(job: Job):
        _finish(job, signature_op.run(
            targets, Path(job.output_dir), template,
            prep=PrepOptions.from_dict(payload.get("prep")),
            style=Style.from_dict(payload.get("style")),
            progress=_progress(job, "Глава"),
        ), "Записано")

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------ читалка (4.4)


@app.post("/api/reader/list")
def api_reader_list():
    """Список глав — по нему интерфейс строит переход стрелками."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**reader_op.listing(targets))
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/reader/open")
def api_reader_open():
    """Одна глава в том виде, в каком уйдёт в файл."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400

    # Пустой список сохраняем как есть: это снятая галочка «подсветить
    # находки», а не просьба проверить всё подряд.
    kinds = payload.get("kinds")
    if isinstance(kinds, list):
        kinds = [k for k in kinds if k in textcheck.ALL_KINDS]

    try:
        page = reader_op.open_at(
            targets,
            index=payload.get("index") or 0,
            prep=PrepOptions.from_dict(payload.get("prep")),
            kinds=kinds,
        )
    except (ReadError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(**page.as_dict())


@app.post("/api/reader/save")
def api_reader_save():
    """Правка поверх исходного файла — единственное такое место."""
    payload = request.json or {}
    source = (payload.get("source") or "").strip()
    if not source:
        return jsonify(error="Не указана глава"), 400
    try:
        return jsonify(**reader_op.save(source, payload.get("text") or ""))
    except reader_op.SaveError as exc:
        return jsonify(error=str(exc)), 400


# ------------------------------------------------ орфография (4.9)


def _spell_root(payload: dict, targets: list[str]) -> Path:
    """Где лежит книга: оттуда свой словарь и реестр имён."""
    folder = (payload.get("folder") or "").strip()
    if folder:
        return Path(folder).expanduser()
    first = Path(targets[0]).expanduser()
    return first if first.is_dir() else first.parent


@app.post("/api/spelling/state")
def api_spelling_state():
    """Есть ли словарь и что уже внесено в свой список."""
    payload = request.json or {}
    targets = _targets(payload)
    folder = _spell_root(payload, targets) if targets else ""
    return jsonify(**spelling_op.state(folder))


@app.post("/api/spelling/start")
def api_spelling_start():
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not spelling_op.available():
        return jsonify(
            error="Словарь не установлен. Поставьте пакеты: "
                  "pip install pymorphy3 pymorphy3-dicts-ru",
            need_package=True), 422

    root = _spell_root(payload, targets)
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="spelling",
        meta={"targets": targets},
        output_dir=str(root),
    )
    job.progress = {"stage": "spelling", "message": "Читаем словарь…",
                    "done": 0, "total": 0}

    def work(job: Job):
        report = spelling_op.check(
            targets, folder=root,
            use_registry=bool(payload.get("use_registry", True)),
            progress=_progress(job, "Глава"),
        )
        job.report = report.as_dict()
        job.progress.update(
            stage="done",
            message=(f"Готово. Незнакомых слов {len(report.findings)} "
                     f"на {report.words} слов текста"))

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/spelling/known")
def api_spelling_known():
    """Кнопка «это имя»: слово уходит в свой словарь книги."""
    payload = request.json or {}
    targets = _targets(payload)
    words = [str(w) for w in (payload.get("words") or []) if str(w).strip()]
    if not words:
        return jsonify(error="Нечего добавлять"), 400

    root = _spell_root(payload, targets) if targets else None
    if root is None:
        return jsonify(error="Не понятно, к какой книге относить слово"), 400
    try:
        spelling_op.add_words(root, words)
    except OSError as exc:
        return jsonify(error=f"Не удалось записать словарь: {exc}"), 400
    return jsonify(**spelling_op.state(root))


# ------------------------------------------------ очередь задач (4.6)

#: Что умеет очередь. Ключ — вид шага, значение — как его назвать.
QUEUE_KINDS = {
    "split": "Разбить на главы",
    "merge": "Объединить в один файл",
    "rename": "Переименовать",
    "clean": "Очистить текст",
    "replace": "Замена по словарю",
    "signature": "Шапка и подпись",
    "check": "Проверить текст",
    "spelling": "Проверить орфографию",
    "stats": "Статистика",
}


def _step_targets(step, previous: str) -> list[str]:
    """Что берём на вход.

    Пустой список — значит «то, что вышло из предыдущего шага». На этом
    держится вся цепочка: разбить → переименовать → проверить.
    """
    targets = _targets(step.params)
    if targets:
        return targets
    if not previous:
        raise ValueError("Шагу нечего обрабатывать: нет ни выбора, ни "
                         "результата предыдущего шага")
    return [previous]


def _step_output(step, kind: str) -> Path:
    base = (step.params.get("base") or "").strip()
    folder = (step.params.get("folder") or "").strip()
    if not base or not folder:
        raise ValueError("Укажите, куда сохранить результат шага")
    return _prepare(base, folder, kind)


def _run_step(step, previous: str, cancel: threading.Event) -> tuple[str, str]:
    """Выполняет один шаг очереди. Возвращает (итог, папка результата).

    Шаги делают ровно то же, что кнопки на вкладках, — те же функции из
    `ops`. Иначе очередь начала бы жить своей жизнью и расходиться с ними.
    """
    kind = step.kind
    params = step.params
    targets = _step_targets(step, previous)
    progress = Progress(cancel=cancel)

    if kind == "split":
        out = _step_output(step, kind)
        report = split_op.run(
            targets, out, out_format=_out_format(params),
            parts=_parts(params), pattern=_pattern(params),
            prep=PrepOptions.from_dict(params.get("prep")),
            encoding=_encoding(params), progress=progress)
        return f"Записано {report.written} из {report.total}", str(out)

    if kind == "merge":
        base = (params.get("base") or "").strip()
        name = (params.get("folder") or params.get("name") or "книга").strip()
        if not base:
            raise ValueError("Укажите, куда сохранить результат шага")
        out = Path(base).expanduser() / f"{name}{_out_format(params)}"
        out.parent.mkdir(parents=True, exist_ok=True)
        report = merge_op.run(
            targets, out, order=_order(params),
            headings=bool(params.get("headings", True)),
            encoding=_encoding(params),
            prep=PrepOptions.from_dict(params.get("prep")),
            progress=progress)
        return f"Собрано {report.written} глав в {out.name}", str(out)

    if kind == "rename":
        out = _step_output(step, kind)
        chapters = rename.scan(targets[0], _pattern(params))
        rows = rename.make_plan(
            chapters, rename.NameFormat.from_dict(params.get("format")))
        report = rename.apply_plan(
            rows, out, fmt=(params.get("out_format") or "txt").strip().lower(),
            cancel=cancel)
        return f"Переименовано {report.written} из {report.total}", str(out)

    if kind == "clean":
        out = _step_output(step, kind)
        kinds = params.get("kinds")
        kinds = list(cleanup.ALL_KINDS) if kinds is None else kinds
        cleanup._validate(kinds)
        fixed = written = 0
        for target in targets:
            report = cleanup.clean(target, kinds, out, cancel=cancel)
            fixed += sum(report.counts.values())
            written += report.written
        return f"Исправлено {fixed} мест в {written} файлах", str(out)

    if kind == "replace":
        out = _step_output(step, kind)
        rules = params.get("rules") or []
        report = replace_op.run(
            targets, out, rules, out_format=(params.get("format") or ""),
            encoding=_encoding(params), progress=progress)
        return f"Записано {report.written} из {report.total}", str(out)

    if kind == "signature":
        out = _step_output(step, kind)
        report = signature_op.run(
            targets, out, signature_op.Template.from_dict(params.get("template")),
            prep=PrepOptions.from_dict(params.get("prep")),
            encoding=_encoding(params), progress=progress)
        return f"Записано {report.written} из {report.total}", str(out)

    if kind == "check":
        kinds = params.get("kinds") or list(textcheck.ALL_KINDS)
        report = textcheck.check(targets, kinds=kinds, cancel=cancel)
        # Проверка ничего не пишет — следующий шаг работает с тем же входом.
        return (f"Находок {len(report.findings)} в {report.files_with_findings} "
                f"файлах из {report.files_checked}"), previous

    if kind == "spelling":
        report = spelling_op.check(targets, progress=progress)
        return (f"Незнакомых слов {len(report.findings)} "
                f"на {report.words} слов текста"), previous

    if kind == "stats":
        report = stats_op.collect(targets).as_dict()
        return (f"Глав {report['chapters']}, символов {report['characters']}, "
                f"чтения примерно {report['reading_time']}"), previous

    raise ValueError(f"Неизвестный шаг очереди: {kind}")


@app.get("/api/queue/state")
def api_queue_state():
    """Сохранённые очереди и виды шагов, из которых их собирают."""
    return jsonify(
        queues=[q.as_dict() for q in queue_op.all_queues()],
        kinds=[{"key": k, "name": v} for k, v in QUEUE_KINDS.items()],
    )


@app.post("/api/queue/save")
def api_queue_save():
    payload = request.json or {}
    queue = queue_op.Queue.from_dict(payload.get("queue"))
    unknown = [s.kind for s in queue.steps if s.kind not in QUEUE_KINDS]
    if unknown:
        return jsonify(error=f"Неизвестный шаг: {', '.join(unknown)}"), 400
    if not queue.steps:
        return jsonify(error="В очереди нет ни одного шага"), 400

    for step in queue.steps:
        step.title = step.title or QUEUE_KINDS[step.kind]
    try:
        queue_op.save(queue)
    except queue_op.QueueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(queues=[q.as_dict() for q in queue_op.all_queues()])


@app.post("/api/queue/remove")
def api_queue_remove():
    payload = request.json or {}
    queue_op.remove((payload.get("name") or "").strip())
    return jsonify(queues=[q.as_dict() for q in queue_op.all_queues()])


@app.post("/api/queue/start")
def api_queue_start():
    """Запускает очередь целиком — ради этого она и заводилась."""
    payload = request.json or {}
    name = (payload.get("name") or "").strip()
    queue = queue_op.get(name) if name else queue_op.Queue.from_dict(
        payload.get("queue"))
    if queue is None or not queue.steps:
        return jsonify(error="Очередь не найдена или пуста"), 400

    unknown = [s.kind for s in queue.steps if s.kind not in QUEUE_KINDS]
    if unknown:
        return jsonify(error=f"Неизвестный шаг: {', '.join(unknown)}"), 400
    queue.reset()
    for step in queue.steps:
        step.title = step.title or QUEUE_KINDS[step.kind]

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="queue",
        meta={"queue": queue.name},
        output_dir="",
    )
    job.progress = {"stage": "queue", "message": "Запускаем очередь…",
                    "done": 0, "total": len(queue.steps),
                    "queue": queue.as_dict()}

    def work(job: Job):
        # Папка результата передаётся из шага в шаг: цепочка «разбить →
        # переименовать» иначе требовала бы вписывать пути руками.
        chain = {"previous": (payload.get("start_from") or "").strip()}

        def perform(step):
            message, output = _run_step(step, chain["previous"], job.cancel)
            chain["previous"] = output or chain["previous"]
            job.output_dir = chain["previous"]
            return message

        def changed(current):
            job.progress.update(done=current.done, total=len(current.steps),
                                queue=current.as_dict(),
                                message=_queue_message(current))

        done = queue_op.run(queue, perform, on_change=changed, cancel=job.cancel)
        job.report = done.as_dict()
        job.progress.update(stage="done", message=_queue_message(done))
        history_op.add(operation="очередь задач", source=done.name,
                       output=chain["previous"], files=done.done,
                       failed=sum(1 for s in done.steps
                                  if s.state == queue_op.FAILED))

    return jsonify(job=start_job(job, work).snapshot())


def _queue_message(queue) -> str:
    if queue.state == queue_op.FAILED:
        broken = next((s for s in queue.steps if s.state == queue_op.FAILED), None)
        return f"Остановились на шаге «{broken.title}»: {broken.message}" if broken \
            else "Очередь остановилась"
    if queue.state == queue_op.DONE:
        return f"Готово. Выполнено шагов: {queue.done} из {len(queue.steps)}"
    if queue.state == queue_op.SKIPPED:
        return "Очередь остановлена"
    current = queue.steps[queue.current] if 0 <= queue.current < len(queue.steps) else None
    return f"Шаг {queue.current + 1} из {len(queue.steps)}: {current.title}" \
        if current else "Запускаем очередь…"


# ------------------------------------------------ вкладка «Проверка текста»


@app.get("/api/check/rules")
def api_check_rules():
    """Правила по группам и пресеты — интерфейс строит галочки по этому."""
    return jsonify(
        groups=checks.grouped(),
        presets=[
            {"key": key, "name": name, "kinds": list(checks.PRESET_KEYS[key])}
            for key, name in checks.PRESETS.items()
        ],
        clean_kinds=[
            {"key": key, "name": name} for key, name in cleanup.KINDS.items()
        ],
    )


@app.post("/api/check/start")
def api_check_start():
    payload = request.json or {}
    targets = _targets(payload)
    # Ключа нет — проверяем всё. Пустой список — это снятые галочки, и это
    # уже ошибка: молча проверять всё подряд нельзя.
    kinds = payload.get("kinds")
    if kinds is None:
        kinds = list(textcheck.ALL_KINDS)

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not kinds:
        return jsonify(error="Отметьте хотя бы одну проверку"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="check",
        meta={"targets": targets, "kinds": kinds},
        output_dir=targets[0],
    )
    job.progress = {"stage": "check", "message": "Читаем файлы…", "done": 0, "total": 0}

    def work(job: Job):
        report = textcheck.check(
            targets, kinds,
            on_progress=lambda done, total: job.progress.update(
                done=done, total=total, message=f"Файл {done} из {total}"),
            cancel=job.cancel,
        )
        job.report = report.as_dict()
        # Текст отчёта держим в задаче — выгрузка берёт его отсюда.
        job.meta["report_text"] = textcheck.report_text(report)
        job.progress.update(
            stage="done",
            message=(f"Готово. Находок {len(report.findings)} "
                     f"в {report.files_with_findings} файлах из {report.files_checked}"),
        )

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/clean/preview")
def api_clean_preview():
    """Сколько замен будет сделано — до того, как что-то записано."""
    payload = request.json or {}
    targets = _targets(payload)
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        # Считаем по всем выбранным целям сразу.
        merged: dict = {}
        total = 0
        unreadable: list = []
        for target in targets:
            kinds = payload.get("kinds")
            result = cleanup.preview(
                target, list(cleanup.ALL_KINDS) if kinds is None else kinds
            )
            total += result["total"]
            unreadable.extend(result["unreadable"])
            for row in result["counts"]:
                merged[row["kind"]] = merged.get(row["kind"], 0) + row["count"]
    except CleanError as exc:
        return jsonify(error=str(exc)), 400

    return jsonify(
        counts=[
            {"kind": k, "kind_name": cleanup.KINDS.get(k, k), "count": v}
            for k, v in sorted(merged.items(), key=lambda kv: -kv[1])
        ],
        total=total,
        unreadable=unreadable,
    )


@app.post("/api/clean/start")
def api_clean_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    # Ключа нет — чистим всё. Пустой список — снятые галочки, это ошибка:
    # молча вычистить всё подряд нельзя, правки необратимы для результата.
    kinds = payload.get("kinds")
    if kinds is None:
        kinds = list(cleanup.ALL_KINDS)

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if not folder:
        return jsonify(error="Введите имя новой папки"), 400

    try:
        cleanup._validate(kinds)
    except CleanError as exc:
        return jsonify(error=str(exc)), 400

    try:
        output_dir = _prepare(base, folder, "clean")
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="clean",
        meta={"targets": targets, "kinds": kinds},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "clean", "message": "Чистим…", "done": 0, "total": 0}

    def work(job: Job):
        # Несколько целей чистим по очереди в одну папку.
        merged: dict = {}
        written = failed = files = 0
        failures: list = []
        for target in targets:
            report = cleanup.clean(
                target, kinds, Path(job.output_dir),
                on_progress=lambda done, total: job.progress.update(
                    done=done, total=total, message=f"Файл {done} из {total}"),
                cancel=job.cancel,
            )
            written += report.written
            failed += report.failed
            files += report.files
            failures.extend(report.failures)
            for key, value in report.counts.items():
                merged[key] = merged.get(key, 0) + value

        job.report = {
            "output_dir": job.output_dir,
            "files": files, "written": written, "failed": failed,
            "total": sum(merged.values()),
            "counts": [
                {"kind": k, "kind_name": cleanup.KINDS.get(k, k), "count": v}
                for k, v in sorted(merged.items(), key=lambda kv: -kv[1]) if v
            ],
            "failed_files": failures,
        }
        job.progress.update(
            stage="done",
            message=(f"Готово. Исправлено {sum(merged.values())} мест "
                     f"в {written} файлах" + (f", ошибок {failed}" if failed else "")),
        )

    return jsonify(job=start_job(job, work).snapshot())


@app.post("/api/open")
def api_open():
    """Открывает файл в программе по умолчанию (Word для .docx и так далее).

    Точное позиционирование на строке средствами Windows недостижимо,
    поэтому открываем файл целиком — искать место человек будет через
    Ctrl+F по скопированному фрагменту.
    """
    payload = request.json or {}
    name = (payload.get("path") or "").strip()
    if not name:
        return jsonify(error="Не указан файл"), 400

    path = Path(name).expanduser()
    if not path.exists():
        return jsonify(error=f"Файл не найден: {path}"), 404

    try:
        opened = platform.open_file(path)
    except platform.OpenError as exc:
        # Не поломка сервера: файл есть, а открыть его нечем. 500 здесь
        # пугал бы зря.
        return jsonify(error=str(exc)), 400

    return jsonify(opened=str(opened))


@app.get("/api/check/<job_id>/report")
def api_check_report(job_id: str):
    """Выгрузка отчёта в .txt."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if job is None or job.kind != "check":
        return jsonify(error="Задача не найдена"), 404
    text = job.meta.get("report_text")
    if not text:
        return jsonify(error="Отчёт ещё не готов"), 409

    return Response(
        text,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="check-report.txt"'},
    )


@app.get("/api/job/<job_id>")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Задача не найдена"), 404
    return jsonify(job=job.snapshot())


@app.post("/api/job/<job_id>/cancel")
def api_cancel(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="Задача не найдена"), 404
    job.cancel.set()
    return jsonify(job=job.snapshot())


@app.post("/api/verify")
def api_verify():
    path = (request.json or {}).get("path", "").strip()
    if not path:
        return jsonify(error="Укажите папку книги"), 400
    try:
        return jsonify(report=verify(Path(path).expanduser()))
    except OSError as exc:
        return jsonify(error=str(exc)), 400


def main() -> None:
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(description="Веб-интерфейс качалки MVLEMPYR")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1", help="менять не рекомендуется")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--proxies", default=PROXY_FILE, help="файл со списком прокси")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        pool = load_pool(args.proxies)
        print(f"  Список прокси: {args.proxies}, адресов — {len(pool)}")
    except (OSError, ValueError) as exc:
        print(f"  Прокси не загружены ({scrub(str(exc))}). Укажите файл в интерфейсе.")

    url = f"http://{args.host}:{args.port}"
    print(f"\n  MVLEMPYR downloader → {url}\n  Ctrl+C чтобы остановить\n")

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
