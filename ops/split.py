"""«Разбить»: один файл или папка → множество файлов.

Формат на выходе выбирается независимо от входного: читатель отдаёт главы,
писатель их раскладывает.
"""

from __future__ import annotations

from pathlib import Path

from core import naming
from core.models import Chapter, OpReport
from core.text import PrepOptions

from .base import Progress, collect_files, read_all


def scan(targets) -> dict:
    """Что нашлось на входе — до записи на диск."""
    files = collect_files(targets)
    report = OpReport()
    chapters = read_all(files, report)
    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "total": len(chapters),
        "titles": [chapter.title for chapter in chapters[:5]],
        "unreadable": [failure.as_text() for failure in report.failures],
    }


def split_chapter(chapter: Chapter, count: int) -> list[Chapter]:
    """Делит главу на части по границам абзацев.

    Номер части проставляется обязательно: без него все части получат одно
    имя и затрут друг друга.
    """
    from mvl.rename import split_into_parts

    if count < 2:
        return [chapter]
    pieces = split_into_parts(chapter.paragraphs, count)
    return [
        Chapter(number=chapter.number, part=index, title=chapter.title,
                paragraphs=piece, source=chapter.source)
        for index, piece in enumerate(pieces, 1)
    ]


def run(
    targets,
    output_dir: Path,
    out_format: str = ".txt",
    splits: dict | None = None,
    prep: PrepOptions | None = None,
    style=None,
    headings: bool = True,
    encoding: str = "utf-8",
    progress: Progress | None = None,
) -> OpReport:
    """Раскладывает главы по отдельным файлам."""
    from core import formats

    progress = progress or Progress()
    splits = splits or {}
    report = OpReport(output=str(output_dir))

    files = collect_files(targets)
    chapters = read_all(files, report, progress)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    # Деление глав на части — до записи, чтобы счётчик был честным.
    prepared: list[Chapter] = []
    for chapter in chapters:
        count = int(splits.get(chapter.source, 1) or 1)
        prepared.extend(split_chapter(chapter, count))

    output_dir.mkdir(parents=True, exist_ok=True)
    report.total = len(prepared)
    width = naming.name_width(len(prepared))
    used: set[str] = set()

    for index, chapter in enumerate(prepared, 1):
        progress.check()
        stem = f"{index:0{width}d} - {naming.safe_filename(chapter.title)}"
        if chapter.part:
            stem = f"{index:0{width}d} - {naming.safe_filename(chapter.title)} ({chapter.part})"
        if stem.lower() in used:
            stem = f"{stem} ({index})"
        used.add(stem.lower())

        try:
            formats.write(
                output_dir / f"{stem}{out_format}", [chapter],
                prep=prep, style=style, headings=headings, encoding=encoding,
                title=chapter.title,
            )
            report.written += 1
        except Exception as exc:
            report.fail(f"{stem}{out_format}", "запись", f"{type(exc).__name__}: {exc}")

        progress.step(index, len(prepared), f"Глава {index} из {len(prepared)}")

    return report
