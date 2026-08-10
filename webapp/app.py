"""Локальный веб-интерфейс к качалке.

Сервер слушает только 127.0.0.1: он даёт доступ к файловой системе (выбор
папки), поэтому наружу его выставлять нельзя.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mvl import api  # noqa: E402
from mvl.client import Client, HttpError  # noqa: E402
from mvl.downloader import Cancelled, Downloader, verify  # noqa: E402
from mvl.paths import list_dirs, prepare_output_dir  # noqa: E402
from mvl.proxies import PROXY_FILE, ProxyPool, scrub  # noqa: E402

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app = Flask(__name__, static_folder=str(STATIC_DIR))


@dataclass
class Job:
    id: str
    novel: dict
    output_dir: str
    progress: dict = field(default_factory=dict)
    report: dict | None = None
    error: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "novel": self.novel,
            "output_dir": self.output_dir,
            "progress": self.progress,
            "report": self.report,
            "error": self.error,
            "cancelled": self.cancel.is_set(),
        }


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
    path = (request.json or {}).get("path", "").strip() or PROXY_FILE
    try:
        pool = load_pool(path)
    except (OSError, ValueError) as exc:
        return jsonify(error=scrub(str(exc))), 400

    pool.check_all()
    payload = pool.to_dict()
    if pool.usable_count == 0:
        payload["warning"] = (
            "Ни один прокси не пропускает до сайта. Напрямую не идём — "
            "этот путь заблокирован. Обновите список и проверьте снова."
        )
    return jsonify(pool=payload, default_path=PROXY_FILE)


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


@app.get("/api/browse")
def api_browse():
    """Обзор папок на этой машине — чтобы выбрать, где создать папку книги."""
    try:
        return jsonify(list_dirs(request.args.get("path")))
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

    job = Job(id=uuid.uuid4().hex[:12], novel=novel.to_dict(), output_dir=str(output_dir))
    job.progress = {"stage": "queued", "message": "Запускаем…", "done": 0, "total": last - first + 1,
                    "downloaded": 0, "skipped": 0, "failed": 0,
                    "proxy": pool.current().label if pool and pool.usable_count else "",
                    "switches": 0}

    def worker():
        client = Client()
        downloader = Downloader(
            client=client,
            pool=pool,
            on_progress=lambda p: job.progress.update(p.as_dict()),
            cancel_event=job.cancel,
        )
        try:
            report = downloader.run(novel, output_dir, first=first, last=last)
            job.report = report.as_dict()
        except Cancelled:
            job.progress["stage"] = "cancelled"
            job.progress["message"] = "Остановлено. Прогресс сохранён."
        except Exception as exc:  # noqa: BLE001 — показываем пользователю любую поломку
            log.exception("Задача %s упала", job.id)
            job.error = f"{type(exc).__name__}: {exc}"
            job.progress["stage"] = "error"
            job.progress["message"] = job.error
        finally:
            client.close()

    job.thread = threading.Thread(target=worker, daemon=True)
    with JOBS_LOCK:
        JOBS[job.id] = job
    job.thread.start()

    return jsonify(job=job.snapshot())


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
