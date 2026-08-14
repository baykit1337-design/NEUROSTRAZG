"""Сверка оригинала и перевода по номерам глав.

Модель иногда молча пропускает абзац или обрывает главу на середине.
Глазами на пятистах главах это не поймать, а по числам — сразу видно.

Ничего не исправляет: только показывает, где смотреть.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.models import OpReport
from core.registry import QUOTE_LIMIT

from .base import Progress, collect_files, read_all

#: На сколько может расходиться число абзацев, прежде чем это подозрительно.
PARAGRAPH_GAP = 0.10

#: Русский текст обычно длиннее английского в 1.1–1.3 раза. Выход за эти
#: границы с запасом означает, что кусок потерян или дописан.
RATIO_LOW = 0.8
RATIO_HIGH = 1.8

#: Короче этого перевод главы считается пустым или обрезанным.
MIN_CHARS = 200

KINDS = {
    "missing": "Нет в переводе",
    "extra": "Нет в оригинале",
    "paragraphs": "Разное число абзацев",
    "ratio": "Подозрительный объём",
    "empty": "Пустая или обрезанная",
}


@dataclass
class Finding:
    kind: str
    chapter: str = ""
    message: str = ""
    source: str = ""

    @property
    def kind_name(self) -> str:
        return KINDS.get(self.kind, self.kind)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "kind_name": self.kind_name,
                "chapter": self.chapter, "message": self.message[:QUOTE_LIMIT],
                "source": self.source}


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    original: int = 0
    translated: int = 0
    matched: int = 0
    unreadable: list = field(default_factory=list)

    @property
    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
        return counts

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "total": len(self.findings),
            "original": self.original,
            "translated": self.translated,
            "matched": self.matched,
            "unreadable": self.unreadable,
            "summary": [
                {"kind": k, "kind_name": KINDS.get(k, k), "count": v}
                for k, v in sorted(self.summary.items(), key=lambda kv: -kv[1])
            ],
        }


def _by_number(chapters) -> dict:
    """Главы по номеру. Без номера — по названию, чтобы не потерялись."""
    found = {}
    for chapter in chapters:
        key = chapter.number if chapter.number is not None else chapter.title
        found.setdefault(key, chapter)
    return found


def _read(targets, progress) -> tuple[dict, list]:
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)
    return _by_number(chapters), [f.as_text() for f in report.failures]


def check(original, translated, kinds=None,
          progress: Progress | None = None) -> Report:
    """Сверяет две папки: оригинал и перевод."""
    wanted = set(kinds) if kinds else set(KINDS)
    left, bad_left = _read(original, progress)
    right, bad_right = _read(translated, progress)

    report = Report(original=len(left), translated=len(right),
                    unreadable=bad_left + bad_right)

    for key in sorted(left, key=_order):
        source = left[key]
        target = right.get(key)
        label = source.label or source.title

        if target is None:
            if "missing" in wanted:
                report.findings.append(Finding(
                    kind="missing", chapter=label, source=source.source,
                    message="глава есть в оригинале, но её нет в переводе"))
            continue

        report.matched += 1
        report.findings.extend(_compare(source, target, label, wanted))

    if "extra" in wanted:
        for key in sorted(set(right) - set(left), key=_order):
            extra = right[key]
            report.findings.append(Finding(
                kind="extra", chapter=extra.label or extra.title,
                source=extra.source,
                message="глава есть в переводе, но её нет в оригинале"))

    return report


def _order(key):
    return (not isinstance(key, int), key if isinstance(key, int) else str(key))


def _compare(source, target, label, wanted) -> list[Finding]:
    found = []

    if "empty" in wanted and target.size < MIN_CHARS:
        found.append(Finding(
            kind="empty", chapter=label, source=target.source,
            message=(f"в переводе {target.size} символов — "
                     f"похоже, глава пустая или оборвана")))
        # Дальше сравнивать нечего: пустую главу и так надо смотреть.
        return found

    if "paragraphs" in wanted:
        a, b = len(source.paragraphs), len(target.paragraphs)
        if a and abs(a - b) / a > PARAGRAPH_GAP:
            found.append(Finding(
                kind="paragraphs", chapter=label, source=target.source,
                message=(f"абзацев в оригинале {a}, в переводе {b} — "
                         f"что-то пропущено или склеено")))

    if "ratio" in wanted and source.size:
        ratio = target.size / source.size
        if ratio < RATIO_LOW or ratio > RATIO_HIGH:
            found.append(Finding(
                kind="ratio", chapter=label, source=target.source,
                message=(f"объём перевода к оригиналу {ratio:.2f} "
                         f"(обычно {RATIO_LOW}–{RATIO_HIGH}): "
                         f"{source.size} против {target.size} символов")))

    return found
