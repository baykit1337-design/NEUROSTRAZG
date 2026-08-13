"""Запись .txt."""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from .base import WriteError, Writer, flat_text

#: UTF-8 по умолчанию, Windows-1251 для старых программ.
ENCODINGS = ("utf-8", "windows-1251")


class TxtWriter(Writer):
    suffix = ".txt"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        prep = options.get("prep")
        heading = options.get("headings", True)
        separator = options.get("separator", "")
        encoding = options.get("encoding", "utf-8")
        if encoding not in ENCODINGS:
            raise WriteError(f"Неизвестная кодировка: {encoding}")

        pieces = [flat_text(chapter, prep, heading) for chapter in chapters]
        joiner = f"\n\n{separator}\n\n" if separator else "\n\n\n"
        text = joiner.join(piece for piece in pieces if piece).strip() + "\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Windows-1251 не покрывает типографику целиком, поэтому
            # непереводимые знаки заменяем, а не роняем запись.
            path.write_text(text, encoding=encoding, errors="replace")
        except OSError as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
