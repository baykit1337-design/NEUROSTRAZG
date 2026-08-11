"""Сборка .docx: общие настройки документа и вставка глав.

Используется вкладкой «Разбить книгу» (глава = отдельный файл) и будет
переиспользована конвертером в Word (все главы в одном документе).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Абзац из одних звёздочек — разделитель сцен, его сохраняем как есть.
SCENE_BREAK = re.compile(r"^[*\s]*\*[*\s]*$")


class DocxUnavailable(RuntimeError):
    """Не установлен python-docx."""


@dataclass
class Style:
    """Оформление документа. Значения по умолчанию — из ТЗ."""

    font: str = "Times New Roman"
    size: int = 12
    line_spacing: float = 1.5
    first_line_indent_cm: float = 1.25
    page_break_between_chapters: bool = True
    table_of_contents: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> Style:
        data = data or {}
        return cls(
            font=str(data.get("font") or cls.font),
            size=_number(data.get("size"), cls.size),
            line_spacing=_number(data.get("line_spacing"), cls.line_spacing),
            first_line_indent_cm=_number(
                data.get("first_line_indent_cm"), cls.first_line_indent_cm
            ),
            page_break_between_chapters=bool(
                data.get("page_break_between_chapters", cls.page_break_between_chapters)
            ),
            table_of_contents=bool(data.get("table_of_contents", cls.table_of_contents)),
        )


def _number(value, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number <= 0:
        return fallback
    return int(number) if isinstance(fallback, int) else number


def _docx():
    try:
        import docx
    except ImportError as exc:  # pragma: no cover — зависит от окружения
        raise DocxUnavailable(
            "Для вывода в .docx нужен python-docx: pip install python-docx"
        ) from exc
    return docx


def new_document(style: Style | None = None):
    """Пустой документ с применённым оформлением."""
    docx = _docx()
    from docx.shared import Cm, Pt

    style = style or Style()
    document = docx.Document()

    normal = document.styles["Normal"]
    normal.font.name = style.font
    normal.font.size = Pt(style.size)
    paragraph_format = normal.paragraph_format
    paragraph_format.line_spacing = style.line_spacing
    paragraph_format.first_line_indent = Cm(style.first_line_indent_cm)

    # Кириллица берёт шрифт из отдельного атрибута темы, без него Word
    # подставляет свой.
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(_qn(attribute), style.font)

    return document


def _qn(tag: str) -> str:
    from docx.oxml.ns import qn

    return qn(tag)


def add_paragraphs(document, text: str, style: Style | None = None) -> int:
    """Добавляет текст главы абзацами. Возвращает число абзацев."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    added = 0
    for block in split_paragraphs(text):
        paragraph = document.add_paragraph()
        if SCENE_BREAK.match(block):
            # Разделитель сцен: по центру и без красной строки.
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.first_line_indent = 0
        paragraph.add_run(block)
        added += 1
    return added


def split_paragraphs(text: str) -> list[str]:
    """Режет текст на абзацы: пустая строка — граница."""
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    return [b.strip() for b in blocks if b.strip()]


def add_chapter(document, title: str, text: str, style: Style | None = None) -> None:
    """Заголовок главы стилем Heading 1, дальше абзацы."""
    if title:
        document.add_heading(title, level=1)
    add_paragraphs(document, text, style)


def write_chapter(path: Path, title: str, text: str, style: Style | None = None) -> None:
    """Одна глава — один .docx."""
    style = style or Style()
    document = new_document(style)
    add_chapter(document, title, text, style)
    document.save(str(path))
