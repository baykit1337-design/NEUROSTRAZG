"""Что у книги на самом деле лежит на диске.

Библиотека помнит, сколько глав она скачала. Это память о прогоне, а не
о диске: папку могли переименовать, перенести на другой диск, вычистить
руками или потерять вместе с флешкой. Запись при этом остаётся, и
«скачано 402» продолжает говорить о книге, которой нет. Узнать об этом
можно было только сходив в проводник — по одной книге из сотни.

Файлов здесь не читаем. Их бывает полторы тысячи на книгу и сотня книг в
библиотеке, а на вопросы «папка на месте?», «сколько глав?», «сколько
занимает?» и «нет ли дыр в номерах?» отвечают имя и размер. Чтение —
работа осмотра (`ops/checkup`), и делается она по одной книге и по
просьбе.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core import formats, naming
from core.longpath import wide

from . import library

log = logging.getLogger(__name__)

#: Что считаем главой. Берём из общего списка читаемых расширений: свой
#: экземпляр разошёлся бы с ним на первом же новом формате.
CHAPTERS = frozenset(formats.READABLE)

#: Служебное в папке книги. Это не главы, и в счёт они не идут.
#:
#: Паспорт — `.md`, то есть с виду ровно такая же глава, как остальные;
#: имя ему берём у библиотеки, которая его и пишет. Своим экземпляром
#: имени я уже ошибся один раз, и книга насчитывала на главу больше.
SERVICE = frozenset({"state.json", library.PASSPORT.lower()})

#: Меньше этого — глава пустая. Не ноль: сайт отдаёт «глава недоступна»
#: в полторы строки, и такой файл на диске есть, а главы в нём нет.
EMPTY_BYTES = 200

#: Сколько пропусков показывать. Книга на полторы тысячи глав, потерявшая
#: половину, дала бы список во весь экран, а решение принимают по первым.
SHOW = 12


@dataclass
class Shelf:
    """Полка одной книги: что нашлось в её папке."""

    folder: str = ""
    #: Есть ли папка вообще. Нет — остальное не считалось.
    exists: bool = False
    #: Сколько файлов-глав нашлось.
    files: int = 0
    #: Сколько они занимают.
    bytes: int = 0
    #: Первый и последний номер главы из имён файлов.
    first: int = 0
    last: int = 0
    #: Номера, которых внутри диапазона нет.
    gaps: list = field(default_factory=list)
    gaps_count: int = 0
    #: Файлы, которые есть, но пусты.
    empty: list = field(default_factory=list)
    empty_count: int = 0
    #: Почему посмотреть не вышло. Пусто — вышло.
    trouble: str = ""

    @property
    def whole(self) -> bool:
        """Всё ли на месте: папка есть, главы есть, дыр и пустых нет."""
        return bool(self.exists and self.files
                    and not self.gaps_count and not self.empty_count)

    def as_dict(self) -> dict:
        return {"folder": self.folder, "exists": self.exists,
                "files": self.files, "bytes": self.bytes,
                "first": self.first, "last": self.last,
                "gaps": self.gaps, "gaps_count": self.gaps_count,
                "empty": self.empty, "empty_count": self.empty_count,
                "trouble": self.trouble, "whole": self.whole}


def _ranges(numbers) -> list:
    """Подряд идущие числа — одной строкой: «1170–1175».

    Пятьсот пропущенных номеров по одному не читаются вовсе, а тремя
    строками диапазонов — читаются.
    """
    out: list = []
    for number in sorted(numbers):
        if out:
            low, _, high = str(out[-1]).partition("–")
            if number == int(high or low) + 1:
                out[-1] = f"{low}–{number}"
                continue
        out.append(str(number))
    return out


def _chapters(folder: Path):
    """Файлы-главы папки: путь, номер и размер.

    Вложенные папки не обходим: книга лежит одним слоем, а внутри её
    папки бывает «копия перед правкой» — и её главы посчитались бы
    второй раз.
    """
    for item in sorted(folder.iterdir()):
        if not item.is_file():
            continue
        if item.name.lower() in SERVICE:
            continue
        if item.suffix.lower() not in CHAPTERS:
            continue
        yield item


def look(folder) -> Shelf:
    """Посмотреть, что лежит в папке книги. Ничего не меняет."""
    said = Shelf(folder=str(folder or ""))
    if not said.folder.strip():
        said.trouble = "папка не записана"
        return said

    where = Path(said.folder).expanduser()
    try:
        if not where.is_dir():
            said.trouble = "папки нет на месте"
            return said
        said.exists = True

        numbers: list[int] = []
        for item in _chapters(Path(wide(where))):
            size = item.stat().st_size
            said.files += 1
            said.bytes += size
            if size < EMPTY_BYTES:
                said.empty_count += 1
                if len(said.empty) < SHOW:
                    said.empty.append(item.name)
            found = naming.parse(item.stem)
            if found.number is not None:
                numbers.append(found.number)
    except OSError as exc:
        # Диск отключили, путь длиннее допустимого, прав нет — всё это
        # «посмотреть не вышло», а не «книги нет».
        log.warning("Папку «%s» не осмотреть: %s", said.folder, exc)
        said.trouble = f"папку не прочитать: {exc}"
        return said

    if numbers:
        said.first, said.last = min(numbers), max(numbers)
        # Дыры ищем только внутри своего диапазона: книга может
        # начинаться с 1168-й главы, и «нет глав с 1 по 1167» — не
        # находка, а начало книги.
        seen = set(numbers)
        holes = [n for n in range(said.first, said.last + 1) if n not in seen]
        said.gaps_count = len(holes)
        said.gaps = _ranges(holes)[:SHOW]
    return said


def weigh(books) -> dict:
    """Сколько всего занимают книги и сколько из них не в порядке."""
    shelves = list(books)
    return {
        "books": len(shelves),
        "bytes": sum(one.bytes for one in shelves),
        "files": sum(one.files for one in shelves),
        "missing": sum(1 for one in shelves if not one.exists),
        # У пропавшей папки дыр не бывает: смотреть было нечего, и
        # считаться второй раз она не станет.
        "holed": sum(1 for one in shelves
                     if one.gaps_count or one.empty_count),
    }


__all__ = ["CHAPTERS", "EMPTY_BYTES", "SERVICE", "SHOW", "Shelf", "look",
           "weigh"]
