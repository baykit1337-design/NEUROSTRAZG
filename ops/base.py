"""Общее для всех операций: прогресс и отмена."""

from __future__ import annotations

import threading
from pathlib import Path

from core import formats
from core.models import Chapter, OpReport
from core.readers.base import ReadError

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
