"""Чтение .docx через python-docx."""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from ..naming import clean_title, parse
from .base import ReadError, Reader


class DocxReader(Reader):
    suffixes = (".docx",)

    def read(self, path: Path) -> list[Chapter]:
        """Глава из документа.

        Заголовок берём из стиля Heading, а не из текста: иначе он остаётся
        первым абзацем и при следующей записи название задваивается.
        """
        heading, paragraphs = self._split(path)
        stem_title = clean_title(path.stem)
        title = heading or stem_title
        name = parse(title if heading else path.stem)
        return [
            Chapter(
                number=name.number,
                part=name.part,
                title=title,
                paragraphs=paragraphs,
                source=str(path),
                # У документа без стилей заголовка название берётся из
                # имени файла: в тексте его не было.
                heading_from_text=bool(heading),
            )
        ]

    def _split(self, path: Path) -> tuple[str, list[str]]:
        try:
            from docx import Document
        except ImportError as exc:
            raise ReadError("Для .docx нужен python-docx") from exc
        try:
            document = Document(str(path))
        except Exception as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc

        heading = ""
        paragraphs: list[str] = []
        for paragraph in document.paragraphs:
            body = paragraph.text.strip()
            if not body:
                continue
            style = (paragraph.style.name or "") if paragraph.style else ""
            # Первый заголовок — название главы, остальные остаются текстом.
            if not heading and not paragraphs and style.startswith("Heading"):
                heading = body
                continue
            paragraphs.append(body)
        return heading, paragraphs

    def paragraphs(self, path: Path) -> list[str]:
        return self._split(path)[1]
