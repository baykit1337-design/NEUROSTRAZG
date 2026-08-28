"""Осмотр скачанной папки: можно ли эту книгу выкладывать.

Дыры в нумерации, пустые файлы, обрывки и повторы программа умеет
находить и по отдельности — но каждая проверка живёт в своей вкладке и
включается своей галочкой. Через полгода после скачивания книгу на
тысячу глав никто так проверять не станет, и пропущенная глава
обнаружится уже после выкладки.

Здесь одна кнопка на всё. Ничего не чинит и ничего не трогает на диске:
только показывает, куда смотреть.

Соседняя проверка нумерации живёт в `mvl/integrity.py` и смотрит на имена
файлов, не читая их. Здесь наоборот: файлы всё равно читаются ради
пустых глав и обрывков, поэтому номер берётся из главы — и книга,
лежащая одним файлом, проверяется наравне с папкой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from core.models import OpReport

from .base import Progress, collect_files, read_all

#: Подписи находок. Список закрытый: интерфейс берёт названия отсюда, а не
#: держит их вторым экземпляром в разметке.
KINDS = {
    "missing": "Пропущенные главы",
    "doubles": "Один номер у двух глав",
    "parts": "Пропущенные части",
    "stray": "Номер вне диапазона",
    "nameless": "Глава без номера",
    "unreadable": "Файл не прочитался",
    "empty": "Пустая глава",
    "short": "Подозрительно короткая глава",
    "cut": "Обрывается на полуслове",
    "same": "Одинаковый текст",
}

#: Находки, с которыми книгу выкладывать нельзя: главы либо нет, либо она
#: пустая. Остальное — повод посмотреть глазами, а не приговор.
HOLES = frozenset({"missing", "doubles", "parts", "empty", "unreadable"})

#: Разрыв между соседними номерами, после которого хвост считается
#: выбросом. Без этого одна глава 999 среди 201–365 превращает список
#: пропусков в шестьсот номеров.
STRAY_GAP = 20

#: Глава короче этой доли от медианы — подозрение на обрывок.
SHORT_SHARE = 0.25

#: Меньше этого числа глав — медиана ничего не значит, и проверка на
#: короткие главы отключается: в книге из трёх глав любая может быть
#: вчетверо короче другой просто так.
ENOUGH = 5

#: Чем кончается дописанная глава. Знаки конца предложения, закрывающие
#: кавычки и скобки, звёздочки разделителя сцен и китайская пунктуация —
#: слив обрывается посреди слова, и хвост выглядит совсем иначе.
ENDINGS = ".!?…»\"'”’)]*~—。！？」』"

#: Больше этого числа примеров в одной находке не показываем: чинить их
#: всё равно по одной, а список во весь экран ничего не добавляет.
SHOW = 20


@dataclass
class Trouble:
    """Одна находка: чего рода, где и в чём именно."""

    kind: str
    where: list[str] = field(default_factory=list)
    detail: str = ""
    count: int = 0

    @property
    def kind_name(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def hole(self) -> bool:
        """Дыра в книге, а не повод присмотреться."""
        return self.kind in HOLES

    @property
    def size(self) -> int:
        """Сколько всего такого нашлось.

        Не совпадает с длиной `where`: пропуски сворачиваются в диапазоны,
        и «1170–1175» — одна строка, но шесть потерянных глав.
        """
        return self.count or len(self.where)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "kind_name": self.kind_name,
            "hole": self.hole,
            "where": self.where[:SHOW],
            "more": max(0, len(self.where) - SHOW),
            "detail": self.detail,
            "count": self.size,
        }


@dataclass
class Look:
    """Итог осмотра."""

    files: int = 0
    chapters: int = 0
    first: int | None = None
    last: int | None = None
    troubles: list[Trouble] = field(default_factory=list)

    @property
    def holes(self) -> int:
        return sum(1 for trouble in self.troubles if trouble.hole)

    @property
    def clean(self) -> bool:
        return not self.troubles

    def summary(self) -> str:
        """Строка вида «Глав: 812 (1–812) · пропущенные главы: 3».

        Дыры называются поимённо — с них начинают. Остальное сворачивается
        в один счётчик: подробности всё равно ниже, в списке находок, а
        строка из семи пунктов не читается.
        """
        head = f"Глав: {self.chapters}"
        if self.first is not None and self.last is not None:
            head += f" ({self.first}–{self.last})"
        parts = [head]
        for trouble in self.troubles:
            if trouble.hole:
                parts.append(f"{trouble.kind_name.lower()}: {trouble.size}")
        watch = sum(t.size for t in self.troubles if not t.hole)
        if watch:
            parts.append(f"присмотреться: {watch}")
        if len(parts) == 1:
            parts.append("всё на месте")
        return " · ".join(parts)

    def as_dict(self) -> dict:
        return {
            "files": self.files,
            "chapters": self.chapters,
            "first": self.first,
            "last": self.last,
            "clean": self.clean,
            "holes": self.holes,
            "summary": self.summary(),
            "troubles": [t.as_dict() for t in self.troubles],
        }


def _where(chapter) -> str:
    """Как назвать главу в отчёте: имя файла, а без него — номер."""
    if chapter.source:
        return Path(chapter.source).name
    return chapter.label or chapter.title or "без имени"


def _ranges(numbers: list[int]) -> list[str]:
    """Подряд идущие номера — одной строкой «1170–1175»."""
    spans: list[str] = []
    for number in sorted(numbers):
        if spans and number == _last_of(spans[-1]) + 1:
            spans[-1] = f"{_first_of(spans[-1])}–{number}"
        else:
            spans.append(str(number))
    return spans


def _first_of(span: str) -> int:
    return int(span.split("–")[0])


def _last_of(span: str) -> int:
    return int(span.split("–")[-1])


def _without_strays(numbers: list[int]) -> tuple[list[int], list[int]]:
    """Делит отсортированные номера на основной ряд и выбросы по краям.

    Ряд ищется самый длинный: книга бывает и с прологом под номером 0, и с
    экстрами под номером 9001, и с тем и другим сразу.
    """
    if not numbers:
        return [], []

    runs: list[list[int]] = [[numbers[0]]]
    for number in numbers[1:]:
        if number - runs[-1][-1] > STRAY_GAP:
            runs.append([])
        runs[-1].append(number)

    best = max(runs, key=len)
    strays = [n for run in runs if run is not best for n in run]
    return best, strays


def _numbering(chapters, look: Look) -> None:
    """Пропуски, повторы номеров, пропущенные части и главы без номера."""
    by_number: dict[int, list[str]] = {}
    by_part: dict[int, set[int]] = {}
    nameless: list[str] = []

    for chapter in chapters:
        where = _where(chapter)
        if chapter.number is None:
            nameless.append(where)
            continue
        if chapter.part is None:
            by_number.setdefault(chapter.number, []).append(where)
        else:
            by_part.setdefault(chapter.number, set()).add(chapter.part)
            # Глава, разрезанная на части, присутствует целиком.
            by_number.setdefault(chapter.number, [])

    if nameless:
        look.troubles.append(Trouble("nameless", nameless))

    numbers = sorted(by_number)
    if not numbers:
        return

    # Выбросы отделяем ПЕРВЫМИ: иначе они раздувают список пропусков.
    core, strays = _without_strays(numbers)
    look.first, look.last = core[0], core[-1]
    if strays:
        look.troubles.append(Trouble(
            "stray", _ranges(strays), count=len(strays)))

    present = set(core)
    missing = [n for n in range(core[0], core[-1] + 1) if n not in present]
    if missing:
        look.troubles.append(Trouble(
            "missing", _ranges(missing), count=len(missing)))

    doubles = [n for n in numbers if len(by_number[n]) > 1]
    if doubles:
        look.troubles.append(Trouble(
            "doubles",
            [f"{n}: {', '.join(sorted(by_number[n]))}" for n in doubles],
            count=len(doubles)))

    gaps: list[str] = []
    for number, parts in sorted(by_part.items()):
        gaps.extend(f"{number}.{p}" for p in range(1, max(parts) + 1)
                    if p not in parts)
    if gaps:
        look.troubles.append(Trouble("parts", gaps, count=len(gaps)))


def _bodies(chapters, look: Look) -> None:
    """Пустые главы, обрывки и подозрительно короткие."""
    empty: list[str] = []
    cut: list[str] = []
    sizes: list[tuple[int, str]] = []

    for chapter in chapters:
        where = _where(chapter)
        text = chapter.text.strip()
        if not text:
            empty.append(where)
            continue
        sizes.append((len(text), where))
        if text[-1] not in ENDINGS:
            cut.append(where)

    if empty:
        look.troubles.append(Trouble("empty", empty))
    if cut:
        look.troubles.append(Trouble("cut", cut))

    if len(sizes) < ENOUGH:
        return
    middle = median(size for size, _ in sizes)
    limit = middle * SHORT_SHARE
    short = [(size, where) for size, where in sizes if size < limit]
    if short:
        look.troubles.append(Trouble(
            "short",
            [f"{where} — {size} знаков" for size, where in sorted(short)],
            detail=f"обычная глава здесь около {int(middle)} знаков",
            count=len(short)))


def _repeats(chapters, look: Look) -> None:
    """Две главы с одинаковым текстом.

    Поиск живёт в `mvl/integrity`: он там написан, обвешан тестами и
    считается быстро. Ввозить его копию в `ops/` значило бы однажды
    чинить дубли в двух местах — а слой выше по зависимости, поэтому
    берём его отложенно, как это уже делает `ops/split`.
    """
    from mvl.integrity import find_duplicates

    texts: dict[str, str] = {}
    for index, chapter in enumerate(chapters):
        # Имя файла у книги, лежащей одним файлом, общее на все главы, а
        # ключ должен быть свой у каждой: иначе главы затрут друг друга и
        # искать повторы будет не в чем.
        where = _where(chapter)
        label = f"{chapter.label} ({where})" if chapter.label else where
        if label in texts:
            label = f"{label} #{index}"
        texts[label] = chapter.text

    pairs = find_duplicates(texts)
    if not pairs:
        return

    # Считаем главы, а не пары. Сайт, отдавший одну заглушку вместо сотни
    # глав, даёт пять тысяч пар — число, которое ничего не значит и пугает
    # больше самой беды. «Одинаковый текст: 100 глав» — значит.
    involved = {name for pair in pairs for name in (pair.left, pair.right)}
    look.troubles.append(Trouble(
        "same",
        [f"{p.left} ↔ {p.right}: совпадение {round(p.ratio * 100)}%"
         for p in pairs],
        count=len(involved)))


def look(targets, progress: Progress | None = None) -> Look:
    """Осматривает выбранную папку или книгу и рассказывает, что не так."""
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)

    result = Look(files=len(files), chapters=len(chapters))
    if report.failures:
        result.troubles.append(Trouble(
            "unreadable", [f.as_text() for f in report.failures],
            count=len(report.failures)))

    if progress:
        progress.check()
        progress.step(len(files), len(files), "Смотрим нумерацию")
    _numbering(chapters, result)

    if progress:
        progress.check()
        progress.step(len(files), len(files), "Смотрим текст глав")
    _bodies(chapters, result)

    if progress:
        progress.check()
        progress.step(len(files), len(files), "Ищем повторы")
    _repeats(chapters, result)

    # Дыры вперёд: с них начинают, а «присмотреться» подождёт.
    result.troubles.sort(key=lambda t: (not t.hole, list(KINDS).index(t.kind)))
    return result
