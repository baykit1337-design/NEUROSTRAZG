"""Чтение .md — тот же текст, но разметка разбирается при выводе."""

from __future__ import annotations

import re
from pathlib import Path

from .base import ReadError, Reader, split_paragraphs
from .txt import read_text


class MarkdownReader(Reader):
    suffixes = (".md", ".markdown")

    def take_heading(self, paragraphs, path):
        """У markdown заголовок помечен решётками — снимаем их перед разбором."""
        if paragraphs:
            stripped = re.sub(r"^\s*#{1,6}\s+", "", paragraphs[0])
            if stripped != paragraphs[0]:
                return stripped.strip(), paragraphs[1:]
        return super().take_heading(paragraphs, path)

    def paragraphs(self, path: Path) -> list[str]:
        try:
            return split_paragraphs(read_text(path))
        except OSError as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc
