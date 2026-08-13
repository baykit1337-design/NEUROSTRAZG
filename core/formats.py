"""Выбор читателя и писателя по расширению.

Добавление формата = один файл в `readers/` и один в `writers/`, плюс
строка здесь. Операции про форматы не знают вовсе.
"""

from __future__ import annotations

from pathlib import Path

from .readers.base import ReadError, Reader
from .readers.docx import DocxReader
from .readers.epub import EpubReader
from .readers.fb2 import Fb2Reader
from .readers.html import HtmlReader
from .readers.md import MarkdownReader
from .readers.odt import OdtReader
from .readers.rtf import RtfReader
from .readers.txt import TxtReader
from .writers.base import WriteError, Writer
from .writers.docx import DocxWriter
from .writers.epub import EpubWriter
from .writers.fb2 import Fb2Writer
from .writers.md import MarkdownWriter
from .writers.odt import OdtWriter
from .writers.rtf import RtfWriter
from .writers.txt import TxtWriter

READERS: tuple[Reader, ...] = (
    TxtReader(), MarkdownReader(), DocxReader(), EpubReader(),
    Fb2Reader(), RtfReader(), OdtReader(), HtmlReader(),
)

WRITERS: tuple[Writer, ...] = (
    TxtWriter(), MarkdownWriter(), DocxWriter(), EpubWriter(),
    Fb2Writer(), RtfWriter(), OdtWriter(),
)

_BY_SUFFIX = {suffix: reader for reader in READERS for suffix in reader.suffixes}
_WRITER_BY_SUFFIX = {writer.suffix: writer for writer in WRITERS}

#: Что можно прочитать и что можно записать — для интерфейса.
READABLE = tuple(sorted(_BY_SUFFIX))
WRITABLE = tuple(sorted(_WRITER_BY_SUFFIX))

#: Сигнатуры файлов. Расширение врёт: `.txt`, который на деле ZIP, читать
#: как текст нельзя — получится мусор.
SIGNATURES = (
    (b"PK\x03\x04", "zip"),
    (b"{\\rtf", ".rtf"),
    (b"%PDF", ".pdf"),
)


def sniff(path: Path) -> str:
    """Формат по сигнатуре файла. Пустая строка — не определился."""
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return ""

    for magic, kind in SIGNATURES:
        if not head.startswith(magic):
            continue
        if kind != "zip":
            return kind
        # ZIP — это epub, odt или docx: смотрим, что внутри.
        return _inside_zip(path)
    return ""


def _inside_zip(path: Path) -> str:
    import zipfile

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return ""

    if "META-INF/container.xml" in names:
        return ".epub"
    if "content.xml" in names:
        return ".odt"
    if any(name.startswith("word/") for name in names):
        return ".docx"
    return ""


def reader_for(path: Path) -> Reader:
    """Читатель по расширению, а при несовпадении — по сигнатуре."""
    suffix = path.suffix.lower()
    reader = _BY_SUFFIX.get(suffix)

    actual = sniff(path)
    if actual and actual != suffix:
        # Содержимое важнее расширения: иначе epub, названный .txt,
        # прочитается как сырые байты архива.
        by_signature = _BY_SUFFIX.get(actual)
        if by_signature is not None:
            return by_signature
        if reader is None:
            raise ReadError(f"{path.name}: формат {actual} не поддерживается")

    if reader is None:
        raise ReadError(
            f"{path.name}: не умею читать {suffix or 'файл без расширения'} — "
            f"нужен один из {', '.join(READABLE)}"
        )
    return reader


def writer_for(suffix: str) -> Writer:
    suffix = suffix.lower()
    if not suffix.startswith("."):
        suffix = "." + suffix
    writer = _WRITER_BY_SUFFIX.get(suffix)
    if writer is None:
        raise WriteError(
            f"Не умею писать {suffix} — нужен один из {', '.join(WRITABLE)}"
        )
    return writer


def is_readable(path: Path) -> bool:
    return path.suffix.lower() in _BY_SUFFIX


def read(path: Path):
    """Главы из файла — единственная точка чтения на весь проект."""
    return reader_for(path).read(Path(path))


def write(path: Path, chapters, **options) -> None:
    """Запись глав в файл — единственная точка записи."""
    writer_for(Path(path).suffix).write(Path(path), list(chapters), **options)
