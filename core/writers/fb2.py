"""Запись .fb2 — главы становятся <section> с <title>."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from ..models import Chapter
from ..text import prepare
from .base import WriteError, Writer

TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info>
<book-title>{title}</book-title>
<author><nickname>{author}</nickname></author>
</title-info></description>
<body>{body}</body>
</FictionBook>"""


class Fb2Writer(Writer):
    suffix = ".fb2"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        prep = options.get("prep")
        heading = options.get("headings", True)
        title = options.get("title") or path.stem
        author = options.get("author") or ""

        sections = []
        for chapter in chapters:
            parts = ["<section>"]
            if heading and chapter.title:
                parts.append(f"<title><p>{escape(chapter.title)}</p></title>")
            for block in prepare(chapter.paragraphs, chapter.title, prep):
                parts.append(f"<p>{escape(block.text)}</p>")
            parts.append("</section>")
            sections.append("".join(parts))

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(
                TEMPLATE.format(
                    title=escape(title), author=escape(author), body="".join(sections)
                ),
                encoding="utf-8",
            )
        except OSError as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
