"""Очистка мусорной шапки в начале файлов.

Спарсенные главы приходят с шапкой: название книги, потом название главы,
иногда дважды с разными разделителями. Переводчик видит две строки и
считает, что глав две.

Жёстких правил здесь нет и быть не может — у каждой книги шапка своя.
Считаем повторы: строка, встретившаяся почти во всех файлах папки,
содержанием быть не может.
"""

from __future__ import annotations

from pathlib import Path

from core import formats, naming, text
from core.models import Chapter, OpReport
from core.text import PrepOptions

from .base import Progress, collect_files, read_all


def scan(targets, progress: Progress | None = None) -> dict:
    """Что похоже на шапку и в скольких файлах встретилось."""
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)

    # Файл передаём вместе с текстом: без него находку нельзя открыть и
    # посмотреть, о чём речь, до удаления.
    findings = text.find_headers(
        (chapter.title, chapter.paragraphs, chapter.source)
        for chapter in chapters
    )
    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "total": len(chapters),
        "findings": [f.as_dict() for f in findings],
        "unreadable": [failure.as_text() for failure in report.failures],
    }


def clean_chapter(chapter: Chapter, texts) -> Chapter:
    """Глава без шапки. Исходная не меняется."""
    return Chapter(
        number=chapter.number,
        part=chapter.part,
        title=chapter.title,
        paragraphs=text.strip_headers(chapter.paragraphs, chapter.title, texts),
        source=chapter.source,
    )


def run(
    targets,
    output_dir: Path,
    texts,
    out_format: str = "",
    prep: PrepOptions | None = None,
    style=None,
    encoding: str = "utf-8",
    progress: Progress | None = None,
) -> OpReport:
    """Пишет очищенные главы в новую папку. Оригиналы не трогает.

    `texts` — отмеченные находки. Пустая строка среди них означает «убрать
    дубль названия главы»: сама строка у каждого файла своя.
    Формат на выходе по умолчанию — как у исходного файла.
    """
    progress = progress or Progress()
    report = OpReport(output=str(output_dir))

    files = collect_files(targets)
    chapters = read_all(files, report, progress)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    output_dir.mkdir(parents=True, exist_ok=True)
    report.total = len(chapters)
    width = naming.name_width(len(chapters))
    used: set[str] = set()

    for index, chapter in enumerate(chapters, 1):
        progress.check()
        cleaned = clean_chapter(chapter, texts)

        # Имя и расширение сохраняем: очистка не переименование.
        source = Path(chapter.source) if chapter.source else None
        suffix = out_format or (source.suffix if source else ".txt")
        if source is not None:
            stem = source.stem
        else:
            stem = f"{index:0{width}d} - {naming.safe_filename(chapter.title)}"
        if f"{stem}{suffix}".lower() in used:
            stem = f"{stem} ({index})"
        used.add(f"{stem}{suffix}".lower())

        try:
            formats.write(
                output_dir / f"{stem}{suffix}", [cleaned],
                prep=prep, style=style, headings=True, encoding=encoding,
                title=cleaned.title,
            )
            report.written += 1
        except Exception as exc:
            report.fail(f"{stem}{suffix}", "запись", f"{type(exc).__name__}: {exc}")

        progress.step(index, len(chapters), f"Файл {index} из {len(chapters)}")

    return report
