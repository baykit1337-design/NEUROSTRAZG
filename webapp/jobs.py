"""Фоновые задачи: одна машинка на все вкладки.

`webapp/app.py` вырос до пяти с половиной тысяч строк и ста сорока
маршрутов — править его вслепую стало опасно. Резать начинаем отсюда:
задачи не знают ни про Flask, ни про вкладки, их держит у себя каждая
вторая ручка, и вынести их можно, ничего не меняя по смыслу.

Что здесь: сама задача, её отчёт, запуск в потоке и уборка доигравших.
Чего здесь нет: маршрутов. Они остаются там, где им и место, — рядом с
тем, что делают.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from mvl.proxies import scrub
from ops.base import Cancelled as OpCancelled
from ops.base import Progress

log = logging.getLogger(__name__)


@dataclass
class Made:
    """Готовая папка и след, по которому её вернут как было."""

    dir: Path
    #: Куда легла копия прежнего содержимого. Пусто — копии нет.
    backup: str = ""
    #: Что операция собирается записать.
    wrote: list = field(default_factory=list)


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
    #: Пауза: поднят — работа стоит на ближайшей границе главы и ждёт.
    #: Отмена сильнее паузы, иначе из паузы было бы не выйти.
    paused: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    #: Когда началась и когда закончилась. Время меряет сервер, а не
    #: страница: перезагрузка вкладки не должна сбрасывать секундомер.
    started: float = field(default_factory=time.monotonic)
    finished: float = 0.0
    #: Построчный журнал работы — заводится там, где он нужен (7.7).
    log: object = None
    #: Куда легла копия прежнего содержимого папки и что задача пишет.
    #: Хранится здесь, а не в общем словаре: две задачи в одну папку
    #: затирали бы записи друг друга, а упавшая — оставляла бы свою
    #: навсегда.
    backup: str = ""
    wrote: list = field(default_factory=list)

    def keep(self, made: Made) -> Path:
        """Запомнить, откуда возвращать, и отдать папку результата."""
        self.backup = made.backup
        self.wrote = list(made.wrote)
        return made.dir

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
            "paused": self.paused.is_set(),
            "elapsed": round(self.elapsed, 1),
            "running": self.running,
        }


JOBS: dict[str, Job] = {}
JOBS_LOCK = threading.Lock()

#: Сколько доигравших задач держать и как долго. Задача хранит свой отчёт
#: целиком — со списком ошибок по каждому файлу, — и за день работы на
#: сотнях книг это растёт без предела: до сих пор из `JOBS` не удалялось
#: ничего и никогда.
#:
#: Час и сорок штук — с большим запасом: интерфейсу задача нужна ровно до
#: того мига, когда он дорисует её итог.
KEEP_JOBS = 40
JOB_TTL = 3600.0


def forget_old() -> None:
    """Убирает доигравшие задачи. Звать под `JOBS_LOCK`.

    Работающие не трогаем ни при каких условиях: у задачи, которую сейчас
    показывают, отнимать себя нельзя. Отбор по `finished` это и
    обеспечивает — у работающей его нет вовсе.
    """
    now = time.monotonic()
    done = sorted((job.finished, key) for key, job in JOBS.items()
                  if job.finished)

    stale = {key for when, key in done if now - when > JOB_TTL}
    # Сверх меры — тоже вон, начиная с самых старых.
    stale.update(key for _, key in done[:max(0, len(done) - KEEP_JOBS)])
    for key in stale:
        JOBS.pop(key, None)


def progress_of(job: Job, unit: str) -> Progress:
    """Единый прогресс операции: колбэк и флаг отмены задачи."""
    def on_progress(done: int, total: int, message: str = "") -> None:
        job.progress.update(done=done, total=total,
                            message=message or f"{unit} {done} из {total}")

    return Progress(on_progress, job.cancel)


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
        except Exception as exc:  # noqa: BLE001 — показываем любую поломку
            log.exception("Задача %s упала", job.id)
            job.error = scrub(f"{type(exc).__name__}: {exc}")
            job.progress["stage"] = "error"
            job.progress["message"] = job.error
        finally:
            job.finished = time.monotonic()

    job.thread = threading.Thread(target=runner, daemon=True)
    with JOBS_LOCK:
        forget_old()
        JOBS[job.id] = job
    job.thread.start()
    return job


__all__ = ["JOBS", "JOBS_LOCK", "JOB_TTL", "KEEP_JOBS", "Job", "Made",
           "forget_old", "progress_of", "start_job"]
