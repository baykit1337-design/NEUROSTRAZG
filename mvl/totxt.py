"""Сборка папки с главами в один .txt — обратная операция к «Разбить».

Вход: папка с `.txt`, `.md`, `.docx` (и `.epub` — он тоже читается).
Выход: один текстовый файл.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .booksplit import Cancelled
from .rename import parse_name, sort_chapters
from .rename import Chapter as NamedChapter
from .source import SourceError, collect_sources, load_chapters
from .textprep import PrepOptions, prepare, to_text

log = logging.getLogger(__name__)

ORDER_NUMBER = "number"
ORDER_NAME = "name"
ORDERS = (ORDER_NUMBER, ORDER_NAME)

#: Кодировки на выбор: UTF-8 и Windows-1251 для старых программ.
ENCODINGS = ("utf-8", "windows-1251")

#: Варианты разделителя между главами.
SEPARATORS = {
    "blank": "",
    "stars": "* * *",
    "dashes": "---",
    "double": "═══",
}
DEFAULT_SEPARATOR = "blank"


class TxtError(Exception):
    """Собрать файл не удалось."""


@dataclass
class TxtReport:
    output: str = ""
    chapters: int = 0
    written: int = 0
    failed: int = 0
    characters: int = 0
    encoding: str = "utf-8"
    failures: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "output": self.output,
            "chapters": self.chapters,
            "written": self.written,
            "failed": self.failed,
            "characters": self.characters,
            "encoding": self.encoding,
            "failed_files": self.failures,
        }


def separator_text(key: str, custom: str = "") -> str:
    """Текст разделителя по ключу. Свой вариант имеет приоритет."""
    if custom.strip():
        return custom.strip()
    return SEPARATORS.get(key, SEPARATORS[DEFAULT_SEPARATOR])


def order_files(files: list[Path], order: str = ORDER_NUMBER) -> list[Path]:
    """Порядок глав: по номеру из имени либо просто по имени файла."""
    if order == ORDER_NAME:
        return sorted(files, key=lambda p: p.name.lower())

    named = [NamedChapter(path=path, parts_of_name=parse_name(path.stem)) for path in files]
    return [chapter.path for chapter in sort_chapters(named)]


def scan(targets, order: str = ORDER_NUMBER) -> dict:
    """Что соберётся — для показа до запуска."""
    try:
        files = order_files(collect_sources(targets), order)
    except SourceError as exc:
        raise TxtError(str(exc)) from exc
    return {
        "files": [str(path) for path in files],
        "total": len(files),
        "titles": [path.stem for path in files[:5]],
    }


def build(
    targets,
    output: Path,
    order: str = ORDER_NUMBER,
    headings: bool = True,
    separator: str = DEFAULT_SEPARATOR,
    custom_separator: str = "",
    encoding: str = "utf-8",
    prep: PrepOptions | None = None,
    on_progress=None,
    cancel: threading.Event | None = None,
) -> TxtReport:
    """Склеивает главы в один файл."""
    if encoding not in ENCODINGS:
        raise TxtError(f"Неизвестная кодировка: {encoding}")
    if order not in ORDERS:
        raise TxtError(f"Неизвестный порядок: {order}")

    prep = prep or PrepOptions()
    try:
        files = order_files(collect_sources(targets), order)
    except SourceError as exc:
        raise TxtError(str(exc)) from exc

    mark = separator_text(separator, custom_separator)
    report = TxtReport(output=str(output), chapters=len(files), encoding=encoding)
    pieces: list[str] = []

    for index, path in enumerate(files, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        try:
            for chapter in load_chapters(path):
                # Тот же разбор текста, что и на других путях вывода.
                blocks = prepare(chapter.paragraphs, chapter.title, prep)
                body = to_text(blocks)
                if headings and chapter.title:
                    body = f"{chapter.title}\n\n{body}"
                pieces.append(body)
            report.written += 1
        except Exception as exc:
            reason = f"{path.name}: {type(exc).__name__}: {exc}"
            log.warning("Не собран %s", reason)
            report.failures.append(reason)
            report.failed += 1

        if on_progress:
            on_progress(index, len(files))

    if not pieces:
        detail = report.failures[0] if report.failures else ""
        raise TxtError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    joiner = f"\n\n{mark}\n\n" if mark else "\n\n\n"
    text = joiner.join(pieces).strip() + "\n"
    report.characters = len(text)

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Windows-1251 не покрывает всю кириллицу вместе с типографикой,
        # поэтому непереводимые знаки заменяем, а не роняем сборку.
        output.write_text(text, encoding=encoding, errors="replace")
    except OSError as exc:
        raise TxtError(f"Файл не сохранён: {type(exc).__name__}: {exc}") from exc

    return report
