"""Разрезание сплошной книги на главы по заголовкам.

Нужно, когда файл на входе — вся книга одним куском: `.txt`, `.rtf`,
`.odt`, `.docx` без стилей заголовков. Читатель отдаёт такой файл одной
главой, и уже здесь она режется по строкам вида «Глава 12».

Формат при этом не важен: работаем с абзацами, а не с байтами файла.
"""

from __future__ import annotations

import re

from .models import Chapter
from .naming import clean_title, parse

#: Строка, с которой начинается глава. Совпадать должна вся строка целиком:
#: «Глава 12» — заголовок, а «…в главе 12 говорилось» — обычный текст.
#:
#: Решётки markdown в начале допускаются: `.md` мы сами так и пишем —
#: `# Глава 5`, — а разобрать собственный вывод обратно не могли, потому
#: что решётка не пускала строку под этот шаблон.
DEFAULT_PATTERN = (r"^\s*#{0,6}\s*"
                   r"(?:Глава|ГЛАВА|глава|Chapter|CHAPTER|Часть)\s*\d+.*$")

#: Решётки markdown в начале строки. Названием главы им не быть: они
#: разметка, а не имя, и в имя файла попадать не должны.
HASHES = re.compile(r"^\s*#{1,6}\s*")

#: Заголовок — короткая строка. Абзац на три экрана заголовком не бывает,
#: даже если начинается со слова «Глава».
MAX_HEADING = 120


class HeadingsNotFound(Exception):
    """Заголовков не нашлось. Наугад не режем — просим свой шаблон."""

    def __init__(self, pattern: str):
        self.pattern = pattern
        super().__init__(
            "Заголовки глав не найдены.\n"
            f"Использовался шаблон: {pattern}\n"
            "Посмотрите, как выглядит начало главы в файле, и опишите его "
            "своим регулярным выражением."
        )


def compile_pattern(pattern: str | None):
    try:
        return re.compile(pattern or DEFAULT_PATTERN, re.MULTILINE)
    except re.error as exc:
        raise HeadingsNotFound(pattern or DEFAULT_PATTERN) from exc


def find(paragraphs: list[str], pattern: str | None = None) -> list[int]:
    """Номера абзацев, которые выглядят заголовками глав."""
    rx = compile_pattern(pattern)
    marks = []
    for index, text in enumerate(paragraphs):
        stripped = text.strip()
        if stripped and len(stripped) <= MAX_HEADING and rx.match(stripped):
            marks.append(index)
    return marks


def cut(chapter: Chapter, pattern: str | None = None) -> list[Chapter]:
    """Режет одну сплошную главу на несколько по заголовкам.

    Заголовок в тело не попадает: он становится названием главы, иначе
    после записи название окажется продублировано первым абзацем.
    """
    marks = find(chapter.paragraphs, pattern)
    if not marks:
        raise HeadingsNotFound(pattern or DEFAULT_PATTERN)

    chapters: list[Chapter] = []

    # Текст до первого заголовка терять нельзя. У плоских форматов читатель
    # уже забрал первую строку в название главы, так что это ровно первая
    # глава книги — её заголовок лежит в `chapter.title`.
    head = [p for p in chapter.paragraphs[:marks[0]] if p.strip()]
    if head:
        chapters.append(_make(chapter.title or "Начало", head, chapter.source))

    for order, start in enumerate(marks):
        end = marks[order + 1] if order + 1 < len(marks) else len(chapter.paragraphs)
        title = HASHES.sub("", chapter.paragraphs[start].strip()).strip()
        body = [p for p in chapter.paragraphs[start + 1:end] if p.strip()]
        chapters.append(_make(title, body, chapter.source))
    return chapters


def _make(title: str, paragraphs: list[str], source: str) -> Chapter:
    """Глава с номером, вынутым из заголовка."""
    parts = parse(clean_title(title))
    return Chapter(number=parts.number, part=parts.part, title=title,
                   paragraphs=paragraphs, source=source)


def looks_monolithic(chapters: list[Chapter]) -> bool:
    """Похоже ли прочитанное на книгу одним куском.

    Одна глава на входе — либо это действительно одна глава, либо целая
    книга, которую читатель не смог разделить. Различает их наличие
    заголовков внутри.
    """
    return len(chapters) == 1 and bool(find(chapters[0].paragraphs))
