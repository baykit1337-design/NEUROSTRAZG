"""Локальный веб-интерфейс к качалке.

Сервер слушает только 127.0.0.1: он даёт доступ к файловой системе (выбор
папки), поэтому наружу его выставлять нельзя.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api, booksplit, checks, cleanup, nativedialog, rename  # noqa: E402
from mvl import textcheck, totxt, toword  # noqa: E402
from mvl.totxt import TxtError  # noqa: E402
from mvl.cleanup import CleanError  # noqa: E402
from mvl.source import SourceError  # noqa: E402
from mvl.textprep import PrepOptions  # noqa: E402
from mvl.toword import ConvertError  # noqa: E402
from mvl.rename import RenameError  # noqa: E402
from mvl.booksplit import Cancelled as SplitCancelled  # noqa: E402
from mvl.booksplit import HeadingsNotFound, SplitError  # noqa: E402
from mvl import client as client_mod  # noqa: E402
from mvl.client import Client, HttpError  # noqa: E402
from mvl import downloader as downloader_mod  # noqa: E402
from mvl.downloader import Cancelled, Downloader, verify  # noqa: E402
from mvl.paths import list_dirs, prepare_output_dir  # noqa: E402
from mvl import proxies as proxies_mod  # noqa: E402
from mvl.proxies import PROXY_FILE, ProxyPool, scrub  # noqa: E402
from mvl.word import DocxUnavailable, Style  # noqa: E402

log = logging.getLogger(__name__)

#: Потолок таймаута из ТЗ: прокси иногда подключается очень долго.
MAX_TIMEOUT = 300

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
        }


def start_job(job: Job, work) -> Job:
    """Запускает работу в фоне, ошибки складывает в саму задачу."""

    def runner():
        try:
            work(job)
        except SplitCancelled:
            job.progress["stage"] = "cancelled"
            job.progress["message"] = "Остановлено."
        except Cancelled:
            job.progress["stage"] = "cancelled"
            job.progress["message"] = "Остановлено. Прогресс сохранён."
        except Exception as exc:  # noqa: BLE001 — показываем пользователю любую поломку
            log.exception("Задача %s упала", job.id)
            job.error = scrub(f"{type(exc).__name__}: {exc}")
            job.progress["stage"] = "error"
            job.progress["message"] = job.error

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


# ------------------------------------------------------------------- API


@app.post("/api/find")
def api_find():
    query = (request.json or {}).get("query", "").strip()
    if not query:
        return jsonify(error="Введите ссылку, слаг или код книги"), 400

    client = Client()
    try:
        novel = api.find_novel(client, query)
        return jsonify(novel=novel.to_dict())
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
        output_dir = prepare_output_dir(base, folder)
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

    def work(job: Job):
        client = Client(timeout=read_timeout, connect_timeout=connect_timeout)
        downloader = Downloader(
            client=client,
            pool=pool,
            on_progress=lambda p: job.progress.update(p.as_dict()),
            cancel_event=job.cancel,
            threads=threads,
        )
        try:
            job.report = downloader.run(novel, output_dir, first=first, last=last).as_dict()
        finally:
            client.close()

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------------- вкладка «Разбить книгу»


@app.post("/api/split/preview")
def api_split_preview():
    """Сколько глав нашлось и первые названия — до записи на диск."""
    payload = request.json or {}
    path = (payload.get("path") or "").strip()
    pattern = (payload.get("pattern") or "").strip() or None

    if not path:
        return jsonify(error="Выберите файл книги (.epub или .txt)"), 400

    try:
        return jsonify(preview=booksplit.preview(path, pattern).as_dict())
    except HeadingsNotFound as exc:
        # Наугад не режем — просим своё регулярное выражение.
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except SplitError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/split/start")
def api_split_start():
    payload = request.json or {}
    path = (payload.get("path") or "").strip()
    base = (payload.get("base") or "").strip()
    folder = (payload.get("folder") or "").strip()
    fmt = (payload.get("format") or booksplit.FORMAT_TXT).strip().lower()
    pattern = (payload.get("pattern") or "").strip() or None

    if not path:
        return jsonify(error="Выберите файл книги"), 400
    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not folder:
        return jsonify(error="Введите имя папки"), 400
    if fmt not in (booksplit.FORMAT_TXT, booksplit.FORMAT_DOCX):
        return jsonify(error=f"Неизвестный формат: {fmt}"), 400

    # Разбираем до создания папки, чтобы не плодить пустые каталоги.
    try:
        chapters = booksplit.read_chapters(path, pattern)
    except HeadingsNotFound as exc:
        return jsonify(error=str(exc), need_pattern=True, pattern=exc.pattern), 422
    except SplitError as exc:
        return jsonify(error=str(exc)), 400

    try:
        output_dir = prepare_output_dir(base, folder)
    except (OSError, ValueError) as exc:
        return jsonify(error=f"Не удалось создать папку: {exc}"), 400

    style = Style.from_dict(payload.get("style"))
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="split",
        meta={"source": path, "format": fmt, "total": len(chapters)},
        output_dir=str(output_dir),
    )
    job.progress = {"stage": "split", "message": f"Пишем {len(chapters)} глав…",
                    "done": 0, "total": len(chapters), "written": 0, "failed": 0}

    def work(job: Job):
        def on_progress(done: int, total: int):
            job.progress.update(done=done, total=total, message=f"Глава {done} из {total}")

        try:
            report = booksplit.write_chapters(
                chapters,
                Path(job.output_dir),
                fmt=fmt,
                style=style,
                on_progress=on_progress,
                cancel=job.cancel,
            )
        except DocxUnavailable as exc:
            raise SplitError(str(exc)) from exc

        job.report = report.as_dict()
        job.progress.update(
            stage="done",
            written=report.written,
            failed=report.failed,
            message=(
                f"Готово. Записано {report.written} из {report.total}"
                + (f", ошибок {report.failed}" if report.failed else "")
            ),
        )

    return jsonify(job=start_job(job, work).snapshot())


# --------------------------------------- вкладка «Переименование и деление»


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
        skip_service=bool(payload.get("skip_service", True)),
    )
    return chapters, rows


@app.post("/api/rename/scan")
def api_rename_scan():
    """Список глав в папке: имя, номер, объём, признак служебного файла."""
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
        service=sum(1 for c in chapters if c.service),
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
    fmt = (payload.get("out_format") or "txt").strip().lower()

    if not base:
        return jsonify(error="Выберите папку, где создать каталог"), 400
    if not out_name:
        return jsonify(error="Введите имя новой папки"), 400
    if fmt not in ("txt", "docx"):
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
        output_dir = prepare_output_dir(base, out_name)
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


# ----------------------------------------------------- вкладка «В Word»


def _targets(payload: dict) -> list[str]:
    """Что выбрано: список файлов и/или папок."""
    targets = payload.get("targets")
    if isinstance(targets, str):
        targets = [targets]
    if not targets:
        one = (payload.get("folder_in") or payload.get("target") or "").strip()
        targets = [one] if one else []
    return [str(t).strip() for t in targets if str(t).strip()]


@app.post("/api/word/scan")
def api_word_scan():
    """Читается сразу после выбора — отдельной кнопки «Прочитать» больше нет."""
    targets = _targets(request.json or {})
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**toword.scan(targets))
    except (ConvertError, SourceError) as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/word/start")
def api_word_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    name = (payload.get("name") or "").strip()
    mode = (payload.get("mode") or toword.MODE_SINGLE).strip()

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if not name:
        return jsonify(error="Введите имя документа или папки"), 400
    if mode not in toword.MODES:
        return jsonify(error=f"Неизвестный режим: {mode}"), 400

    try:
        info = toword.scan(targets)
    except (ConvertError, SourceError) as exc:
        return jsonify(error=str(exc)), 400

    base_dir = Path(base).expanduser()
    if not base_dir.is_dir():
        return jsonify(error=f"Папка не найдена: {base_dir}"), 400

    clean = rename.safe_filename(name)
    output = base_dir / (f"{clean}.docx" if mode == toword.MODE_SINGLE else clean)

    style = Style.from_dict(payload.get("style"))
    prep = PrepOptions.from_dict(payload.get("prep"))
    total = info["total"]
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="word",
        meta={"targets": targets, "mode": mode, "total": total},
        output_dir=str(output),
    )
    job.progress = {"stage": "word", "message": f"Собираем {total} глав…",
                    "done": 0, "total": total, "written": 0, "failed": 0}

    def work(job: Job):
        report = toword.convert(
            targets, output, mode=mode, style=style, prep=prep,
            on_progress=lambda done, total: job.progress.update(
                done=done, total=total, message=f"Глава {done} из {total}"),
            cancel=job.cancel,
        )
        job.report = report.as_dict()
        job.progress.update(
            stage="done", written=report.written, failed=report.failed,
            message=(f"Готово. Собрано {report.written} из {report.total}"
                     + (f", ошибок {report.failed}" if report.failed else "")),
        )

    return jsonify(job=start_job(job, work).snapshot())


# ------------------------------------------------------- вкладка «В TXT»


@app.post("/api/txt/scan")
def api_txt_scan():
    targets = _targets(request.json or {})
    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    try:
        return jsonify(**totxt.scan(targets, (request.json or {}).get("order") or totxt.ORDER_NUMBER))
    except TxtError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/txt/start")
def api_txt_start():
    payload = request.json or {}
    targets = _targets(payload)
    base = (payload.get("base") or "").strip()
    name = (payload.get("name") or "").strip()

    if not targets:
        return jsonify(error="Выберите файлы или папку"), 400
    if not base:
        return jsonify(error="Выберите, куда сохранить"), 400
    if not name:
        return jsonify(error="Введите имя файла"), 400

    base_dir = Path(base).expanduser()
    if not base_dir.is_dir():
        return jsonify(error=f"Папка не найдена: {base_dir}"), 400

    order = (payload.get("order") or totxt.ORDER_NUMBER).strip()
    encoding = (payload.get("encoding") or "utf-8").strip()
    if order not in totxt.ORDERS:
        return jsonify(error=f"Неизвестный порядок: {order}"), 400
    if encoding not in totxt.ENCODINGS:
        return jsonify(error=f"Неизвестная кодировка: {encoding}"), 400

    try:
        info = totxt.scan(targets, order)
    except TxtError as exc:
        return jsonify(error=str(exc)), 400

    output = base_dir / f"{rename.safe_filename(name)}.txt"
    job = Job(
        id=uuid.uuid4().hex[:12],
        kind="txt",
        meta={"targets": targets, "total": info["total"]},
        output_dir=str(output),
    )
    job.progress = {"stage": "txt", "message": f"Собираем {info['total']} глав…",
                    "done": 0, "total": info["total"], "written": 0, "failed": 0}

    def work(job: Job):
        report = totxt.build(
            targets, output,
            order=order,
            headings=bool(payload.get("headings", True)),
            separator=(payload.get("separator") or totxt.DEFAULT_SEPARATOR),
            custom_separator=(payload.get("custom_separator") or ""),
            encoding=encoding,
            prep=PrepOptions.from_dict(payload.get("prep")),
            on_progress=lambda done, total: job.progress.update(
                done=done, total=total, message=f"Глава {done} из {total}"),
            cancel=job.cancel,
        )
        job.report = report.as_dict()
        job.progress.update(
            stage="done", written=report.written, failed=report.failed,
            message=(f"Готово. Собрано {report.written} из {report.chapters}, "
                     f"{report.characters} символов"),
        )

    return jsonify(job=start_job(job, work).snapshot())


# -------------------------------------------------- вкладка «Проверка текста»


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
        output_dir = prepare_output_dir(base, folder)
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
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa: S606 — открываем в программе по умолчанию
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        return jsonify(error=f"Не удалось открыть: {type(exc).__name__}: {exc}"), 500

    return jsonify(opened=str(path))


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
