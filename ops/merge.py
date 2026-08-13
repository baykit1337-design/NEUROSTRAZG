"""«Объединить»: множество файлов → один файл.

Форматы на входе могут быть смешанными: читатель подбирается на каждый
файл отдельно.
"""

from __future__ import annotations

from pathlib import Path

from core import naming
from core.models import OpReport
from core.text import PrepOptions

from .base import Progress, collect_files, read_all

ORDER_NUMBER = "number"
ORDER_NAME = "name"
ORDERS = (ORDER_NUMBER, ORDER_NAME)

#: Варианты разделителя между главами.
SEPARATORS = {"blank": "", "stars": "* * *", "dashes": "---", "double": "═══"}
DEFAULT_SEPARATOR = "blank"


def separator_text(key: str, custom: str = "") -> str:
    """Текст разделителя по ключу. Свой вариант имеет приоритет."""
    if custom.strip():
        return custom.strip()
    return SEPARATORS.get(key, SEPARATORS[DEFAULT_SEPARATOR])


def scan(targets, order: str = ORDER_NUMBER) -> dict:
    files = collect_files(targets)
    report = OpReport()
    chapters = _ordered(read_all(files, report), order)
    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        "total": len(chapters),
        "titles": [chapter.title for chapter in chapters[:5]],
        "unreadable": [failure.as_text() for failure in report.failures],
    }


def _ordered(chapters, order: str):
    """Порядок глав: по номеру (по паре чисел) либо по имени файла."""
    if order == ORDER_NAME:
        return sorted(chapters, key=lambda c: Path(c.source).name.lower())
    return sorted(chapters, key=naming.sort_key)


def run(
    targets,
    output: Path,
    order: str = ORDER_NUMBER,
    headings: bool = True,
    separator: str = DEFAULT_SEPARATOR,
    custom_separator: str = "",
    encoding: str = "utf-8",
    prep: PrepOptions | None = None,
    style=None,
    progress: Progress | None = None,
) -> OpReport:
    """Склеивает главы в один файл выбранного формата."""
    from core import formats

    if order not in ORDERS:
        raise ValueError(f"Неизвестный порядок: {order}")

    progress = progress or Progress()
    report = OpReport(output=str(output))

    files = collect_files(targets)
    chapters = _ordered(read_all(files, report, progress), order)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    report.total = len(chapters)
    progress.check()
    progress.step(len(files), len(files), f"Собираем {len(chapters)} глав…")

    try:
        formats.write(
            output, chapters,
            prep=prep, style=style, headings=headings, encoding=encoding,
            separator=separator_text(separator, custom_separator),
            title=output.stem,
        )
        report.written = len(chapters)
    except Exception as exc:
        report.fail(output.name, "запись", f"{type(exc).__name__}: {exc}")
        raise

    return report
