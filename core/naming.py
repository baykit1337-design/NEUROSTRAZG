"""Разбор и сборка имён глав — единственное место в проекте.

И «Разбить», и «Объединить», и «Переименовать», и «Проверка» ходят сюда:
иначе правка разбора в одной вкладке не доходит до остальных.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Слова, которыми помечают главу. Нужны, чтобы отличить номер главы от
#: порядкового номера файла.
CHAPTER_WORD = r"(?:Глава|ГЛАВА|глава|Chapter|CHAPTER|chapter|Часть|Part)"

#: Порядковый номер файла в начале имени: «0010 - ».
SEQ_RE = re.compile(r"^\s*(\d+)\s*[-–—]\s*(.*)$", re.S)

#: Номер главы с необязательной приставкой и необязательным номером части.
NUMBER_RE = re.compile(
    rf"^\s*(?:{CHAPTER_WORD}\s*)?"
    r"(?P<number>\d+)"
    r"(?:[.,](?P<part>\d+))?"
    r"(?:\s*(?:[.:\-–—]|\s)\s*(?P<title>.*?))?\s*$",
    re.S,
)

#: Интерфейс показывает её как отправную точку для своего варианта.
DEFAULT_PATTERN = NUMBER_RE.pattern

DEFAULT_PREFIX = "Глава"
DEFAULT_SEPARATOR = ": "
#: Разделители перед названием, предлагаемые в интерфейсе.
SEPARATORS = (": ", ". ", " — ", " - ")

#: Символы, запрещённые в именах файлов. Набор объединённый: на Windows
#: свой список, на macOS запрещено двоеточие — чистим по обоим, чтобы файлы
#: переносились между системами без сюрпризов.
#:
#: Просто выбрасывать нельзя: из «Глава 201: Конец» вышло бы «Глава 201
#: Конец», и разделитель пропал бы совсем. Подставляем эквивалент.
FORBIDDEN_MAP = {
    ":": " -", "/": "-", "\\": "-", "|": "-",
    "*": "", "?": "", '"': "'", "<": "(", ">": ")",
}

#: Имена, зарезервированные Windows: файл с таким именем создать нельзя.
RESERVED = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{n}" for n in range(1, 10)]
    + [f"lpt{n}" for n in range(1, 10)]
)

#: Управляющие символы в именах не нужны никому.
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_NAME = 150


class NamingError(Exception):
    """Имя не удалось разобрать."""


def safe_filename(name: str) -> str:
    """Имя файла, пригодное и для Windows, и для macOS."""
    for bad, good in FORBIDDEN_MAP.items():
        name = name.replace(bad, good)
    name = CONTROL.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")

    if name.split(".")[0].lower() in RESERVED:
        name = f"_{name}"
    return name[:MAX_NAME].strip() or "без имени"


def has_forbidden(text: str) -> bool:
    """Есть ли в строке символы, запрещённые в именах файлов."""
    return any(bad in text for bad in FORBIDDEN_MAP)


@dataclass
class NameParts:
    """Что вышло из имени файла."""

    seq: int | None = None
    number: int | None = None
    part: int | None = None
    title: str = ""

    @property
    def service(self) -> bool:
        """Номера главы нет — файл служебный («Информация», «Обложка»)."""
        return self.number is None


def parse(stem: str, pattern: str | None = None) -> NameParts:
    """Раскладывает имя файла (без расширения) на составляющие.

    Разбор идёт в два шага, и это принципиально: сначала отрезается
    порядковый номер файла, и только в остатке ищется номер главы. Иначе
    `0001 - Информация` превращается в «главу 1», хотя это служебный файл
    без номера вовсе.

    Порядковый номер разбирается, но в новое имя не попадает — он нужен
    только чтобы понять исходный порядок.
    """
    if pattern:
        try:
            match = re.match(pattern, stem)
        except re.error as exc:
            raise NamingError(f"Неверное регулярное выражение: {exc}") from exc
        if not match:
            return NameParts(seq=_leading_int(stem), title=stem.strip())
        groups = match.groupdict()
        return NameParts(
            seq=_int(groups.get("seq")),
            number=_int(groups.get("number")),
            part=_int(groups.get("part")),
            title=(groups.get("title") or "").strip(),
        )

    seq = None
    rest = stem.strip()
    head = SEQ_RE.match(rest)
    if head:
        seq, rest = int(head.group(1)), head.group(2).strip()

    match = NUMBER_RE.match(rest)
    if not match:
        return NameParts(seq=seq if seq is not None else _leading_int(stem),
                         title=rest or stem.strip())

    return NameParts(
        seq=seq,
        number=_int(match.group("number")),
        part=_int(match.group("part")),
        title=(match.group("title") or "").strip(),
    )


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _leading_int(stem: str) -> int | None:
    match = re.match(r"\s*(\d+)", stem)
    return int(match.group(1)) if match else None


#: Порядковый номер файла «0010 - » в начале имени. В заголовок главы он не
#: идёт: это служебная нумерация, нужная только для сортировки.
SEQ_PREFIX = re.compile(r"^\s*\d+\s*[-–—]\s*")


def clean_title(stem: str) -> str:
    """Заголовок главы из имени файла, без порядкового номера."""
    return SEQ_PREFIX.sub("", stem.strip()).strip() or stem.strip()


@dataclass
class NameFormat:
    """Три галочки формата имени плюс приставка и разделитель."""

    number: bool = True
    part: bool = True
    title: bool = True
    prefix: str = DEFAULT_PREFIX
    separator: str = DEFAULT_SEPARATOR

    @classmethod
    def from_dict(cls, data: dict | None) -> NameFormat:
        data = data or {}
        prefix = data.get("prefix")
        separator = data.get("separator")
        return cls(
            number=bool(data.get("number", True)),
            part=bool(data.get("part", True)),
            title=bool(data.get("title", True)),
            # Приставку можно очистить, поэтому проверяем на None.
            prefix=DEFAULT_PREFIX if prefix is None else str(prefix),
            separator=DEFAULT_SEPARATOR if separator is None else str(separator),
        )


def build(number: int | None, part: int | None, title: str, fmt: NameFormat) -> str:
    """Собирает имя главы по галочкам.

    Номер части подставляется только если он есть: у целой главы части нет,
    и включённая галочка ничего не добавляет.
    """
    head = ""
    if fmt.number and number is not None:
        head = f"{fmt.prefix} {number}".strip() if fmt.prefix else str(number)
        if fmt.part and part is not None:
            head = f"{head}.{part}"

    name = head
    if fmt.title and title:
        name = f"{head}{fmt.separator}{title}" if head else title

    # Все галочки сняты — пустое имя недопустимо, оставляем номер.
    if not name.strip():
        name = str(number) if number is not None else title
    return safe_filename(name.strip())


def sort_key(chapter) -> tuple:
    """Сортировка по паре чисел (номер главы, номер части), не по имени.

    Иначе «Глава 361.10» встаёт перед «Глава 361.2».
    """
    number = getattr(chapter, "number", None)
    part = getattr(chapter, "part", None)
    return (number is None, number or 0, part or 0)


def name_width(total: int) -> int:
    """Ведущие нули по длине списка, минимум 4 знака."""
    return max(4, len(str(total)))
