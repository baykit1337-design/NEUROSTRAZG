"""«Разбить»: один файл или папка → множество файлов.

Формат на выходе выбирается независимо от входного: читатель отдаёт главы,
писатель их раскладывает.
"""

from __future__ import annotations

from pathlib import Path

from core import headings, naming
from core.headings import HeadingsNotFound
from core.models import Chapter, OpReport
from core.text import PrepOptions

from .base import Progress, collect_files, read_all

#: Сколько названий показывать в предпросмотре.
PREVIEW_TITLES = 5


def gather(targets, pattern: str | None = None, parts: int = 1,
           report: OpReport | None = None, progress: Progress | None = None
           ) -> tuple[list, list[Chapter]]:
    """Файлы и главы со входа, при необходимости разрезанные по заголовкам.

    Книга приходит и набором файлов, и одним куском. Во втором случае
    читатель отдаёт её единственной главой, и её надо резать по
    заголовкам — иначе «разбить» не разбивает ничего.

    Если книга пришла одним файлом, а заголовков в ней не нашлось —
    наугад не режем, а просим шаблон. Молча отдать один файл на выходе
    значит сделать вид, что операция удалась.

    Просьба не выставляется, когда резать и не требовалось: файлов
    несколько, у главы распознан номер (значит, это готовая глава, а не
    книга целиком) или задано деление на части — для него заголовки не
    нужны.
    """
    report = report if report is not None else OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)

    if len(chapters) != 1:
        return files, chapters

    if headings.find(chapters[0].paragraphs, pattern):
        return files, headings.cut(chapters[0], pattern)
    if pattern or (len(files) == 1 and parts < 2 and chapters[0].number is None):
        raise HeadingsNotFound(pattern or headings.DEFAULT_PATTERN)
    return files, chapters


def scan(targets, pattern: str | None = None, parts: int = 1) -> dict:
    """Что нашлось на входе — до записи на диск."""
    report = OpReport()
    files, chapters = gather(targets, pattern, parts, report)
    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "total": len(chapters),
        "titles": [chapter.title for chapter in chapters[:PREVIEW_TITLES]],
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
    parts: int = 1,
    pattern: str | None = None,
    prep: PrepOptions | None = None,
    style=None,
    titles: bool = True,
    encoding: str = "utf-8",
    progress: Progress | None = None,
) -> OpReport:
    """Раскладывает главы по отдельным файлам."""
    from core import formats

    progress = progress or Progress()
    splits = splits or {}
    report = OpReport(output=str(output_dir))

    _, chapters = gather(targets, pattern, parts, report, progress)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    # Деление глав на части — до записи, чтобы счётчик был честным.
    # `splits` задаёт число частей для отдельного файла, `parts` — для всех
    # сразу; частное правило важнее общего.
    prepared: list[Chapter] = []
    for chapter in chapters:
        count = int(splits.get(chapter.source, parts) or 1)
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
                prep=prep, style=style, headings=titles, encoding=encoding,
                title=chapter.title,
            )
            report.written += 1
        except Exception as exc:
            report.fail(f"{stem}{out_format}", "запись", f"{type(exc).__name__}: {exc}")

        progress.step(index, len(prepared), f"Глава {index} из {len(prepared)}")

    return report
