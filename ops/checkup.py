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

import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from core import naming
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
    "thin": "Под номером файлов меньше обычного",
    "tail": "Общий хвост имён",
}

#: Находки, с которыми книгу выкладывать нельзя: главы либо нет, либо она
#: пустая. Остальное — повод посмотреть глазами, а не приговор.
HOLES = frozenset({"missing", "doubles", "parts", "empty", "unreadable",
                   "thin"})

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


# ------------------------------------------- каких глав нет: по именам


"""Проверка нумерации в готовой книге отвечает «под номером 303 глав
меньше, чем у соседей», и дальше человек остаётся один на один с папкой в
несколько сотен файлов. Здесь тот же вопрос задаётся самой папке — и
ответ выходит точный: не «с 303 что-то не так», а «нет 303.1».

Слив в OEBPS размечен не так, как понимает общий разбор имён:

    0002_Chapter_295_The_Anti-Ancient_God_Unified_Alliance.xhtml
    0003_Chapter_295_The_Anti-Ancient_God_Unified_Alliance_2.xhtml

Вторая часть помечена голой цифрой в хвосте, и одному имени тут верить
нельзя: «Level 2» в названии главы выглядит ровно так же.

Отличить помогает вся папка сразу. Если у большинства номеров файлы
складываются в один и тот же ряд — «без хвоста» и «хвост 2», — то хвост в
этой папке и есть номер части. Тогда и одинокий файл
`0069_Chapter_330_We_Are_the_Hope_2` читается однозначно: вторая часть на
месте, первой нет.

Файлы не читаются вовсе — только имена, поэтому проверка идёт мгновенно
даже на тысяче глав."""


#: Номер части в хвосте имени: «…_2», «… 2», «…(2)». Цифра должна быть
#: отделена — «Hope2» частью не является. Голая цифра целым названием
#: («Chapter_330_2») частью является: разделитель перед ней уже снят
#: общим разбором.
TAIL_PART = re.compile(r"(?:^|[\s_.\-–—(\[])\s*(\d{1,3})[)\]]?\s*$")

#: С чего может начинаться общий хвост имён: он режется по границе слова.
TAIL_EDGE = " _-.–—"

#: Со скольких номеров у папки появляется свой ряд частей. Меньше — и «у
#: каждого номера по две части» значит только то, что файлов всего два.
ENOUGH_NUMBERS = 10


@dataclass
class Piece:
    """Один файл: что вышло из его имени."""

    name: str
    number: int | None = None
    #: Номер части, размеченный явно: «295.2», «295. Часть 2».
    part: int | None = None
    #: Голая цифра в хвосте имени. Частью считается не всегда — решает
    #: вся папка сразу.
    tail: int | None = None


def common_tail(stems: list[str]) -> str:
    """Общий хвост всех имён — он ничего не различает и мешает разбору.

    Переводчик дописывает к каждому файлу свою подпись:
    `..._2_translated_gemini`. Номер части перестаёт быть последним, и в
    хвосте его уже не найти. Снять подпись можно, только увидев всю папку:
    одному имени неоткуда знать, что «gemini» — не название главы.

    Кончаться цифрой хвост не должен. У папки, где вторая часть есть у
    каждой главы, общим хвостом окажется сам «_2» — и снять его значило бы
    стереть пометку части со всех файлов разом.
    """
    if len(stems) < 2:
        return ""

    tail = stems[0]
    for stem in stems[1:]:
        while tail and not stem.endswith(tail):
            tail = tail[1:]
        if not tail:
            return ""

    if tail[-1].isdigit():
        return ""

    # Хвост — это целые слова: «_translated_gemini», а не «ranslated_gemini».
    at = next((i for i, ch in enumerate(tail) if ch in TAIL_EDGE), -1)
    tail = tail[at:] if at >= 0 else ""
    if not tail:
        return ""

    # Снять хвост, от которого не остаётся имени, значит остаться ни с чем.
    if any(not stem[:-len(tail)].strip() for stem in stems):
        return ""
    return tail


def pieces_of(files) -> tuple[list[Piece], str]:
    """Имена файлов — в «номер главы, номер части». Файлы не читаются."""
    names = [Path(path).name for path in files]
    stems = [Path(name).stem for name in names]
    tail = common_tail(stems)

    pieces: list[Piece] = []
    for name, stem in zip(names, stems):
        base = stem[:-len(tail)] if tail else stem
        parsed = naming.parse(base)
        mark = None
        if parsed.number is not None and parsed.part is None:
            found = TAIL_PART.search(parsed.title)
            if found:
                mark = int(found.group(1))
        pieces.append(Piece(name, parsed.number, parsed.part, mark))
    return pieces, tail


def _rows(pieces) -> dict[int, list[int]]:
    """Номер главы → номера её частей, как они вышли из имён.

    Часть без пометки считается первой: у главы, лежащей одним файлом,
    номер части не пишут вовсе.
    """
    rows: dict[int, list[int]] = {}
    for piece in pieces:
        if piece.number is None:
            continue
        rows.setdefault(piece.number, []).append(
            piece.part or piece.tail or 1)
    return {number: sorted(parts) for number, parts in rows.items()}


def usual_row(rows) -> tuple:
    """Ряд частей, в который складывается номер в этой папке: (1, 2).

    Пустой кортеж — ряда нет, и назвать пропавшую часть поимённо нельзя:
    либо папка мала, либо номера разнобойны.

    Ряд признаём только явный. Так должно жить большинство номеров, и
    самих номеров должно быть достаточно: две части под одним номером в
    папке из двух файлов — это не ряд, а совпадение. Повтор внутри ряда
    («1, 1») рядом тоже не считается: две части без пометок неразличимы,
    и сказать, какой из них не хватает, всё равно нечего.
    """
    if len(rows) < ENOUGH_NUMBERS:
        return ()

    tally: dict[tuple, int] = {}
    for parts in rows.values():
        row = tuple(parts)
        tally[row] = tally.get(row, 0) + 1

    row = max(tally, key=lambda parts: (tally[parts], -len(parts)))
    if len(row) < 2 or len(set(row)) != len(row):
        return ()
    return row if tally[row] * 2 > len(rows) else ()


def _usual_count(rows) -> int:
    """Сколько файлов приходится на номер, когда ряда частей нет."""
    if len(rows) < ENOUGH_NUMBERS:
        return 1
    tally: dict[int, int] = {}
    for parts in rows.values():
        tally[len(parts)] = tally.get(len(parts), 0) + 1
    usual = max(tally, key=lambda size: (tally[size], -size))
    return usual if tally[usual] * 2 > len(rows) else 1


def _by_names(pieces, look: Look) -> None:
    """Пропущенные номера и части — по одним именам файлов."""
    nameless = [piece.name for piece in pieces if piece.number is None]
    if nameless:
        look.troubles.append(Trouble("nameless", nameless))

    rows = _rows(pieces)
    numbers = sorted(rows)
    if not numbers:
        return

    # Выбросы отделяем ПЕРВЫМИ: иначе одна глава 999 среди 294–582
    # превращает список пропусков в четыреста номеров.
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

    row = usual_row({number: rows[number] for number in core})
    if not row:
        # Ряда нет — назвать пропавшую часть нечем. Остаётся сказать, где
        # файлов меньше, чем у соседей: пропажу в такой папке иначе не
        # видно вовсе, номер-то на месте.
        size = _usual_count({number: rows[number] for number in core})
        thin = [number for number in core if len(rows[number]) < size]
        if thin:
            look.troubles.append(Trouble(
                "thin", _ranges(thin),
                detail=f"обычно их тут {size}", count=len(thin)))
        return

    whole = set(row)
    holes: list[str] = []
    doubles: list[str] = []
    for number in core:
        parts = rows[number]
        for part in sorted(whole - set(parts)):
            holes.append(f"{number}.{part}")
        for part in sorted({p for p in parts if parts.count(p) > 1}):
            doubles.append(f"{number}.{part}")

    listing = ", ".join(str(part) for part in row)
    if holes:
        look.troubles.append(Trouble(
            "parts", holes, detail=f"у главы здесь части {listing}",
            count=len(holes)))
    if doubles:
        look.troubles.append(Trouble("doubles", doubles, count=len(doubles)))


def look_names(targets) -> Look:
    """Каких глав и частей нет в папке — по одним именам файлов.

    Ничего не читает и ничего не трогает: на тысяче глав отвечает сразу.
    """
    files = collect_files(targets)
    pieces, tail = pieces_of(files)

    result = Look(files=len(files),
                  chapters=sum(1 for p in pieces if p.number is not None))
    _by_names(pieces, result)
    if tail:
        # Снятый хвост показываем: если разбор ошибся, видно будет сразу.
        result.troubles.append(Trouble(
            "tail", [tail], detail="одинаковый хвост имён в разборе не"
                                   " участвовал"))

    result.troubles.sort(key=lambda t: (not t.hole, list(KINDS).index(t.kind)))
    return result
