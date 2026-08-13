"""Запись .md: заголовок главы становится markdown-заголовком."""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from ..text import prepare
from .base import WriteError, Writer


class MarkdownWriter(Writer):
    suffix = ".md"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        prep = options.get("prep")
        heading = options.get("headings", True)
        separator = options.get("separator", "")

        pieces = []
        for chapter in chapters:
            blocks = prepare(chapter.paragraphs, chapter.title, prep)
            body = "\n\n".join(block.text for block in blocks if block.text)
            if heading and chapter.title:
                body = f"# {chapter.title}\n\n{body}"
            pieces.append(body)

        joiner = f"\n\n{separator}\n\n" if separator else "\n\n---\n\n"
        text = joiner.join(piece for piece in pieces if piece).strip() + "\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
