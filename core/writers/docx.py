"""Запись .docx через python-docx."""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from .base import WriteError, Writer


class DocxWriter(Writer):
    suffix = ".docx"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        # Оформление живёт в mvl.word — там же разбор markdown и стили.
        from mvl.word import DocxUnavailable, Style, add_blocks, new_document

        style = options.get("style") or Style()
        prep = options.get("prep")
        heading = options.get("headings", True)

        try:
            document = new_document(style)
        except DocxUnavailable as exc:
            raise WriteError(str(exc)) from exc

        written = 0
        for chapter in chapters:
            if written and style.page_break_between_chapters:
                document.add_page_break()
            if heading and chapter.title:
                document.add_heading(chapter.title, level=1)
            add_blocks(document, self.blocks_for(chapter, prep), style, prep)
            written += 1

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            document.save(str(path))
        except Exception as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
