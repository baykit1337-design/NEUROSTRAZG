"""Запись .rtf — простой, но настоящий RTF, который открывают Word и Pages."""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from ..text import prepare
from .base import WriteError, Writer


def escape(text: str) -> str:
    r"""Экранирует служебные символы и кодирует не-ASCII как \uN."""
    out = []
    for char in text:
        if char in "\\{}":
            out.append("\\" + char)
        elif ord(char) < 128:
            out.append(char)
        else:
            # RTF хочет знаковое 16-битное значение.
            code = ord(char)
            if code > 32767:
                code -= 65536
            out.append(f"\\u{code}?")
    return "".join(out)


class RtfWriter(Writer):
    suffix = ".rtf"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        prep = options.get("prep")
        heading = options.get("headings", True)
        separator = options.get("separator", "")

        lines = [r"{\rtf1\ansi\deff0",
                 r"{\fonttbl{\f0 Times New Roman;}}", r"\fs24"]
        for index, chapter in enumerate(chapters):
            if index and separator:
                lines.append(r"\par\qc " + escape(separator) + r"\par\ql")
            elif index:
                lines.append(r"\par")
            if heading and chapter.title:
                lines.append(r"\par\b " + escape(chapter.title) + r"\b0\par")
            for block in prepare(chapter.paragraphs, chapter.title, prep):
                if block.text:
                    lines.append(r"\par " + escape(block.text))
        lines.append("}")

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text("\n".join(lines), encoding="ascii", errors="replace")
        except OSError as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
