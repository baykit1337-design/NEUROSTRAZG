"""Общая доска: одна книга сразу на нескольких сайтах.

Каждый рейтинг знает только свой сайт. Книга, которую читают и на
Цидяне, и на Фанкью, стоит в двух списках порознь, и увидеть, что её
читают везде, а не в одном месте, неоткуда — а это и есть главный
признак того, что книгу стоит брать.

Здесь последние срезы всех сайтов сводятся в один список: книга,
узнанная больше чем в одном рейтинге, становится одной строкой с местом
на каждом сайте.

Сводятся они по названию: общего кода у сайтов нет и быть не может.
Значит, склеиваются прежде всего соседи по языку — китайские рейтинги
между собой, английские между собой, — и это честный предел способа, а
не недоделка. Одинаковое название при разных авторах — не одна книга, и
такие строки нарочно остаются порознь.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.registry import normalize

from .rank import RANK_DIR, Snapshot, read

#: Больше этого числа строк в интерфейс не отдаём.
MAX_ROWS = 400

#: Как звать срез, снятый до того, как у рейтингов появились доски. В
#: файлах он записан словом «all», и показывать это слово человеку —
#: значит показывать ему наше внутреннее имя.
WHOLE = "весь срез"


@dataclass
class Seat:
    """Место книги на одном сайте."""

    site: str = ""
    site_name: str = ""
    place: int = 0
    board: str = ""
    day: str = ""
    link: str = ""
    book_id: str = ""
    readers: int = 0
    score: float | None = None
    metric: str = ""

    def as_dict(self) -> dict:
        return {"site": self.site, "site_name": self.site_name,
                "place": self.place, "board": self.board, "day": self.day,
                "link": self.link, "book_id": self.book_id,
                "readers": self.readers, "score": self.score,
                "metric": self.metric}


@dataclass
class Row:
    """Одна книга и все её места."""

    name: str = ""
    author: str = ""
    cover: str = ""
    seats: list[Seat] = field(default_factory=list)

    @property
    def sites(self) -> int:
        return len({seat.site for seat in self.seats})

    @property
    def best(self) -> int:
        return min((seat.place for seat in self.seats if seat.place), default=0)

    def as_dict(self) -> dict:
        return {"name": self.name, "author": self.author, "cover": self.cover,
                "sites": self.sites, "best": self.best,
                "seats": [s.as_dict() for s in self.seats]}


@dataclass
class Board:
    """Общая доска целиком."""

    rows: list[Row] = field(default_factory=list)
    #: Какие срезы в неё вошли и какой давности каждый.
    taken: list[dict] = field(default_factory=list)

    @property
    def shared(self) -> int:
        """Сколько книг нашлось больше чем на одном сайте."""
        return sum(1 for row in self.rows if row.sites > 1)

    def as_dict(self) -> dict:
        return {
            "rows": [r.as_dict() for r in self.rows[:MAX_ROWS]],
            "total": len(self.rows),
            "shared": self.shared,
            "taken": self.taken,
            "more": max(0, len(self.rows) - MAX_ROWS),
        }


def latest() -> list[Snapshot]:
    """Последний срез каждого набора: сайт, доска, раздел.

    Имя файла начинается с дня в неизменном формате, поэтому свежий
    выбирается по имени, а сайт и доска читаются уже из содержимого — по
    имени их не разбираем, чтобы разбор не разъехался с записью.
    """
    if not RANK_DIR.is_dir():
        return []

    newest: dict[str, tuple[str, Path]] = {}
    for path in RANK_DIR.glob("*.json"):
        day, _, slug = path.stem.partition("_")
        slug = slug or "all"
        if slug not in newest or day > newest[slug][0]:
            newest[slug] = (day, path)

    found = []
    for day, path in newest.values():
        data = read(path)
        if data and data.rows:
            # У срезов, записанных до появления поля, дня внутри нет.
            data.day = data.day or day
            found.append(data)
    return found


def _same_book(row, other) -> bool:
    """Одно ли это, если названия совпали.

    Авторы сверяются только когда они есть у обоих: у половины рейтингов
    автора в строке нет вовсе, и требовать его значило бы не склеить
    ничего.
    """
    here, there = normalize(row.author), normalize(other.author)
    return not (here and there) or here == there


def board(snapshots=None, names=None, boards=None, categories=None) -> Board:
    """Сводит срезы в одну доску.

    Подписи сайтов, досок и разделов приходят снаружи: их знает тот, кто
    рейтинги настраивает, а не тот, кто их складывает. Своих названий у
    доски нет — только запасное, если подпись не нашлась.
    """
    snapshots = latest() if snapshots is None else list(snapshots)
    names = names or {}
    boards = boards or {}
    categories = categories or {}

    result = Board()
    groups: dict[str, list[Row]] = {}

    for snapshot in snapshots:
        titles = boards.get(snapshot.site) or {}
        result.taken.append({
            "site": snapshot.site,
            "site_name": names.get(snapshot.site, snapshot.site or "Фанкью"),
            "board": snapshot.board,
            "board_name": (titles.get(snapshot.board)
                           or (WHOLE if snapshot.board in ("", "all")
                               else snapshot.board)),
            "category": snapshot.category,
            "category_name": categories.get(snapshot.category, snapshot.category),
            "day": snapshot.day,
            "rows": len(snapshot.rows),
        })
        for entry in snapshot.rows:
            key = normalize(entry.name)
            if not key:
                # Название не расшифровалось. Склеивать такие строки не по
                # чему, и валить их в одну кучу — худшее, что можно
                # сделать: получится одна книга из сотни разных.
                continue

            seat = Seat(
                site=snapshot.site,
                site_name=names.get(snapshot.site, snapshot.site or "Фанкью"),
                place=int(entry.place or 0),
                board=snapshot.board,
                day=snapshot.day,
                link=entry.link or "",
                book_id=entry.book_id or "",
                readers=int(entry.readers or 0),
                score=entry.score,
                metric=entry.metric or "",
            )

            row = next((r for r in groups.get(key, []) if _same_book(r, entry)),
                       None)
            if row is None:
                row = Row(name=entry.name, author=entry.author or "",
                          cover=entry.cover or "")
                groups.setdefault(key, []).append(row)
                result.rows.append(row)
            else:
                row.author = row.author or entry.author or ""
                row.cover = row.cover or entry.cover or ""

            # Одна и та же книга на одном сайте попадает в несколько досок.
            # Оставляем лучшее место: «двадцатая по продажам и сотая по
            # библиотекам» — это про одно и то же, и две строки тут лишние.
            same = next((s for s in row.seats if s.site == seat.site), None)
            if same is None:
                row.seats.append(seat)
            elif seat.place and (not same.place or seat.place < same.place):
                row.seats[row.seats.index(same)] = seat

    # Сначала те, кого узнали в нескольких рейтингах: ради них доска и
    # собирается. Внутри — по лучшему месту.
    result.rows.sort(key=lambda r: (-r.sites, r.best or 10**6, r.name))
    result.taken.sort(key=lambda t: (t["site_name"], t["board_name"],
                                     t["category_name"]))
    return result
