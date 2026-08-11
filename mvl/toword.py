"""Сборка глав в Word.

Два сценария, разведённых явно:

- **Собрать в один документ** — все главы (из epub или из папки с файлами)
  складываются в один `.docx`;
- **Разложить по главам** — epub или большой файл раскладывается на
  отдельный `.docx` на каждую главу.

На входе `.epub`, `.txt`, `.md`, `.docx` — один файл или несколько.

Оглавления и титульной страницы нет намеренно. В документ идут только
главы: заголовок стилем Heading 1, текст абзацами, разрыв страницы между
главами.

Молчаливых отказов быть не должно: любая осечка попадает в отчёт с именем
файла, шагом и текстом исключения.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .booksplit import Cancelled
from .rename import safe_filename
from .source import Chapter, SourceError, collect_sources, is_multi_chapter, load_chapters
from .textprep import PrepOptions, prepare
from .word import DocxUnavailable, Style, add_blocks, new_document

log = logging.getLogger(__name__)

MODE_SINGLE = "single"
MODE_PER_CHAPTER = "per_chapter"
MODES = (MODE_SINGLE, MODE_PER_CHAPTER)

#: Подписи режимов для интерфейса.
MODE_LABELS = {
    MODE_SINGLE: "Собрать в один документ",
    MODE_PER_CHAPTER: "Разложить по главам",
}


class ConvertError(Exception):
    """Собрать документ не удалось."""


class NothingToDo(ConvertError):
    """Делать нечего — на входе уже готовые отдельные файлы."""


@dataclass
class Failure:
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


def scan(targets) -> dict:
    """Что нашлось на входе — для показа до запуска."""
    try:
        files = collect_sources(targets)
    except SourceError as exc:
        raise ConvertError(str(exc)) from exc
    chapters, failures = read_all(files)
    return {
        "files": [str(f) for f in files],
        "file_count": len(files),
        "total": len(chapters),
        "titles": [c.title for c in chapters[:5]],
        # Несколько глав в одном файле бывает только у epub.
        "multi_chapter": any(is_multi_chapter(f) for f in files),
        "unreadable": [f.as_text() for f in failures],
    }


def read_all(files: list[Path]) -> tuple[list[Chapter], list[Failure]]:
    """Читает все источники. Сбой одного файла не мешает остальным."""
    chapters: list[Chapter] = []
    failures: list[Failure] = []
    for path in files:
        try:
            chapters.extend(load_chapters(path))
        except SourceError as exc:
            failures.append(Failure(file=path.name, step="чтение", error=str(exc)))
        except Exception as exc:
            failures.append(
                Failure(file=path.name, step="чтение", error=f"{type(exc).__name__}: {exc}")
            )
    return chapters, failures


def convert(
    targets,
    output: Path,
    mode: str = MODE_SINGLE,
    style: Style | None = None,
    prep: PrepOptions | None = None,
    on_progress=None,
    cancel: threading.Event | None = None,
) -> ConvertReport:
    """Собирает главы в Word.

    `output` — файл .docx для режима «собрать в один», иначе папка.
    """
    style = style or Style()
    prep = prep or PrepOptions()

    try:
        files = collect_sources(targets)
    except SourceError as exc:
        raise ConvertError(str(exc)) from exc
    chapters, failures = read_all(files)

    if not chapters:
        detail = failures[0].as_text() if failures else ""
        raise ConvertError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    if mode == MODE_PER_CHAPTER and len(chapters) == len(files) and not any(
        is_multi_chapter(f) for f in files
    ):
        # На входе уже по одной главе на файл — раскладывать нечего.
        raise NothingToDo(
            f"На входе уже отдельные файлы ({len(files)} шт.), раскладывать нечего. "
            "Выберите режим «Собрать в один документ» или добавьте .epub."
        )

    report = ConvertReport(output=str(output), total=len(chapters))
    report.failures.extend(failures)
    report.failed += len(failures)

    try:
        document = new_document(style) if mode == MODE_SINGLE else None
    except DocxUnavailable as exc:
        raise ConvertError(str(exc)) from exc

    if mode == MODE_SINGLE:
        output.parent.mkdir(parents=True, exist_ok=True)
    else:
        output.mkdir(parents=True, exist_ok=True)

    width = max(4, len(str(len(chapters))))
    used: set[str] = set()

    for index, chapter in enumerate(chapters, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        step = "подготовка текста"
        name = Path(chapter.source).name or chapter.title
        try:
            blocks = prepare(chapter.paragraphs, chapter.title, prep)

            if mode == MODE_SINGLE:
                step = "вставка в документ"
                if report.written and style.page_break_between_chapters:
                    document.add_page_break()
                if chapter.title:
                    document.add_heading(chapter.title, level=1)
                add_blocks(document, blocks, style, prep)
            else:
                step = "запись файла"
                stem = safe_filename(chapter.title) or f"{index:0{width}d}"
                if stem.lower() in used:
                    stem = f"{index:0{width}d} - {stem}"
                used.add(stem.lower())

                single = new_document(style)
                if chapter.title:
                    single.add_heading(chapter.title, level=1)
                add_blocks(single, blocks, style, prep)
                single.save(str(output / f"{stem}.docx"))

            report.written += 1
        except Exception as exc:
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
