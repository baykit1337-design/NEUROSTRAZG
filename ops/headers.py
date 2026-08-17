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


def lines_of(chapters) -> list[str]:
    """Строки файла в том виде, в каком они в нём лежали.

    Читатель забирает первую строку в название главы, и без неё тройка
    «заголовок · название книги · тот же заголовок» распадается — правило
    сдвоенного заголовка не срабатывает. Поэтому название возвращаем на
    место.
    """
    lines: list[str] = []
    for chapter in chapters:
        if chapter.title:
            lines.append(chapter.title)
        lines.extend(chapter.paragraphs)
    return lines


def _by_file(chapters) -> dict:
    """Главы, разложенные по файлам, откуда они прочитаны."""
    grouped: dict[str, list] = {}
    for chapter in chapters:
        grouped.setdefault(str(chapter.source or ""), []).append(chapter)
    return grouped


def scan(targets, progress: Progress | None = None, repeat: int = 0,
         pattern: str = "", offset: int = 0) -> dict:
    """Что похоже на шапку: и между файлами, и внутри каждого из них.

    Книга одним файлом на тысячу глав сравнивать себя не с чем: правило
    «строка почти во всех файлах» находит там ровно одну строку и чистит
    одно место. Поэтому те же правила прогоняются и внутри файла.
    """
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)

    # Файл передаём вместе с текстом: без него находку нельзя открыть и
    # посмотреть, о чём речь, до удаления.
    findings = text.find_headers(
        (chapter.title, chapter.paragraphs, chapter.source)
        for chapter in chapters
    )

    inside = _scan_inside(chapters, repeat=repeat, pattern=pattern,
                          offset=offset)
    first = next(iter(_by_file(chapters).values()), [])
    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "total": len(chapters),
        "findings": [f.as_dict() for f in findings],
        "inside": [f.as_dict() for f in inside],
        # Правила могли не найти ничего: тогда «ничего не найдено» — не
        # ответ, а вот первые строки сразу подсказывают, что здесь лишнее.
        "peek": text.peek(lines_of(first), text.HEAD_MANUAL_LINES),
        "repeat": repeat or text.INSIDE_REPEAT,
        "unreadable": [failure.as_text() for failure in report.failures],
    }


def _scan_inside(chapters, repeat: int = 0, pattern: str = "",
                 offset: int = 0) -> list:
    """Находки внутри файлов, сведённые в один список.

    Файлов может быть и тысяча: тогда каждое отдельное правило находит
    мало, но вместе по всем файлам находка одна и та же. Складываем её,
    иначе список будет на тысячу одинаковых строк.
    """
    limit = repeat or text.INSIDE_REPEAT
    merged: dict[tuple, text.HeaderFinding] = {}

    for chapters_of_file in _by_file(chapters).values():
        lines = lines_of(chapters_of_file)
        found = text.find_headers_inside(
            lines,
            title=chapters_of_file[0].title if chapters_of_file else "",
            repeat=limit,
            chapters=_chapter_guess(lines),
            pattern=pattern,
            offset=offset,
        )
        source = str(chapters_of_file[0].source or "") if chapters_of_file else ""
        for finding in found:
            # Файл нужен, чтобы находку можно было открыть и посмотреть,
            # о чём речь, до удаления (4.3 ТЗ).
            if source and source not in finding.files:
                finding.files.append(source)
            key = (finding.kind, text.normalize_loose(finding.text))
            known = merged.get(key)
            if known is None:
                merged[key] = finding
            else:
                known.count += finding.count
                known.total += finding.total
                known.at.extend(finding.at)
                for path in finding.files:
                    if path not in known.files:
                        known.files.append(path)
                # Пример берём у первого файла, где находка встретилась:
                # он уже есть, и заменять его нечем и незачем.

    order = [text.HEAD_REPEAT, text.HEAD_DOUBLE, text.HEAD_NEIGHBOUR,
             text.HEAD_MANUAL, text.HEAD_POSITION]
    return sorted(merged.values(),
                  key=lambda f: (order.index(f.kind) if f.kind in order else 9,
                                 -f.count, f.text))


def _chapter_guess(lines) -> int:
    """Сколько в файле глав — по числу строк, похожих на заголовок.

    Нужно для порога «чаще, чем в трети глав»: на книге в сорок глав
    двадцати повторов не наберётся, а шапка всё равно шапка.
    """
    return sum(1 for line in lines if text.looks_like_heading(line))


def clean_chapter(chapter: Chapter, texts, rules=None) -> Chapter:
    """Глава без шапки. Исходная не меняется.

    `texts` — находки по папке, `rules` — правила внутри файла. Первые
    чистят зону шапки в начале главы, вторые проходят по всему тексту:
    при книге одним файлом «начало главы» — это одно место на тысячу.
    """
    paragraphs = text.strip_headers(chapter.paragraphs, chapter.title, texts)

    if rules:
        lines = ([chapter.title] if chapter.title else []) + paragraphs
        lines = text.strip_headers_inside(lines, rules)
        # Название снимаем обратно, только если оно уцелело: правила
        # заголовок главы не трогают, но проверить дешевле, чем потерять.
        if chapter.title and lines and lines[0] == chapter.title:
            lines = lines[1:]
        paragraphs = lines

    return Chapter(
        number=chapter.number,
        part=chapter.part,
        title=chapter.title,
        paragraphs=paragraphs,
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
    rules=None,
) -> OpReport:
    """Пишет очищенные главы в новую папку. Оригиналы не трогает.

    `texts` — отмеченные находки по папке. Пустая строка среди них
    означает «убрать дубль названия главы»: сама строка у каждого файла
    своя. `rules` — отмеченные правила внутри файла.
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
        cleaned = clean_chapter(chapter, texts, rules)

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
