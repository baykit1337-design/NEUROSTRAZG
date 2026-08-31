"""Общий интерфейс читателя.

Читатель получает путь и отдаёт список глав. Больше он ничего не знает: ни
про операции, ни про интерфейс.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Chapter
from ..naming import clean_title, heading_number, parse


class ReadError(Exception):
    """Файл не удалось прочитать."""


class Reader:
    """Базовый читатель. Наследник объявляет расширения и `read_text`."""

    #: Какие расширения обслуживает.
    suffixes: tuple[str, ...] = ()
    #: Даёт ли формат несколько глав из одного файла.
    multi_chapter: bool = False

    #: Первый абзац длиннее этого заголовком не считаем.
    heading_limit = 120

    def title_of(self, path: Path) -> str:
        """Название главы, записанное в самом файле. Пусто — такого нет.

        У плоских форматов его и не бывает: там заголовок — первый абзац.
        А у разметки бывает, и тогда имя файла — плохая замена.
        """
        return ""

    def read(self, path: Path) -> list[Chapter]:
        """Главы из файла. По умолчанию — одна глава на файл."""
        found = self.paragraphs(path)
        title, paragraphs = self.take_heading(found, path)
        # Название из разметки сильнее имени файла, но слабее заголовка,
        # стоящего в самом тексте: тот человек видит глазами. Заголовок
        # из текста узнаётся по тому, что его оттуда забрали, — сравнивать
        # с именем файла нельзя, они часто совпадают.
        # Тем же сравнением узнаётся и другое: стоял ли заголовок в
        # тексте вообще. Не стоял — значит, записывать его обратно нельзя.
        from_text = len(paragraphs) != len(found)
        if not from_text:
            title = self.title_of(path) or title
        name = parse(title)
        if name.number is None:
            name = parse(path.stem)
        return [
            Chapter(
                number=name.number,
                part=name.part,
                title=title,
                paragraphs=paragraphs,
                source=str(path),
                heading_from_text=from_text,
            )
        ]

    def take_heading(self, paragraphs: list[str], path: Path) -> tuple[str, list[str]]:
        """Отделяет заголовок главы от текста.

        У плоских форматов (txt, rtf, odt) заголовок — обычный первый абзац,
        структурно от текста не отличимый. Если он выглядит как название
        главы, забираем его в title: иначе при следующей записи название
        задвоится.
        """
        from ..text import normalize_title

        fallback = clean_title(path.stem)
        if not paragraphs:
            return fallback, paragraphs

        first = paragraphs[0].strip()
        looks_like_heading = (
            len(first) <= self.heading_limit
            and (heading_number(first) is not None
                 or normalize_title(first) == normalize_title(fallback))
        )
        if looks_like_heading:
            return first, paragraphs[1:]
        return fallback, paragraphs

    def paragraphs(self, path: Path) -> list[str]:
        """Абзацы плоского файла. Переопределяется наследником."""
        raise NotImplementedError


def split_paragraphs(text: str) -> list[str]:
    """Режет текст на абзацы: пустая строка — граница."""
    if not text:
        return []
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    import re

    blocks = re.split(r"\n\s*\n", normalised)
    return [block.strip() for block in blocks if block.strip()]
