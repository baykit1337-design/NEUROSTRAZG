"""Разбивка книги на отдельные файлы по главам.

Разбор берём из готового модуля split_book.py в корне проекта — он уже
обкатан, здесь его не переписываем. Добавляем только то, чего ему не хватает
для веб-интерфейса: превью до записи, прогресс, отмену, вывод в .docx и
аккуратные исключения вместо SystemExit.
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import split_book  # noqa: E402  — модуль лежит в корне проекта

from .textprep import PrepOptions, prepare, to_text  # noqa: E402
from .word import Style, add_blocks, new_document, split_paragraphs  # noqa: E402

log = logging.getLogger(__name__)

EPUB_SUFFIXES = (".epub",)
TXT_SUFFIXES = (".txt", ".text")
SUPPORTED_SUFFIXES = EPUB_SUFFIXES + TXT_SUFFIXES
FORMAT_TXT = "txt"
FORMAT_DOCX = "docx"
PREVIEW_TITLES = 5

DEFAULT_PATTERN = split_book.DEFAULT_PATTERN
safe_name = split_book.safe_name


class SplitError(Exception):
    """Книгу не удалось разобрать."""


class HeadingsNotFound(SplitError):
    """В .txt не нашлись заголовки глав — резать наугад не будем."""

    def __init__(self, pattern: str):
        super().__init__(
            "Заголовки глав не найдены. Посмотрите, как выглядит начало главы "
            "в файле, и задайте своё регулярное выражение."
        )
        self.pattern = pattern


class Cancelled(Exception):
    """Пользователь остановил разбивку."""


@dataclass
class Chapter:
    title: str
    text: str

    @property
    def length(self) -> int:
        return len(self.text)


@dataclass
class Preview:
    """Что нашли в книге — показывается до записи на диск."""

    source: str = ""
    kind: str = ""
    total: int = 0
    titles: list[str] = field(default_factory=list)
    pattern: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SplitReport:
    output_dir: str = ""
    written: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)
    total: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def detect_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in EPUB_SUFFIXES:
        return "epub"
    if suffix in TXT_SUFFIXES:
        return "txt"
    raise SplitError(f"Не умею работать с {suffix or 'файлом без расширения'} — нужен .epub или .txt")


def read_chapters(path: str | Path, pattern: str | None = None) -> list[Chapter]:
    """Главы книги в порядке чтения.

    split_book при неудаче кидает SystemExit — в сервере это недопустимо,
    поэтому переводим в обычные исключения.
    """
    file_path = Path(path).expanduser()
    if not file_path.exists():
        raise SplitError(f"Файл не найден: {file_path}")

    kind = detect_kind(file_path)
    pattern = pattern or DEFAULT_PATTERN

    try:
        if kind == "epub":
            raw = split_book.epub_chapters(file_path)
        else:
            raw = split_book.txt_chapters(file_path, pattern)
    except SystemExit as exc:
        message = str(exc)
        if kind == "txt" and "заголовки глав не найдены" in message.lower():
            raise HeadingsNotFound(pattern) from exc
        raise SplitError(message or "Не удалось разобрать книгу") from exc
    except SplitError:
        raise
    except Exception as exc:
        raise SplitError(f"Не удалось разобрать книгу: {type(exc).__name__}: {exc}") from exc

    chapters = [Chapter(title=title, text=text) for title, text in raw]
    if not chapters:
        raise SplitError("Глав не найдено")
    return chapters


def preview(path: str | Path, pattern: str | None = None) -> Preview:
    """Сколько глав нашлось и первые названия — до записи на диск."""
    file_path = Path(path).expanduser()
    chapters = read_chapters(file_path, pattern)
    return Preview(
        source=str(file_path),
        kind=detect_kind(file_path),
        total=len(chapters),
        titles=[c.title for c in chapters[:PREVIEW_TITLES]],
        pattern=pattern or DEFAULT_PATTERN,
    )


def chapter_filename(number: int, title: str, width: int, suffix: str) -> str:
    """`0001 - Название главы.txt`, ведущие нули по длине списка."""
    return f"{str(number).zfill(width)} - {safe_name(title)}.{suffix}"


def name_width(total: int) -> int:
    """Ведущие нули по длине списка, минимум 4 знака."""
    return max(4, len(str(total)))


def write_chapters(
    chapters: list[Chapter],
    output_dir: Path,
    fmt: str = FORMAT_TXT,
    style: Style | None = None,
    prep: PrepOptions | None = None,
    on_progress=None,
    cancel: threading.Event | None = None,
) -> SplitReport:
    """Пишет главы отдельными файлами.

    Ошибка на одной главе не прерывает остальные: файл пропускается, причина
    уходит в лог, в конце — сводка.
    """
    prep = prep or PrepOptions()
    output_dir.mkdir(parents=True, exist_ok=True)
    width = name_width(len(chapters))
    suffix = FORMAT_DOCX if fmt == FORMAT_DOCX else FORMAT_TXT

    report = SplitReport(output_dir=str(output_dir), total=len(chapters))

    for index, chapter in enumerate(chapters, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        filename = chapter_filename(index, chapter.title, width, suffix)
        try:
            target = output_dir / filename
            # Та же подготовка, что и во всех остальных путях вывода:
            # дубль названия, разделители, пустые абзацы.
            blocks = prepare(split_paragraphs(chapter.text), chapter.title, prep)
            if suffix == FORMAT_DOCX:
                document = new_document(style)
                if chapter.title:
                    document.add_heading(chapter.title, level=1)
                add_blocks(document, blocks, style, prep)
                document.save(str(target))
            else:
                body = to_text(blocks)
                target.write_text(
                    f"{chapter.title}\n\n{body}\n" if chapter.title else f"{body}\n",
                    encoding="utf-8",
                )
            report.written += 1
        except Exception as exc:
            log.warning("Глава %s (%s) не записана: %s", index, filename, exc)
            report.failed += 1
            report.failed_files.append(f"{filename}: {type(exc).__name__}: {exc}")

        if on_progress:
            on_progress(index, len(chapters))

    return report


def split_book_to_dir(
    path: str | Path,
    output_dir: Path,
    fmt: str = FORMAT_TXT,
    pattern: str | None = None,
    style: Style | None = None,
    prep: PrepOptions | None = None,
    on_progress=None,
    cancel: threading.Event | None = None,
) -> SplitReport:
    """Разбор и запись одним вызовом — для CLI и для фоновой задачи."""
    chapters = read_chapters(path, pattern)
    return write_chapters(
        chapters, output_dir, fmt=fmt, style=style, prep=prep,
        on_progress=on_progress, cancel=cancel,
    )
