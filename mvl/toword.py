"""Сборка папки с главами в Word.

Два режима: всё в один документ или отдельный .docx на главу.

Оглавления и титульной страницы здесь нет намеренно — они убраны из ТЗ
вместе с галочками. В документ идут только главы: заголовок стилем
Heading 1, текст абзацами, разрыв страницы между главами.

Молчаливых отказов быть не должно: любая осечка попадает в отчёт с именем
файла, шагом, на котором она случилась, и текстом исключения.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .booksplit import Cancelled
from .rename import READABLE, parse_name, read_paragraphs, safe_filename, sort_chapters
from .rename import Chapter as RenameChapter
from .word import DocxUnavailable, Style, add_chapter, new_document

log = logging.getLogger(__name__)

MODE_SINGLE = "single"
MODE_PER_CHAPTER = "per_chapter"


class ConvertError(Exception):
    """Собрать документ не удалось."""


@dataclass
class Failure:
    """Что именно и на каком шаге сломалось."""

    file: str
    step: str
    error: str

    def as_text(self) -> str:
        return f"{self.file} — {self.step}: {self.error}"

    def as_dict(self) -> dict:
        return {"file": self.file, "step": self.step, "error": self.error}


@dataclass
class ConvertReport:
    output: str = ""
    written: int = 0
    failed: int = 0
    total: int = 0
    failures: list[Failure] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "output": self.output,
            "written": self.written,
            "failed": self.failed,
            "total": self.total,
            "failures": [f.as_dict() for f in self.failures],
            "failed_files": [f.as_text() for f in self.failures],
        }


def collect(folder: str | Path, pattern: str | None = None) -> list[RenameChapter]:
    """Файлы глав из папки в порядке номеров."""
    directory = Path(folder).expanduser()
    if not directory.is_dir():
        raise ConvertError(f"Папка не найдена: {directory}")

    chapters: list[RenameChapter] = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in READABLE:
            chapters.append(RenameChapter(path=path, parts_of_name=parse_name(path.stem, pattern)))

    if not chapters:
        raise ConvertError("В папке нет файлов .txt, .md или .docx")
    return sort_chapters(chapters)


def heading_for(chapter: RenameChapter) -> str:
    """Заголовок главы в документе.

    Порядковый номер файла в заголовок не идёт — он служебный и нужен был
    только для сортировки. Всё остальное из имени сохраняется как есть.
    """
    stem = chapter.path.stem.strip()
    parts = chapter.parts_of_name
    if parts.seq is None:
        return stem

    # Отрезаем ровно «0010 - » в начале, не трогая остальное имя.
    head = re.match(r"^\s*\d+\s*[-–—]\s*", stem)
    return stem[head.end():].strip() if head else stem


def convert(
    folder: str | Path,
    output: Path,
    mode: str = MODE_SINGLE,
    style: Style | None = None,
    pattern: str | None = None,
    on_progress=None,
    cancel: threading.Event | None = None,
) -> ConvertReport:
    """Собирает главы в Word.

    `output` — файл .docx для режима «один документ», иначе папка.
    """
    style = style or Style()
    chapters = collect(folder, pattern)
    report = ConvertReport(output=str(output), total=len(chapters))

    try:
        document = new_document(style) if mode == MODE_SINGLE else None
    except DocxUnavailable as exc:
        raise ConvertError(str(exc)) from exc

    if mode == MODE_SINGLE:
        output.parent.mkdir(parents=True, exist_ok=True)
    else:
        output.mkdir(parents=True, exist_ok=True)

    for index, chapter in enumerate(chapters, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        name = chapter.path.name
        step = "чтение"
        try:
            paragraphs = read_paragraphs(chapter.path)
            text = "\n\n".join(paragraphs)

            if mode == MODE_SINGLE:
                step = "вставка в документ"
                # Разрыв страницы ставим перед главой, кроме самой первой.
                if report.written and style.page_break_between_chapters:
                    document.add_page_break()
                add_chapter(document, heading_for(chapter), text, style)
            else:
                step = "запись файла"
                target = output / f"{safe_filename(chapter.path.stem)}.docx"
                single = new_document(style)
                add_chapter(single, heading_for(chapter), text, style)
                single.save(str(target))

            report.written += 1
        except Exception as exc:
            # Молчаливый отказ недопустим: имя файла, шаг и текст исключения.
            failure = Failure(file=name, step=step, error=f"{type(exc).__name__}: {exc}")
            log.warning("Не собран %s", failure.as_text())
            report.failures.append(failure)
            report.failed += 1

        if on_progress:
            on_progress(index, len(chapters))

    if mode == MODE_SINGLE:
        if not report.written:
            raise ConvertError(
                "Ни одна глава не попала в документ. "
                + (report.failures[0].as_text() if report.failures else "")
            )
        try:
            document.save(str(output))
        except Exception as exc:
            raise ConvertError(f"Документ не сохранён: {type(exc).__name__}: {exc}") from exc

    return report
