"""Общее для всех операций: прогресс, отмена и раскладка по ядрам."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from core import formats
from core.models import Chapter, OpReport
from core.readers.base import ReadError

log = logging.getLogger(__name__)

#: Служебные файлы, которые программа кладёт рядом с книгой. Формат у них
#: читаемый, но содержанием они не являются: словарь автозамен попадал в
#: сверку отдельной «главой».
SERVICE_FILES = frozenset({
    "replacements.txt",   # словарь автозамен книги
    "whitelist.txt",      # исключения проверки латиницы
    "spelling.txt",       # свои слова для проверки орфографии
    "errors.log",
})


class Cancelled(Exception):
    """Пользователь остановил операцию."""


class Progress:
    """Колбэк `(сделано, всего, текст)` и флаг отмены — один на все вкладки."""

    def __init__(self, on_progress=None, cancel: threading.Event | None = None):
        self.on_progress = on_progress
        self.cancel = cancel or threading.Event()

    def step(self, done: int, total: int, message: str = "") -> None:
        if self.on_progress:
            self.on_progress(done, total, message)

    def check(self) -> None:
        """Проверяется перед каждым шагом и во время пауз."""
        if self.cancel.is_set():
            raise Cancelled()

    def wait(self, seconds: float) -> None:
        if self.cancel.wait(seconds):
            raise Cancelled()


# ------------------------------------------------- раскладка по ядрам


#: С какого числа заданий работу стоит раскладывать по ядрам.
#:
#: Порог высокий нарочно. Отдельный процесс не бесплатен: на Windows он
#: заводится с нуля и заново импортирует наши модули — это доли секунды
#: на процесс. На двух десятках файлов такая плата съела бы весь
#: выигрыш; на пятистах её не видно.
MANY = 100

#: Больше этого числа процессов не заводим, сколько бы ядер ни было.
#: Программа работает на машине человека, и занимать её целиком — не
#: наше дело: он в это время ею пользуется.
MOST = 4


def cores() -> int:
    """Сколько ядер занимаем."""
    return max(1, min(os.cpu_count() or 1, MOST))


def spread(work, jobs, progress: Progress | None = None,
           heavy: bool = False, note: str = "Файл") -> list[str]:
    """Одну и ту же работу — по всем ядрам. Порядок заданий сохраняется.

    `work` — функция уровня модуля: замыкание или метод в другой процесс
    не отправить. Принимает одно задание, возвращает пустую строку, если
    вышло, и текст беды, если нет. Отдавать беду значением, а не
    исключением, приходится потому, что через границу процесса летит
    только то, что умеет засолиться.

    **Процессы, а не нити.** Работа здесь — разбор разметки и упаковка,
    то есть счёт, а счёт в Python нити не делят: интерпретатор держит
    общую блокировку. Замерено на пятистах главах в `.docx`: один поток —
    7.54 с, четыре нити — 7.75 с (то есть ничего), четыре процесса —
    2.62 с.

    Раскладываем не всегда. Лёгкую работу (`heavy=False`) и короткий
    список процессы только замедлят: `.txt` пишется впятеро быстрее, чем
    заводится процесс. Тогда считаем на месте — тем же кодом, чтобы не
    держать два разных пути с разным поведением.
    """
    progress = progress or Progress()
    jobs = list(jobs)
    total = len(jobs)
    troubles = [""] * total

    if not (heavy and total >= MANY and cores() > 1):
        for index, job in enumerate(jobs, 1):
            progress.check()
            try:
                troubles[index - 1] = work(job)
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 — сбой одного задания
                # Ловим и здесь тоже. Через границу процесса исключение
                # не пролетает — там его ловит сам пул, — и без этой
                # ветки одна и та же работа вела бы себя по-разному в
                # зависимости от длины списка. Такое расхождение ищут
                # потом сутками.
                troubles[index - 1] = f"{type(exc).__name__}: {exc}"
            progress.step(index, total, f"{note} {index} из {total}")
        return troubles

    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context

    try:
        # `spawn` везде, а не только там, где он и так по умолчанию:
        # иначе на машине человека работал бы один путь, а проверялся
        # другой. Заодно `fork` из рабочей нити веб-сервера — известный
        # способ получить намертво зависший процесс.
        pool = ProcessPoolExecutor(max_workers=cores(),
                                   mp_context=get_context("spawn"))
    except Exception as exc:  # noqa: BLE001 — без процессов работа не встаёт
        log.warning("Процессы не завелись (%s) — считаем в один поток", exc)
        return spread(work, jobs, progress, heavy=False, note=note)

    done = 0
    try:
        futures = {pool.submit(work, job): at for at, job in enumerate(jobs)}
        for future in _as_they_come(futures):
            progress.check()
            at = futures[future]
            try:
                troubles[at] = future.result()
            except Exception as exc:  # noqa: BLE001 — сбой одного задания
                troubles[at] = f"{type(exc).__name__}: {exc}"
            done += 1
            progress.step(done, total, f"{note} {done} из {total}")
    finally:
        # Отмену слушаем в `progress.check()`; сюда попадаем и по ней.
        # `cancel_futures` снимает то, что ещё не начали, — иначе
        # «Остановить» ждало бы всю очередь.
        pool.shutdown(wait=True, cancel_futures=True)
    return troubles


def _as_they_come(futures):
    """Готовые задания по мере готовности. Отдельной функцией — чтобы
    импорт `as_completed` не висел в шапке модуля ради одной ветки."""
    from concurrent.futures import as_completed

    return as_completed(futures)


def collect_files(targets) -> list[Path]:
    """Разворачивает выбранное в список файлов.

    Принимает пути к файлам и папкам вперемешку: папка раскрывается в свои
    читаемые файлы, файл берётся как есть.

    Разница в обращении с чужим форматом намеренная. В папке он молча
    пропускается — там могут лежать `state.json` и прочее служебное. А вот
    файл, выбранный руками, отвергается сразу: человек указал именно на
    него, и прочитать `.pdf` как текст значит выдать мусор вместо отказа.
    """
    if isinstance(targets, (str, Path)):
        targets = [targets]

    files: list[Path] = []
    seen: set[str] = set()

    for target in targets:
        path = Path(str(target)).expanduser()
        if path.is_dir():
            found = [p for p in sorted(path.iterdir())
                     if p.is_file() and formats.is_readable(p)
                     and p.name.lower() not in SERVICE_FILES]
        elif path.is_file():
            # Через reader_for, а не по расширению: он же решает спор
            # расширения с сигнатурой, и epub, названный .dat, пройдёт.
            formats.reader_for(path)
            found = [path]
        else:
            raise ReadError(f"Не найдено: {path}")

        for item in found:
            key = str(item.resolve())
            if key not in seen:
                seen.add(key)
                files.append(item)

    if not files:
        raise ReadError("Не нашлось файлов поддерживаемых форматов")
    return files


def skipped_files(targets) -> list[str]:
    """Файлы из выбранных папок, которые пропущены по формату (4.2 ТЗ).

    Пропускать их в папке правильно — рядом лежат `state.json` и прочее
    служебное. Но делать это молча нельзя: недостающие главы иначе
    обнаружатся только в готовой книге.
    """
    if isinstance(targets, (str, Path)):
        targets = [targets]

    skipped: list[str] = []
    for target in targets:
        path = Path(str(target)).expanduser()
        if not path.is_dir():
            continue
        for item in sorted(path.iterdir()):
            if not item.is_file() or formats.is_readable(item):
                continue
            if item.name.lower() in SERVICE_FILES:
                continue
            skipped.append(item.name)
    return skipped


def read_all(files: list[Path], report: OpReport, progress: Progress | None = None
             ) -> list[Chapter]:
    """Читает все источники. Сбой одного файла не мешает остальным."""
    chapters: list[Chapter] = []
    for index, path in enumerate(files, 1):
        if progress:
            progress.check()
        try:
            chapters.extend(formats.read(path))
        except ReadError as exc:
            # Формат не распознан — пропускаем файл и идём дальше.
            report.fail(path.name, "чтение", str(exc))
        except Exception as exc:
            report.fail(path.name, "чтение", f"{type(exc).__name__}: {exc}")
        if progress:
            progress.step(index, len(files), f"Читаем {path.name}")
    return chapters
