"""Общий интерфейс писателя.

Писатель принимает главы и пишет файл. Текст к этому моменту уже прошёл
`core.text.prepare` — писатель только раскладывает его по формату.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from ..text import KIND_SCENE, PrepOptions, prepare


class WriteError(Exception):
    """Файл не удалось записать."""


class Writer:
    """Базовый писатель."""

    suffix: str = ""
    #: Умеет ли формат держать много глав в одном файле.
    multi_chapter: bool = True

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        raise NotImplementedError

    def blocks_for(self, chapter: Chapter, prep: PrepOptions | None = None):
        """Готовые блоки главы — общая обработка на всех писателей."""
        return prepare(chapter.paragraphs, chapter.title, prep or PrepOptions())


def flat_text(chapter: Chapter, prep: PrepOptions | None = None,
              heading: bool = True) -> str:
    """Глава как плоский текст — для форматов без разметки."""
    blocks = prepare(chapter.paragraphs, chapter.title, prep or PrepOptions())
    body = "\n\n".join(block.text for block in blocks if block.text or block.kind == KIND_SCENE)
    if heading and chapter.title:
        return f"{chapter.title}\n\n{body}"
    return body
