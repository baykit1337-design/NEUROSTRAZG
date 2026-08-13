"""Чтение .rtf через striprtf."""

from __future__ import annotations

from pathlib import Path

from .base import ReadError, Reader, split_paragraphs


class RtfReader(Reader):
    suffixes = (".rtf",)

    def paragraphs(self, path: Path) -> list[str]:
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError as exc:
            raise ReadError("Для .rtf нужен striprtf: pip install striprtf") from exc
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            text = rtf_to_text(raw, errors="ignore")
        except Exception as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc
        # В rtf абзацы разделены одиночным переводом строки.
        lines = [line.strip() for line in text.splitlines()]
        paragraphs = [line for line in lines if line]
        return paragraphs or split_paragraphs(text)
