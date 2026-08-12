"""Целостность папки с главами: нумерация и дубликаты.

Пропущенная глава обнаруживается обычно уже после публикации, поэтому обе
проверки стоит делать до неё.

Проверка нумерации работает по именам файлов и текст не читает — она
быстрая и идёт первой.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .rename import parse_name

#: Совпадение выше этого порога — подозрение на дубль.
SIMILAR_THRESHOLD = 0.90
#: Слишком короткие главы в сравнение не берём: они похожи друг на друга
#: просто потому, что коротки.
MIN_COMPARE_CHARS = 200
#: По скольку слов берём куски для быстрого сравнения.
SHINGLE_WORDS = 5
#: Пересечение кусков падает быстрее посимвольного сходства, поэтому порог
#: для отсева берём с запасом — иначе потеряем настоящие дубли.
JACCARD_SLACK = 0.6


@dataclass
class NumberingReport:
    """Что не так с нумерацией глав в папке."""

    total: int = 0
    first: int | None = None
    last: int | None = None
    missing: list[int] = field(default_factory=list)
    duplicates: list[dict] = field(default_factory=list)
    missing_parts: list[str] = field(default_factory=list)
    out_of_range: list[dict] = field(default_factory=list)
    unnumbered: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not (
            self.missing or self.duplicates or self.missing_parts or self.out_of_range
        )

    def summary(self) -> str:
        """Строка вида «Глав: 164 · пропущено: 2 (203, 287) · дублей: 1 (205)»."""
        parts = [f"Глав: {self.total}"]
        if self.missing:
            parts.append(f"пропущено: {len(self.missing)} ({_compact(self.missing)})")
        if self.duplicates:
            numbers = ", ".join(str(row["number"]) for row in self.duplicates)
            parts.append(f"дублей: {len(self.duplicates)} ({numbers})")
        if self.missing_parts:
            parts.append(f"пропуски частей: {', '.join(self.missing_parts)}")
        if self.out_of_range:
            numbers = ", ".join(str(row["number"]) for row in self.out_of_range)
            parts.append(f"вне диапазона: {numbers}")
        if self.unnumbered:
            parts.append(f"без номера: {len(self.unnumbered)}")
        if len(parts) == 1:
            parts.append("нумерация целая")
        return " · ".join(parts)

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "first": self.first,
            "last": self.last,
            "missing": self.missing,
            "duplicates": self.duplicates,
            "missing_parts": self.missing_parts,
            "out_of_range": self.out_of_range,
            "unnumbered": self.unnumbered,
            "clean": self.clean,
            "summary": self.summary(),
        }


def _compact(numbers: list[int]) -> str:
    """[1,2,3,7] → «1–3, 7»."""
    if not numbers:
        return ""
    parts, start, previous = [], numbers[0], numbers[0]
    for number in numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}–{previous}")
        start = previous = number
    parts.append(str(start) if start == previous else f"{start}–{previous}")
    return ", ".join(parts)


#: Разрыв между соседними номерами, после которого хвост считается выбросом.
OUTLIER_GAP = 20


def _split_outliers(numbers: list[int]) -> tuple[list[int], list[int]]:
    """Делит номера на основную массу и выбросы.

    Ищем самый большой разрыв между соседними номерами: если он заметно
    больше обычного шага, то меньшая из двух частей — выброс вроде главы 999
    среди 201–365.
    """
    if len(numbers) < 4:
        return numbers, []

    gaps = [(numbers[i + 1] - numbers[i], i) for i in range(len(numbers) - 1)]
    widest, index = max(gaps)
    if widest <= OUTLIER_GAP:
        return numbers, []

    left, right = numbers[: index + 1], numbers[index + 1:]
    # Выброс — та часть, что меньше; при равенстве считаем целым списком.
    if len(left) == len(right):
        return numbers, []
    return (left, right) if len(left) > len(right) else (right, left)


def check_numbering(files: list[Path], pattern: str | None = None) -> NumberingReport:
    """Пропуски, дубли, пропущенные части и главы вне диапазона."""
    report = NumberingReport()
    by_number: dict[int, list[str]] = defaultdict(list)
    parts_by_number: dict[int, set[int]] = defaultdict(set)

    for path in files:
        name = parse_name(path.stem, pattern)
        if name.number is None:
            report.unnumbered.append(path.name)
            continue
        if name.part is None:
            by_number[name.number].append(path.name)
        else:
            parts_by_number[name.number].add(name.part)
            # Глава, разрезанная на части, присутствует целиком.
            by_number.setdefault(name.number, [])

    numbers = sorted(by_number)
    report.total = len(numbers)
    if not numbers:
        return report

    # Выпадающие из диапазона ищем ПЕРВЫМИ: без этого одна глава 999 среди
    # 201–365 превращает список пропусков в шестьсот номеров.
    core, outliers = _split_outliers(numbers)
    for number in outliers:
        report.out_of_range.append({"number": number, "files": by_number[number]})

    report.first, report.last = core[0], core[-1]

    # Пропуски считаем только внутри основного диапазона.
    present = set(core)
    report.missing = [n for n in range(report.first, report.last + 1) if n not in present]

    # Два файла с одним номером.
    for number in numbers:
        names = by_number[number]
        if len(names) > 1:
            report.duplicates.append({"number": number, "files": sorted(names)})

    # Пропуски в частях: есть 201.1 и 201.3, но нет 201.2.
    for number, parts in sorted(parts_by_number.items()):
        gaps = [p for p in range(1, max(parts) + 1) if p not in parts]
        if gaps:
            listing = ", ".join(f"{number}.{p}" for p in gaps)
            report.missing_parts.append(listing)

    return report


# ------------------------------------------------------------- дубликаты


PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Текст без регистра, пунктуации и лишних пробелов — для сравнения."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    text = PUNCT.sub("", text)
    return SPACES.sub(" ", text).strip()


def text_hash(text: str) -> str:
    return hashlib.sha1(normalize(text).encode("utf-8")).hexdigest()


@dataclass
class DuplicatePair:
    left: str
    right: str
    ratio: float

    @property
    def exact(self) -> bool:
        return self.ratio >= 0.999

    def as_dict(self) -> dict:
        return {
            "left": self.left,
            "right": self.right,
            "percent": round(self.ratio * 100),
            "exact": self.exact,
        }


def shingles(text: str, size: int = SHINGLE_WORDS) -> frozenset[int]:
    """Множество хешей от последовательностей слов.

    Сравнивать главы посимвольно слишком дорого: на книге из 165 глав это
    больше тринадцати тысяч пар по пять килобайт каждая. Пересечение
    множеств справляется за доли секунды и не хуже отличает дубль от
    просто похожего текста.
    """
    words = text.split()
    if len(words) < size:
        return frozenset({hash(text)}) if text else frozenset()
    return frozenset(
        hash(" ".join(words[i:i + size])) for i in range(len(words) - size + 1)
    )


def jaccard(left: frozenset[int], right: frozenset[int]) -> float:
    """Доля общих кусков: |A∩B| / |A∪B|."""
    if not left or not right:
        return 0.0
    common = len(left & right)
    return common / (len(left) + len(right) - common)


def find_duplicates(
    texts: dict[str, str], threshold: float = SIMILAR_THRESHOLD
) -> list[DuplicatePair]:
    """Главы с одинаковым или почти одинаковым текстом.

    Полные совпадения ловятся по хешу — это дёшево. Похожие сначала
    отсеиваются по пересечению кусков, и лишь немногие выжившие пары
    сравниваются посимвольно, чтобы показать точный процент.
    """
    prepared = {
        name: normalize(text)
        for name, text in texts.items()
        if len(normalize(text)) >= MIN_COMPARE_CHARS
    }

    pairs: list[DuplicatePair] = []
    seen: set[tuple[str, str]] = set()

    # 1. Точные совпадения — по хешу.
    by_hash: dict[str, list[str]] = defaultdict(list)
    for name, text in prepared.items():
        by_hash[hashlib.sha1(text.encode("utf-8")).hexdigest()].append(name)

    for names in by_hash.values():
        if len(names) < 2:
            continue
        ordered = sorted(names)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1:]:
                pairs.append(DuplicatePair(left, right, 1.0))
                seen.add((left, right))

    # 2. Похожие: сначала дешёвый отсев по кускам, потом точный процент.
    marks = {name: shingles(text) for name, text in prepared.items()}
    names = sorted(prepared)

    for index, left in enumerate(names):
        for right in names[index + 1:]:
            if (left, right) in seen:
                continue
            a, b = prepared[left], prepared[right]
            shorter, longer = sorted((len(a), len(b)))
            if longer == 0 or shorter / longer < threshold:
                continue
            if jaccard(marks[left], marks[right]) < threshold * JACCARD_SLACK:
                continue
            ratio = SequenceMatcher(None, a, b).ratio()
            if ratio >= threshold:
                pairs.append(DuplicatePair(left, right, ratio))

    pairs.sort(key=lambda pair: -pair.ratio)
    return pairs
