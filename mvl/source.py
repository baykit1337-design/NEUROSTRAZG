"""Чтение исходников — тонкая обёртка над `core/formats.py`.

Раньше каждая вкладка читала файлы по-своему, и `.epub` в двух местах
открывался как текст — а это ZIP-архив, отсюда и мусор вида `??v????A`.
Потом чтение свели в этот модуль, а теперь — в `core/`, где на каждый
формат по одному читателю.

Здесь остались только имена, под которыми к чтению обращаются «Проверка»
и «Переименовать», плюс перевод ошибок ядра в `SourceError`. Логики
разбора форматов в этом файле больше нет: добавить формат = добавить
читателя в `core/readers/`, и он появится во всех вкладках сразу.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core import formats
from core.models import Chapter
from core.naming import clean_title
from core.readers.base import ReadError

log = logging.getLogger(__name__)

#: Всё, что вкладки умеют читать. Список один на весь проект.
READABLE = formats.READABLE
#: Форматы, из которых обычно приходит сразу много глав.
MULTI = (".epub", ".fb2")

__all__ = [
    "Chapter", "SourceError", "READABLE", "MULTI", "clean_title",
    "is_readable", "is_multi_chapter", "read_paragraphs", "load_chapters",
    "collect_sources",
]


class SourceError(Exception):
    """Файл не удалось прочитать."""


def is_readable(path: Path) -> bool:
    return formats.is_readable(path)


def is_multi_chapter(path: Path) -> bool:
    """Даёт ли файл несколько глав сразу."""
    return path.suffix.lower() in MULTI


def load_chapters(path: str | Path) -> list[Chapter]:
    """Главы из файла. epub и fb2 дают много, плоские форматы — одну."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise SourceError(f"Файл не найден: {file_path}")
    try:
        return formats.read(file_path)
    except ReadError as exc:
        raise SourceError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — вкладке нужен текст ошибки
        raise SourceError(f"{file_path.name}: {type(exc).__name__}: {exc}") from exc


def read_paragraphs(path: Path) -> list[str]:
    """Абзацы файла одним списком, сколько бы глав в нём ни было."""
    return [p for chapter in load_chapters(path) for p in chapter.paragraphs]


def collect_sources(targets) -> list[Path]:
    """Разворачивает выбранное в список файлов.

    Принимает пути к файлам и к папкам вперемешку: папка раскрывается в
    свои читаемые файлы, файл берётся как есть. Расширение проверяется и
    у одиночного файла: без этого epub уходил в текстовое чтение и
    превращался в мусор.
    """
    from ops.base import collect_files

    try:
        return collect_files(targets)
    except ReadError as exc:
        raise SourceError(str(exc)) from exc
