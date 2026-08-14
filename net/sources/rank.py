"""Разбор рейтинга Фанкью (5.3 ТЗ NEUROSTRAZH).

Задача — находить, что сейчас набирает обороты, не листая сайт на
китайском и не копируя идентификаторы руками.

Сам сайт отдаёт только суточный срез: готовых рейтингов «за неделю» и «за
месяц» у него нет. Поэтому срезы складываются в свою историю, а движение
считается уже по ней — см. `ops/rank.py`. Это и есть главная польза: видно
не просто популярное, а то, что растёт, то есть кандидатов на перевод,
пока их не разобрали.

Разбор идёт по тому же правилу, что и в источнике: не нашли — говорим
«источник изменился», а не отдаём пустую таблицу, которую примут за
«сегодня рейтинг пуст».
"""

from __future__ import annotations

import json
import logging
import re

from .base import SourceBroken
from .fanqie import SITE, _dig, _json

log = logging.getLogger(__name__)

#: Разделы рейтинга. Ключ — то, что уходит в адрес, значение — подпись.
BOARDS = {
    "all": "Общий",
    "male": "Мужская аудитория (男频)",
    "female": "Женская аудитория (女频)",
}

#: Адреса разделов. Отдельно от подписей: адрес может смениться, а раздел
#: остаться тем же.
BOARD_PATHS = {
    "all": "/rank/all",
    "male": "/rank/male",
    "female": "/rank/female",
}

#: Сколько строк держать в срезе. Дальше пятидесяти рейтинг уже не смотрят.
TOP = 50


class RankRow:
    """Одна строка рейтинга."""

    __slots__ = ("place", "book_id", "name", "author", "readers", "category")

    def __init__(self, place=0, book_id="", name="", author="", readers=0,
                 category=""):
        self.place = place
        self.book_id = str(book_id)
        self.name = name
        self.author = author
        self.readers = readers
        self.category = category

    def as_dict(self) -> dict:
        return {"place": self.place, "book_id": self.book_id, "name": self.name,
                "author": self.author, "readers": self.readers,
                "category": self.category,
                "link": f"{SITE}/page/{self.book_id}"}

    @classmethod
    def from_dict(cls, data: dict) -> RankRow:
        return cls(
            place=int((data or {}).get("place") or 0),
            book_id=str((data or {}).get("book_id") or ""),
            name=str((data or {}).get("name") or ""),
            author=str((data or {}).get("author") or ""),
            readers=_readers((data or {}).get("readers")),
            category=str((data or {}).get("category") or ""),
        )

    def __eq__(self, other):
        return isinstance(other, RankRow) and self.as_dict() == other.as_dict()

    def __repr__(self):
        return f"RankRow({self.place}, {self.name!r}, {self.readers})"


#: «12.3万» — китайская запись «сто двадцать три тысячи». Без разбора этих
#: суффиксов число читателей превращается в 12 вместо 123000.
SUFFIXES = {"万": 10_000, "亿": 100_000_000, "k": 1_000, "K": 1_000,
            "w": 10_000, "W": 10_000}


def _readers(value) -> int:
    """Число читающих из чего угодно, что отдаёт сайт."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0

    found = re.match(r"([\d.,]+)\s*([万亿kKwW]?)", text)
    if not found:
        return 0
    try:
        number = float(found.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(number * SUFFIXES.get(found.group(2), 1))


def parse(html: str, limit: int = TOP) -> list[RankRow]:
    """Строки рейтинга со страницы."""
    rows = _from_json(html) or _from_markup(html)
    if not rows:
        raise SourceBroken(
            "Источник изменился: рейтинг на странице не разбирается. "
            "Пустую таблицу не показываем — её приняли бы за пустой рейтинг.")

    for place, row in enumerate(rows, 1):
        if not row.place:
            row.place = place
    return rows[:limit]


def _from_json(html: str) -> list[RankRow]:
    """Основной путь: данные страницы отдельным блоком JSON."""
    block = re.search(
        r'(?s)<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
    if not block:
        return []

    data = _json(block.group(1), "рейтинг")
    found = (_dig(data, "rankList") or _dig(data, "bookList")
             or _dig(data, "booksList") or _dig(data, "items"))
    if not isinstance(found, list):
        return []

    rows = []
    for item in found:
        if not isinstance(item, dict):
            continue
        book_id = (item.get("bookId") or item.get("book_id") or item.get("id"))
        name = item.get("bookName") or item.get("book_name") or item.get("title")
        if not book_id or not name:
            continue
        rows.append(RankRow(
            place=int(item.get("rank") or item.get("place") or 0),
            book_id=str(book_id),
            name=str(name).strip(),
            author=str(item.get("author") or item.get("authorName") or "").strip(),
            readers=_readers(item.get("readCount") or item.get("read_count")
                             or item.get("readerCount") or item.get("score")),
            category=str(item.get("category") or item.get("categoryName")
                         or item.get("tags") or "").strip(),
        ))
    return rows


#: Запасной разбор вёрстки: ссылка на книгу плюс всё до следующей ссылки.
CARD = re.compile(
    r'(?is)<a[^>]+href="[^"]*?/page/(\d{6,25})"[^>]*>(.*?)(?=<a[^>]+href="[^"]*?/page/|\Z)')


def _from_markup(html: str) -> list[RankRow]:
    """Запасной путь. Хуже, но лучше пустой таблицы."""
    rows = []
    for book_id, block in CARD.findall(html):
        text = re.sub(r"(?s)<[^>]+>", "\n", block)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if not lines:
            continue
        readers = next((_readers(line) for line in lines
                        if re.search(r"\d", line) and "万" in line), 0)
        rows.append(RankRow(
            book_id=book_id,
            name=lines[0],
            author=lines[1] if len(lines) > 1 else "",
            readers=readers,
        ))
    return rows


def fetch(client, board: str = "all", limit: int = TOP) -> list[RankRow]:
    """Срез рейтинга прямо сейчас."""
    path = BOARD_PATHS.get(board)
    if path is None:
        raise ValueError(f"Неизвестный раздел рейтинга: {board}")
    return parse(client.get_text(f"{SITE}{path}"), limit=limit)
