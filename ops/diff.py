"""Сравнение двух версий: что изменилось после операции.

Автоматическая очистка иногда портит текст, и обнаруживается это поздно и
случайно. Здесь то же самое видно сразу: построчно, с пометкой удалённого
и добавленного.

Сравниваются абзацы, а не байты: перенос строки или смена кодировки — не
изменение текста, и показывать их как правку значит топить настоящие
находки в шуме.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from core import formats
from core.readers.base import ReadError

from .base import collect_files

#: Как помечена строка в сравнении.
SAME = "same"
ADDED = "added"
REMOVED = "removed"

#: Абзацев без изменений вокруг правки — чтобы было видно, где она.
CONTEXT = 2

#: Больше этого числа строк в интерфейс не отдаём.
MAX_LINES = 4000


@dataclass
class Line:
    kind: str
    text: str = ""
    left: int | None = None
    right: int | None = None

    def as_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text,
                "left": self.left, "right": self.right}


@dataclass
class ChapterDiff:
    """Различия в одной главе."""

    chapter: str = ""
    lines: list[Line] = field(default_factory=list)
    added: int = 0
    removed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)

    def as_dict(self) -> dict:
        return {"chapter": self.chapter, "added": self.added,
                "removed": self.removed, "changed": self.changed,
                "lines": [l.as_dict() for l in self.lines]}


@dataclass
class Report:
    chapters: list[ChapterDiff] = field(default_factory=list)
    only_left: list = field(default_factory=list)
    only_right: list = field(default_factory=list)

    @property
    def changed(self) -> int:
        return sum(1 for c in self.chapters if c.changed)

    def as_dict(self) -> dict:
        return {
            "chapters": [c.as_dict() for c in self.chapters if c.changed],
            "total": len(self.chapters),
            "changed": self.changed,
            "added": sum(c.added for c in self.chapters),
            "removed": sum(c.removed for c in self.chapters),
            "only_left": self.only_left,
            "only_right": self.only_right,
        }


def compare_paragraphs(before, after, context: int = CONTEXT) -> ChapterDiff:
    """Построчное сравнение двух наборов абзацев.

    Неизменённые куски сворачиваются: в главе на сто абзацев правка в двух
    иначе теряется среди девяноста восьми одинаковых строк.
    """
    result = ChapterDiff()
    matcher = SequenceMatcher(None, list(before), list(after), autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            block = list(before[i1:i2])
            if len(block) <= context * 2:
                shown = [(index, text) for index, text in enumerate(block, i1)]
            else:
                head = [(index, text) for index, text in
                        enumerate(block[:context], i1)]
                tail = [(index, text) for index, text in
                        enumerate(block[-context:], i2 - context)]
                shown = head + [(None, "…")] + tail
            for index, text in shown:
                result.lines.append(Line(kind=SAME, text=text, left=index,
                                         right=None if index is None else
                                         j1 + (index - i1)))
            continue

        for index in range(i1, i2):
            result.lines.append(Line(kind=REMOVED, text=before[index], left=index))
            result.removed += 1
        for index in range(j1, j2):
            result.lines.append(Line(kind=ADDED, text=after[index], right=index))
            result.added += 1

    return result


def _by_key(chapters) -> dict:
    found = {}
    for chapter in chapters:
        key = chapter.number if chapter.number is not None else chapter.title
        found.setdefault(key, chapter)
    return found


def _read(target) -> dict:
    from core.models import OpReport

    from .base import read_all

    report = OpReport()
    files = collect_files(target)
    return _by_key(read_all(files, report))


def compare(before, after, context: int = CONTEXT) -> Report:
    """Сравнивает две папки или два файла: до операции и после."""
    left = _read(before)
    right = _read(after)
    report = Report()

    for key in sorted(set(left) & set(right), key=_order):
        source, target = left[key], right[key]
        diff = compare_paragraphs(source.paragraphs, target.paragraphs, context)
        diff.chapter = source.label or source.title
        report.chapters.append(diff)

    report.only_left = [str(left[k].label or left[k].title)
                        for k in sorted(set(left) - set(right), key=_order)]
    report.only_right = [str(right[k].label or right[k].title)
                         for k in sorted(set(right) - set(left), key=_order)]

    # Строк может быть много — обрезаем, оставляя изменённые главы целиком.
    shown = 0
    for diff in report.chapters:
        if not diff.changed:
            continue
        if shown >= MAX_LINES:
            diff.lines = []
            continue
        shown += len(diff.lines)

    return report


def _order(key):
    return (not isinstance(key, int), key if isinstance(key, int) else str(key))


def compare_files(before: Path, after: Path, context: int = CONTEXT) -> ChapterDiff:
    """Сравнение двух отдельных файлов — одна глава против одной."""
    try:
        left = formats.read(Path(before))
        right = formats.read(Path(after))
    except ReadError as exc:
        raise ValueError(str(exc)) from exc

    source = left[0].paragraphs if left else []
    target = right[0].paragraphs if right else []
    diff = compare_paragraphs(source, target, context)
    diff.chapter = (left[0].label or left[0].title) if left else Path(before).name
    return diff
