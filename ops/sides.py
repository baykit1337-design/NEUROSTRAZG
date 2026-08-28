"""Одна книга с двух сайтов: где они расходятся.

Слив бывает обрезан — то главы кончаются на середине, то их просто нет, —
и понять это по одной папке нельзя: она выглядит целой. А рядом лежит та
же книга с другого сайта, и разница видна сразу.

От сверки оригинала с переводом (`ops/compare`) отличие в том, что здесь
нет главной стороны. Там перевод обязан повторять оригинал, и всё, что
разошлось, — вина перевода. Здесь обе стороны равны, объём должен
совпадать примерно один к одному, и вопрос ровно один: какую из двух
папок брать.

Ничего не сливает и не чинит: только показывает, что выбрать.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.models import OpReport

from .base import Progress, collect_files, read_all

#: Подписи находок. Список закрытый: интерфейс берёт названия отсюда.
KINDS = {
    "only_left": "Есть только слева",
    "only_right": "Есть только справа",
    "empty_left": "Слева нет текста",
    "empty_right": "Справа нет текста",
    "shorter_left": "Слева заметно короче",
    "shorter_right": "Справа заметно короче",
}

#: Какие находки говорят, что обрезана левая сторона, а какие — правая.
AGAINST_LEFT = frozenset({"only_right", "empty_left", "shorter_left"})
AGAINST_RIGHT = frozenset({"only_left", "empty_right", "shorter_right"})

#: Во сколько раз глава должна быть короче соседней, чтобы это перестало
#: быть разницей переводов и стало обрывом. Два перевода одной главы
#: расходятся в объёме на четверть, вдвое — уже не расходятся.
SHORT = 0.6

#: Короче этого глава считается пустой: у сливов вместо текста часто
#: остаётся строчка «продолжение на сайте».
MIN_CHARS = 200

#: Больше этого числа находок одного рода в интерфейс не отдаём.
SHOW = 40


@dataclass
class Finding:
    kind: str
    chapter: str = ""
    left: int = 0
    right: int = 0

    @property
    def kind_name(self) -> str:
        return KINDS.get(self.kind, self.kind)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "kind_name": self.kind_name,
                "chapter": self.chapter, "left": self.left, "right": self.right}


@dataclass
class Verdict:
    """Что вышло из сравнения двух папок."""

    left_name: str = ""
    right_name: str = ""
    left_total: int = 0
    right_total: int = 0
    matched: int = 0
    findings: list[Finding] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        found: dict[str, int] = {}
        for finding in self.findings:
            found[finding.kind] = found.get(finding.kind, 0) + 1
        return found

    @property
    def against_left(self) -> int:
        return sum(1 for f in self.findings if f.kind in AGAINST_LEFT)

    @property
    def against_right(self) -> int:
        return sum(1 for f in self.findings if f.kind in AGAINST_RIGHT)

    @property
    def fuller(self) -> str:
        """Какую папку брать: «left», «right» или пусто, если поровну."""
        if self.against_left > self.against_right:
            return "right"
        if self.against_right > self.against_left:
            return "left"
        return ""

    def advice(self) -> str:
        """Ответ на вопрос, ради которого сравнение и затевалось."""
        if not self.findings:
            return (f"Расхождений нет: {self.matched} "
                    f"{_chapters(self.matched)} совпадают, брать можно любую.")

        counts = self.counts
        side = self.fuller
        if not side:
            return (f"Ни одна не полнее: у каждой по {self.against_left} "
                    f"{_spots(self.against_left)}, где обрезана она. "
                    "Выбирать глазами.")

        name = "Левая" if side == "left" else "Правая"
        only = counts.get("only_left" if side == "left" else "only_right", 0)
        cut = (counts.get("shorter_right", 0) + counts.get("empty_right", 0)
               if side == "left"
               else counts.get("shorter_left", 0) + counts.get("empty_left", 0))

        tail = []
        if only:
            tail.append(f"{only} {_chapters(only)} есть только в ней")
        if cut:
            tail.append(f"ещё в {cut} {_spots(cut)} у соседней текст обрезан")
        if not tail:
            return f"{name} папка полнее."
        return f"{name} папка полнее: " + ", ".join(tail) + "."

    def as_dict(self) -> dict:
        counts = self.counts
        return {
            "left_name": self.left_name,
            "right_name": self.right_name,
            "left_total": self.left_total,
            "right_total": self.right_total,
            "matched": self.matched,
            "total": len(self.findings),
            "fuller": self.fuller,
            "advice": self.advice(),
            "unreadable": self.unreadable,
            "summary": [
                {"kind": kind, "kind_name": KINDS[kind], "count": counts[kind]}
                for kind in KINDS if kind in counts
            ],
            "findings": [f.as_dict() for f in self.findings[:SHOW * len(KINDS)]],
        }


def _chapters(count: int) -> str:
    return "глава" if count % 10 == 1 and count % 100 != 11 else (
        "главы" if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14
        else "глав")


def _spots(count: int) -> str:
    return "месте" if count % 10 == 1 and count % 100 != 11 else "местах"


def _by_number(chapters) -> dict:
    """Главы по номеру. Без номера — по названию, чтобы не потерялись."""
    found: dict = {}
    for chapter in chapters:
        key = chapter.number if chapter.number is not None else chapter.title
        found.setdefault(key, chapter)
    return found


def _read(targets, progress) -> tuple[dict, list[str]]:
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)
    return _by_number(chapters), [f.as_text() for f in report.failures]


def _order(key):
    """Номера по порядку, безымянные — после них, по алфавиту."""
    return (not isinstance(key, int), key if isinstance(key, int) else str(key))


def _label(chapter, key) -> str:
    if chapter is not None and chapter.label:
        return chapter.label
    if chapter is not None and chapter.title:
        return chapter.title
    return str(key)


def compare(left, right, progress: Progress | None = None) -> Verdict:
    """Сравнивает две папки с одной и той же книгой."""
    here, bad_here = _read(left, progress)
    there, bad_there = _read(right, progress)

    verdict = Verdict(left_name=where(left), right_name=where(right),
                      left_total=len(here), right_total=len(there),
                      unreadable=bad_here + bad_there)

    for key in sorted(set(here) | set(there), key=_order):
        if progress:
            progress.check()
        one, two = here.get(key), there.get(key)
        name = _label(one or two, key)

        if two is None:
            verdict.findings.append(Finding("only_left", name, len(one.text), 0))
            continue
        if one is None:
            verdict.findings.append(Finding("only_right", name, 0, len(two.text)))
            continue

        verdict.matched += 1
        a, b = len(one.text.strip()), len(two.text.strip())

        # Пустая сторона — не «короче на столько-то», а отсутствие главы.
        # Свалить их в одну находку значило бы утопить беду в мелочи.
        if a < MIN_CHARS and b >= MIN_CHARS:
            verdict.findings.append(Finding("empty_left", name, a, b))
            continue
        if b < MIN_CHARS and a >= MIN_CHARS:
            verdict.findings.append(Finding("empty_right", name, a, b))
            continue
        if not a or not b:
            continue

        if a < b * SHORT:
            verdict.findings.append(Finding("shorter_left", name, a, b))
        elif b < a * SHORT:
            verdict.findings.append(Finding("shorter_right", name, a, b))

    verdict.findings.sort(key=lambda f: (list(KINDS).index(f.kind), f.chapter))
    return verdict


def where(targets) -> str:
    """Имя папки для подписи стороны в отчёте."""
    if isinstance(targets, (str, Path)):
        targets = [targets]
    first = Path(str(targets[0])).expanduser() if targets else None
    return first.name if first else ""
