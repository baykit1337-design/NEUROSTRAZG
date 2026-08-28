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
    return look(targets, pattern, parts)


def pieces_for(index: int, chapter, pieces=None, splits=None, parts: int = 1) -> int:
    """На сколько частей резать эту главу.

    Правила идут от частного к общему: указанное для самой главы важнее
    указанного для файла, а то — общего числа для всех сразу. Раньше
    общее число было единственным, и «разбить книгу на главы» с забытой
    двойкой в поле молча давало вдвое больше файлов, чем глав.
    """
    if pieces:
        want = pieces.get(str(index), pieces.get(index))
        if want:
            return max(1, int(want))
    if splits:
        want = splits.get(chapter.source)
        if want:
            return max(1, int(want))
    return max(1, int(parts or 1))


def stem_of(index: int, width: int, chapter, fmt=None, seq: bool = True) -> str:
    """Имя файла для одной главы.

    Без своего формата имя остаётся прежним: заголовок как есть плюс
    номер части в скобках. С форматом — собирается тем же `naming.build`,
    что и во вкладке «Переименовать», чтобы у одной и той же книги,
    разбитой здесь и переименованной там, имена не расходились.
    """
    if fmt is None:
        name = naming.safe_filename(chapter.title)
        if chapter.part:
            name = f"{name} ({chapter.part})"
    else:
        parsed = naming.parse(chapter.title)
        number = chapter.number if chapter.number is not None else parsed.number
        name = naming.build(number, chapter.part or parsed.part, parsed.title, fmt)
    return f"{index:0{width}d} - {name}" if seq else name


def look(targets, pattern: str | None = None, parts: int = 1, pieces=None,
         splits=None, fmt=None, seq: bool = True,
         progress: Progress | None = None) -> dict:
    """Что получится на выходе — до записи на диск.

    Отдаёт и найденные главы (для таблицы), и готовые имена файлов (для
    предпросмотра). Считает их тот же код, что и пишет, — иначе
    предпросмотр однажды показал бы одно, а на диск легло бы другое.
    """
    report = OpReport()
    files, chapters = gather(targets, pattern, parts, report, progress)
    prepared, counts = arrange(chapters, parts, pieces, splits)
    width = naming.name_width(len(prepared))

    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "total": len(prepared),
        "found": len(chapters),
        "chapters": [
            {
                "index": index,
                "number": chapter.number,
                "title": chapter.title,
                "size": chapter.size,
                "paragraphs": len(chapter.paragraphs),
                "parts": counts[index - 1],
                "source": Path(chapter.source).name if chapter.source else "",
            }
            for index, chapter in enumerate(chapters, 1)
        ],
        "names": [stem_of(index, width, chapter, fmt, seq)
                  for index, chapter in enumerate(prepared, 1)],
        "titles": [chapter.title for chapter in chapters[:PREVIEW_TITLES]],
        "unreadable": [failure.as_text() for failure in report.failures],
    }


def names(rows, parts: int = 1, pieces=None, fmt=None, seq: bool = True
          ) -> list[str]:
    """Имена файлов по уже прочитанным главам — без повторного чтения.

    Предпросмотр перестраивается на каждую галочку, а книга в полторы
    тысячи глав читается с диска секунды. Текст главы для имени не нужен:
    хватает номера, названия и того, на сколько частей её режут. Собирает
    имена всё равно `stem_of` — тот же, что и при записи.
    """
    made: list[Chapter] = []
    for index, row in enumerate(rows, 1):
        count = pieces_for(index, Chapter(), pieces, None, parts)
        title = str(row.get("title") or "")
        number = row.get("number")
        if count < 2:
            made.append(Chapter(number=number, title=title))
            continue
        made.extend(Chapter(number=number, part=part, title=title)
                    for part in range(1, count + 1))

    width = naming.name_width(len(made))
    return [stem_of(index, width, chapter, fmt, seq)
            for index, chapter in enumerate(made, 1)]


def arrange(chapters, parts: int = 1, pieces=None, splits=None
            ) -> tuple[list[Chapter], list[int]]:
    """Режет главы на части и говорит, сколько частей вышло у каждой."""
    prepared: list[Chapter] = []
    counts: list[int] = []
    for index, chapter in enumerate(chapters, 1):
        count = pieces_for(index, chapter, pieces, splits, parts)
        counts.append(count)
        prepared.extend(split_chapter(chapter, count))
    return prepared, counts


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
    pieces: dict | None = None,
    fmt=None,
    seq: bool = True,
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
    report = OpReport(output=str(output_dir))

    _, chapters = gather(targets, pattern, parts, report, progress)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    # Деление глав на части — до записи, чтобы счётчик был честным. Режет
    # и считает имена тот же код, что и предпросмотр: разойдись они, и
    # человек увидел бы одно, а на диск легло бы другое.
    prepared, _ = arrange(chapters, parts, pieces, splits)

    output_dir.mkdir(parents=True, exist_ok=True)
    report.total = len(prepared)
    width = naming.name_width(len(prepared))
    used: set[str] = set()

    for index, chapter in enumerate(prepared, 1):
        progress.check()
        stem = stem_of(index, width, chapter, fmt, seq)
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
