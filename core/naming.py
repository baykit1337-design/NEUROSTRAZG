"""Разбор и сборка имён глав — единственное место в проекте.

И «Разбить», и «Объединить», и «Переименовать», и «Проверка» ходят сюда:
иначе правка разбора в одной вкладке не доходит до остальных.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Слова, которыми помечают главу. Список неполный намеренно: разбор на
#: него не опирается, всё до номера отбрасывается независимо от языка.
#: Держим только для обратной совместимости старых шаблонов.
CHAPTER_WORD = r"(?:Глава|ГЛАВА|глава|Chapter|CHAPTER|chapter|Часть|Part)"

#: Группа цифр длиной 1–5. Шесть и больше — это год, дата или внутренний
#: код, но не номер главы. Границы `(?<!\d)` и `(?!\d)` нужны, чтобы из
#: «123456» не выхватить «12345».
NUMBER_GROUP = re.compile(r"(?<!\d)(\d{1,5})(?!\d)")

#: Номер части идёт вплотную за номером главы: «361.2». С пробелом это уже
#: не часть, а начало названия — «Глава 5. 100 дней».
PART_AFTER = re.compile(r"^[.,](\d{1,3})(?!\d)")

#: Разделители между номером и названием — в любом сочетании и количестве.
#: Сюда же китайская и японская пунктуация: имена приходят на любом языке.
SEPARATOR_CHARS = " \t.:_\-–—―)\]},;、，。：；·・|«»\"'"
SEPARATORS_RE = re.compile(rf"^[{re.escape(SEPARATOR_CHARS)}]+")

#: Иероглиф «глава» стоит ПОСЛЕ номера: 第 244 章 标题, и пробела при нём
#: может не быть вовсе. Сразу за номером это пометка, а не начало названия.
CJK_CHAPTER = re.compile(r"^[章回節节話话篇卷幕]")

#: Порядковый номер файла в начале имени: «0010 - », «0010_», «0010.».
SEQ_RE = re.compile(rf"^\s*(\d+)\s*[{re.escape(SEPARATOR_CHARS)}]\s*(.*)$", re.S)

#: Совместимость: шаблон, который интерфейс показывает как отправную точку
#: для своего варианта.
NUMBER_RE = re.compile(
    rf"^\s*(?:{CHAPTER_WORD}\s*)?"
    r"(?P<number>\d+)"
    r"(?:[.,](?P<part>\d+))?"
    r"(?:\s*(?:[.:\-–—]|\s)\s*(?P<title>.*?))?\s*$",
    re.S,
)

#: Интерфейс показывает её как отправную точку для своего варианта.
DEFAULT_PATTERN = NUMBER_RE.pattern

#: На столько номер может отличаться от общего диапазона папки, прежде чем
#: разбор будет помечен сомнительным.
SUSPECT_GAP = 100

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
    def numbered(self) -> bool:
        """Номер главы удалось вынуть из имени."""
        return self.number is not None


def parse(stem: str, pattern: str | None = None) -> NameParts:
    """Раскладывает имя файла (без расширения) на составляющие.

    Разбор не опирается ни на язык, ни на слово «глава». Единственное, что
    ищется, — первая группа из 1–5 цифр. Всё до неё отбрасывается (там
    стоит пометка главы на каком угодно языке: `Chapter`, `Глава`, `第`),
    всё после, за вычетом разделителей, становится названием.

    Порядковый номер файла в начале (`0001 - `) отбрасывается, но **только
    если дальше по строке есть другой номер**. Иначе в `0001 - Информация`
    отбрасывать было бы нечего и файл остался бы без номера вовсе.

    Чисел нет совсем — не беда: номер такому файлу присвоит вызывающий, по
    порядку в папке. Понятия «служебный файл», который выпадает из списка,
    больше нет: пользователь снимает галочку сам.
    """
    if pattern:
        return _by_pattern(stem, pattern)

    text = stem.strip()
    groups = list(NUMBER_GROUP.finditer(text))
    if not groups:
        return NameParts(title=text)

    seq = None
    head = groups[0]
    # Порядковый номер стоит в самом начале и отделён разделителем.
    at_start = text[:head.start()].strip() == ""
    if at_start and len(groups) > 1 and SEQ_RE.match(text):
        seq = int(head.group(1))
        head = groups[1]

    number = int(head.group(1))
    rest = text[head.end():]

    part = None
    piece = PART_AFTER.match(rest)
    if piece:
        part = int(piece.group(1))
        rest = rest[piece.end():]

    return NameParts(seq=seq, number=number, part=part, title=_title(rest))


def _title(rest: str) -> str:
    """Название главы из хвоста имени, без разделителей и пометок."""
    rest = SEPARATORS_RE.sub("", rest)
    # 第 244 章 标题: иероглиф «глава» стоит после номера, в названии он лишний.
    rest = CJK_CHAPTER.sub("", rest)
    return SEPARATORS_RE.sub("", rest).strip()


def _by_pattern(stem: str, pattern: str) -> NameParts:
    """Разбор своим регулярным выражением пользователя."""
    try:
        match = re.match(pattern, stem)
    except re.error as exc:
        raise NamingError(f"Неверное регулярное выражение: {exc}") from exc
    if not match:
        return NameParts(title=stem.strip())

    groups = match.groupdict()
    return NameParts(
        seq=_int(groups.get("seq")),
        number=_int(groups.get("number")),
        part=_int(groups.get("part")),
        title=(groups.get("title") or "").strip(),
    )


#: Сколько символов пометки допускается перед номером в ЗАГОЛОВКЕ.
#: «Глава 201» и «第 244 章» проходят, «Первый абзац 201.» — нет.
HEADING_PREFIX = 12

#: Пометка главы перед номером — ОДНО короткое слово без цифр и знаков
#: препинания: «Глава», «Chapter», «第». Два слова и больше — это уже
#: предложение: «Он пришёл в 1945 году» заголовком не является.
HEADING_RE = re.compile(
    rf"^\s*(?:[^\s\d.!?;:]{{1,{HEADING_PREFIX}}}\s*)?(?<!\d)(\d{{1,5}})(?!\d)")


def heading_number(text: str) -> int | None:
    """Номер главы, если строка похожа на ЗАГОЛОВОК, а не на текст.

    Разбор имени файла намеренно нестрогий: число ищется где угодно. Для
    абзаца так нельзя — иначе «Первый абзац 201.» станет заголовком главы
    201, а первый абзац текста пропадёт. Здесь номер обязан стоять в
    начале, самое большее за короткой пометкой вроде «Глава» или «第».
    """
    match = HEADING_RE.match(text)
    return int(match.group(1)) if match else None


def suspects(numbers) -> set[int]:
    """Номера, выбивающиеся из общего диапазона папки.

    Разбор мог ошибиться: из даты в имени выйдет «глава 2024» посреди
    двухсот обычных. Такую строку помечаем «проверьте», но из списка не
    убираем — решает человек.
    """
    known = sorted(n for n in numbers if n is not None)
    if len(known) < 3:
        return set()

    # Границы берём по краям без хвостов: сам выброс не должен растягивать
    # диапазон, из которого он выбивается.
    low = known[int(len(known) * 0.1)]
    high = known[int(len(known) * 0.9) - 1]
    return {n for n in known if n < low - SUSPECT_GAP or n > high + SUSPECT_GAP}


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
