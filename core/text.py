"""ЕДИНАЯ обработка текста — одна на весь проект.

Убрать дубль названия, выровнять, схлопнуть разделители, выкинуть пустые
абзацы — всё здесь. Ни одна вкладка не обрабатывает абзацы сама: операции
вызывают `prepare()` и получают готовые блоки.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

#: Абзац-разделитель сцен: только звёздочки, точки или тире в любом числе.
SCENE_CHARS = "*＊※·•—–-_"
SCENE_BREAK = re.compile(rf"^[\s{re.escape(SCENE_CHARS)}]*[{re.escape(SCENE_CHARS)}][\s{re.escape(SCENE_CHARS)}]*$")

#: Игровые уведомления новеллы: {Обнаружен Потенциал} и [Получено достижение].
#: Это часть текста, удалять нельзя — только выровнять как обычный абзац.
SYSTEM_MESSAGE = re.compile(r"^\s*[\{\[].+[\}\]]\s*$", re.S)

#: Приставка вида «Глава 209.» перед названием — при сравнении не учитывается.
TITLE_PREFIX = re.compile(
    r"^\s*(?:глава|глaва|chapter|часть|part)\s*\d+(?:[.,]\d+)?\s*[.:\-–—]?\s*",
    re.I,
)

#: Сколько первых абзацев проверять на дубль названия.
TITLE_LOOKAHEAD = 3

# Виды разделителя сцен на выходе.
SCENE_STARS = "stars"
SCENE_BLANK = "blank"
SCENE_DASHES = "dashes"
SCENE_KEEP = "keep"
SCENE_STYLES = (SCENE_STARS, SCENE_BLANK, SCENE_DASHES, SCENE_KEEP)
SCENE_TEXT = {SCENE_STARS: "* * *", SCENE_DASHES: "— — —"}

ALIGN_LEFT = "left"
ALIGN_CENTER = "center"
ALIGN_JUSTIFY = "justify"
ALIGNMENTS = (ALIGN_LEFT, ALIGN_CENTER, ALIGN_JUSTIFY)

# Типы блоков на выходе.
KIND_TEXT = "text"
KIND_SCENE = "scene"
KIND_SYSTEM = "system"


@dataclass
class Block:
    """Абзац с пометкой, что это — обычный текст, разделитель или уведомление."""

    text: str
    kind: str = KIND_TEXT


@dataclass
class PrepOptions:
    """Настройки подготовки. Значения по умолчанию — из ТЗ v4."""

    strip_title: bool = True
    align: str = ALIGN_LEFT
    first_line_indent_cm: float = 0.0
    scene_style: str = SCENE_STARS
    drop_empty: bool = True
    italic_system: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> PrepOptions:
        data = data or {}
        align = str(data.get("align") or cls.align)
        scene = str(data.get("scene_style") or cls.scene_style)
        return cls(
            strip_title=bool(data.get("strip_title", cls.strip_title)),
            align=align if align in ALIGNMENTS else cls.align,
            first_line_indent_cm=_positive(
                data.get("first_line_indent_cm"), cls.first_line_indent_cm
            ),
            scene_style=scene if scene in SCENE_STYLES else cls.scene_style,
            drop_empty=bool(data.get("drop_empty", cls.drop_empty)),
            italic_system=bool(data.get("italic_system", cls.italic_system)),
        )


def _positive(value, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number >= 0 else fallback


def normalize_title(text: str) -> str:
    """Приводит строку к виду, пригодному для сравнения с названием главы.

    Без регистра, без лишних пробелов, без знаков по краям и без приставки
    «Глава 209.» — иначе дубль в тексте не опознаётся.
    """
    text = unicodedata.normalize("NFKC", text or "").strip()
    text = TITLE_PREFIX.sub("", text)
    text = re.sub(r"\s+", " ", text)
    # Знаки препинания по краям: «Название?» и «Название» — одно и то же.
    # Скобки не трогаем: в названиях бывает «(1)», и обрезка сделала бы из
    # «паука (1)» несимметричное «паука (1».
    text = text.strip(" \t.,:;!?«»\"'-–—*")
    return text.casefold()


#: Сколько первых строк файла считаем зоной шапки. Дальше идёт текст.
HEAD_LINES = 5

#: Доля файлов, в которых строка должна встретиться, чтобы считаться
#: шапкой. Название книги стоит почти в каждом файле, содержание — нет.
HEAD_SHARE = 0.8

#: Меньше этого числа файлов сравнивать бессмысленно: в одном файле любая
#: строка встречается «во всех ста процентах файлов», и в находки попадает
#: текст главы. Для одного файла работает поиск внутри него.
HEAD_MIN_FILES = 3

#: Шапка — это название книги или главы, то есть строка короткая. Абзац на
#: три экрана шапкой не бывает, даже если повторился во всех файлах.
HEAD_MAX = 120

#: Разделители и скобки, которые при сверке шапок не значат ничего.
#: «Chapter 243_ Finding the Culprit (Bonus)» и «Chapter 243: Finding the
#: Culprit (Bonus)» — одна и та же строка, набранная по-разному.
LOOSE_NOISE = re.compile(r"[_:.,;!?()\[\]{}«»\"'—–\-]+")

#: Что это за находка: строка повторяется по всей папке или дублирует
#: название главы из имени файла.
HEAD_REPEAT = "repeat"
HEAD_TITLE = "title"

#: Находки внутри одного файла (3.3 ТЗ).
HEAD_DOUBLE = "double"        #: сдвоенный заголовок главы
HEAD_NEIGHBOUR = "neighbour"  #: шапка вплотную к заголовку главы
HEAD_MANUAL = "manual"        #: своё выражение
HEAD_POSITION = "position"    #: N-я строка после каждого заголовка

#: Сколько раз строка должна встретиться внутри файла, чтобы считаться
#: шапкой. Порог настраиваемый: у книги на сорок глав своя арифметика.
INSIDE_REPEAT = 20

#: Либо — чаще, чем в трети глав. Название книги стоит перед каждой, а
#: реплика «— Что?» на тысячу глав столько раз не наберёт.
INSIDE_SHARE = 1 / 3

#: Слова, по которым строка опознаётся как заголовок главы.
HEADING_WORDS = ("глава", "глaва", "chapter", "часть", "part", "том", "book")

#: Китайская нумерация: 第 241 章.
HEADING_CJK = re.compile(r"第\s*\d+\s*[章回节話话]")

#: Сколько строк файла показывать, когда правила ничего не нашли.
HEAD_PEEK = 10

#: Сколько строк давать на полностью ручной разбор.
HEAD_MANUAL_LINES = 30


def normalize_loose(text: str) -> str:
    """Грубая нормализация для сверки шапок.

    `normalize_title` бережёт скобки: в названии бывает «(1)», и обрезка
    сделала бы из «паука (1)» несимметричное «паука (1». Здесь наоборот —
    сравниваем строки, набранные с разными разделителями, поэтому все
    знаки убираем.
    """
    text = unicodedata.normalize("NFKC", text or "").strip().casefold()
    text = LOOSE_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class HeaderFinding:
    """Строка, похожая на шапку, и в скольких файлах она встретилась."""

    text: str
    count: int
    total: int
    kind: str = HEAD_REPEAT
    #: Файлы, где строка встретилась. Нужны, чтобы её можно было открыть
    #: и посмотреть, о чём речь, до удаления.
    files: list = field(default_factory=list)
    #: Находка внутри одного файла считается не файлами, а вхождениями.
    inside: bool = False
    #: Номера строк — для предпросмотра ручного правила («в каких местах»).
    at: list = field(default_factory=list)
    #: Значение правила: номер строки после заголовка или само выражение.
    value: str = ""
    #: Пример найденного: строки как они лежат в файле, с пометкой, какие
    #: из них удалятся (4.3 ТЗ). Одного названия правила мало — по нему
    #: не видно, что именно программа собирается выкинуть.
    example: list = field(default_factory=list)

    @property
    def share(self) -> float:
        return self.count / self.total if self.total else 0.0

    @property
    def label(self) -> str:
        if not self.inside:
            if self.kind == HEAD_TITLE:
                return f"Дубль названия главы: в {self.count} файлах из {self.total}"
            return f"Найдено в {self.count} файлах из {self.total}"

        # Внутри файла считать файлы бессмысленно: он один.
        times = _times(self.count)
        if self.kind == HEAD_DOUBLE:
            return f"найдено {times}"
        if self.kind == HEAD_POSITION:
            return f"строка после заголовка, найдено {times}"
        if self.kind == HEAD_MANUAL:
            return f"своё выражение, совпадений {self.count}"
        if self.kind == HEAD_NEIGHBOUR:
            return f"рядом с заголовком главы, встречается {times}"
        return f"встречается {times}"

    def as_dict(self) -> dict:
        return {"text": self.text, "count": self.count, "total": self.total,
                "kind": self.kind, "label": self.label, "inside": self.inside,
                "value": self.value,
                # Первые места — чтобы можно было посмотреть, о чём речь,
                # не пролистывая тысячу строк.
                "at": list(self.at[:20]),
                "example": list(self.example),
                # Показываем несколько: открывается первый, остальные —
                # чтобы было видно, что находка не единичная.
                "files": list(self.files[:20])}


def _times(count: int) -> str:
    """«1004 раза», «1001 раз», «1005 раз» — по-русски."""
    tail, hundred = count % 10, count % 100
    if tail == 1 and hundred != 11:
        word = "раз"
    elif tail in (2, 3, 4) and hundred not in (12, 13, 14):
        word = "раза"
    else:
        word = "раз"
    return f"{count} {word}"


def find_headers(samples) -> list[HeaderFinding]:
    """Ищет мусорную шапку по началу файлов.

    `samples` — тройки «название главы, первые абзацы, файл» либо пары без
    файла. Жёстких правил нет: строка, встретившаяся почти во всех файлах,
    содержанием быть не может, поэтому название книги вычисляется само.
    """
    prepared = []
    for sample in samples:
        title, lines, *rest = sample
        prepared.append((title, list(lines), str(rest[0]) if rest else ""))
    samples = prepared
    total = len(samples)
    # Одна-две главы — не выборка: доля «встретилась почти везде» на них
    # равна единице для любой строки, включая текст главы.
    if total < HEAD_MIN_FILES:
        return []

    seen: dict[str, tuple[str, int]] = {}
    where: dict[str, list] = {}
    title_files: list = []
    #: Как выглядит продублированное название в тексте. Своей строки у
    #: этой находки нет — она у каждого файла своя, — но показать хоть
    #: один пример надо: иначе непонятно, что удалится (4.3 ТЗ).
    title_example = ""
    duplicates = 0

    for title, lines, source in samples:
        head = [line.strip() for line in lines[:HEAD_LINES] if line.strip()]
        # Один и тот же файл не должен считаться дважды за одну строку.
        counted: set[str] = set()
        title_hit = False

        for line in head:
            if _is_title_echo(line, title):
                title_hit = True
                if not title_example:
                    title_example = line
                continue
            if len(line) > HEAD_MAX:
                continue
            key = normalize_loose(line)
            if not key or key in counted:
                continue
            counted.add(key)
            text, count = seen.get(key, (line, 0))
            seen[key] = (text, count + 1)
            if source:
                where.setdefault(key, []).append(source)

        if title_hit:
            duplicates += 1
            if source:
                title_files.append(source)

    findings = [
        HeaderFinding(text=text, count=count, total=total,
                      files=where.get(key, []),
                      example=[{"text": text, "removed": True}])
        for key, (text, count) in seen.items()
        if count / total > HEAD_SHARE
    ]
    if duplicates:
        findings.append(HeaderFinding(
            text="", count=duplicates, total=total, kind=HEAD_TITLE,
            files=title_files,
            example=([{"text": title_example, "removed": True}]
                     if title_example else [])))

    findings.sort(key=lambda f: (-f.count, f.text))
    return findings


def looks_like_heading(line: str, title: str = "") -> bool:
    """Похожа ли строка на заголовок главы (3.3 ТЗ).

    Признак нарочно грубый: строка короткая, в ней есть число и слово из
    списка — либо она совпадает с названием из имени файла. Точнее здесь
    и не нужно: правило только отличает заголовок от названия книги,
    стоящего с ним рядом.
    """
    line = (line or "").strip()
    if not line or len(line) > HEAD_MAX:
        return False
    if HEADING_CJK.search(line):
        return True
    low = line.casefold()
    if any(word in low for word in HEADING_WORDS) and re.search(r"\d", line):
        return True
    return bool(title) and normalize_loose(line) == normalize_loose(title)


def _clean_lines(lines) -> list[str]:
    return [str(line or "") for line in lines]


#: Сколько строк показывать вокруг найденной — чтобы был контекст.
AROUND = 1


def _around(lines: list[str], number: int, span: int = AROUND) -> list[dict]:
    """Найденная строка с соседями и пометкой, что именно удалится.

    Само название правила ничего не говорит: по «Сдвоенный заголовок» не
    видно, что программа собирается выкинуть. Показываем кусок файла как
    он есть (4.3 ТЗ).
    """
    index = number - 1
    if not 0 <= index < len(lines):
        return []
    first = max(0, index - span)
    last = min(len(lines), index + span + 1)
    return [{"text": lines[n], "removed": n == index}
            for n in range(first, last) if lines[n].strip()]


def find_repeats_inside(lines, repeat: int = INSIDE_REPEAT,
                        chapters: int = 0, title: str = "") -> list[HeaderFinding]:
    """Правило первое: строка, повторяющаяся внутри файла.

    Считаем каждую строку по всему файлу. Встретилась больше порога (либо
    чаще, чем в трети глав) — это шапка, а не содержание: название книги
    вычисляется само, вписывать его руками не нужно.

    Заголовки глав из счёта исключены. Заголовок — это ровно то, что
    правила обязаны оставить, и предлагать его к удалению нельзя, как бы
    часто он ни повторялся. Плата за это — название книги, само похожее
    на заголовок («Книга 2»), правилом не найдётся: для него есть ручное.
    """
    lines = _clean_lines(lines)
    counts: dict[str, int] = {}
    shown: dict[str, str] = {}
    at: dict[str, list] = {}

    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or len(stripped) > HEAD_MAX:
            continue
        if looks_like_heading(stripped, title):
            continue
        key = normalize_loose(stripped)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        shown.setdefault(key, stripped)
        at.setdefault(key, []).append(number)

    # Порог по числу глав работает там, где глав мало: на сорока главах
    # двадцати повторов не наберётся, а шапка всё равно шапка.
    by_share = int(chapters * INSIDE_SHARE) if chapters else 0
    limit = min(repeat, by_share) if by_share else repeat

    found = [
        HeaderFinding(text=shown[key], count=count, total=len(lines),
                      kind=HEAD_REPEAT, inside=True, at=at[key],
                      example=_around(lines, at[key][0]))
        for key, count in counts.items()
        if count > limit
    ]
    found.sort(key=lambda f: (-f.count, f.text))
    return found


def find_doubles_inside(lines, title: str = "") -> HeaderFinding | None:
    """Правило второе: сдвоенный заголовок главы.

    Ищем тройки строк подряд, где первая и третья — одно и то же после
    грубой нормализации, а между ними ровно одна строка. Так ловится
    «Chapter 241_ …» / название книги / «Chapter 241: …».

    Отдаём один пункт с числом, а не тысячу пунктов: список на тысячу
    строк прочитать нельзя.
    """
    lines = _clean_lines(lines)
    spots = list(_double_spots(lines))
    if not spots:
        return None

    # Один пример на всю находку: тысяча одинаковых троек на экране
    # бесполезна, а по одной сразу видно, что именно уйдёт (4.3 ТЗ).
    _, (first, middle, third) = spots[0]
    example = [
        {"text": first, "removed": False},
        {"text": middle, "removed": True},
        {"text": third, "removed": True},
    ]
    return HeaderFinding(text="Сдвоенный заголовок главы", count=len(spots),
                         total=len(lines), kind=HEAD_DOUBLE, inside=True,
                         at=[number for number, _ in spots], example=example)


def _double_spots(lines: list[str]):
    """Места сдвоенных заголовков: пары «номер первой строки, сама тройка».

    Считаем только непустые строки: между заголовком и его повтором
    пустых строк не бывает, а вот отступы вокруг тройки бывают всякие.
    """
    for index in range(len(lines) - 2):
        first, middle, third = lines[index], lines[index + 1], lines[index + 2]
        if not first.strip() or not middle.strip() or not third.strip():
            continue
        head = normalize_loose(first)
        if not head or len(first.strip()) > HEAD_MAX:
            continue
        if head != normalize_loose(third):
            continue
        yield index + 1, (first, middle, third)


def find_neighbours_inside(lines, repeats, title: str = "") -> list[HeaderFinding]:
    """Правило третье: одиночный заголовок с названием книги рядом.

    Строка, опознанная первым правилом как шапка, стоит вплотную (через
    пустую строку или без неё) к строке, похожей на заголовок главы.
    Удалять при этом надо только шапку — заголовок остаётся.
    """
    lines = _clean_lines(lines)
    found = []
    for repeat in repeats:
        spots = [number for number in repeat.at
                 if _next_to_heading(lines, number, title)]
        # Соседство должно быть правилом, а не совпадением в паре мест:
        # иначе в список попадёт любая часто повторяющаяся реплика.
        if len(spots) * 2 < repeat.count:
            continue
        found.append(HeaderFinding(text=repeat.text, count=len(spots),
                                   total=len(lines), kind=HEAD_NEIGHBOUR,
                                   inside=True, at=spots,
                                   example=_around(lines, spots[0])))
    return found


def _next_to_heading(lines: list[str], number: int, title: str) -> bool:
    """Есть ли заголовок главы вплотную к строке с этим номером."""
    index = number - 1
    for step in (-2, -1, 1, 2):
        near = index + step
        if not 0 <= near < len(lines):
            continue
        # Через пустую строку — тоже «вплотную»: пустая строка не текст.
        if abs(step) == 2 and lines[index + step // 2].strip():
            continue
        if looks_like_heading(lines[near], title):
            return True
    return False


def find_by_pattern(lines, pattern: str) -> HeaderFinding | None:
    """Ручное правило: своё выражение с предпросмотром (3.4 ТЗ).

    Выражение сначала пробуем как обычный текст: большинству нужно именно
    это, а regexp с непонятной ошибкой отпугивает.
    """
    pattern = (pattern or "").strip()
    if not pattern:
        return None
    lines = _clean_lines(lines)

    try:
        rule = re.compile(pattern, re.I)
    except re.error as exc:
        raise ValueError(f"Выражение не разобрать: {exc}") from exc

    at = [number for number, line in enumerate(lines, 1)
          if line.strip() and rule.search(line)]
    if not at:
        return None
    return HeaderFinding(text=pattern, count=len(at), total=len(lines),
                         kind=HEAD_MANUAL, inside=True, at=at, value=pattern,
                         example=_around(lines, at[0]))


def find_by_position(lines, offset: int, title: str = "") -> HeaderFinding | None:
    """Правило по позиции: N-я строка после каждого заголовка главы.

    Нужно там, где мусор не повторяется дословно — в нём номер главы или
    дата, и первое правило его не поймает.
    """
    offset = int(offset or 0)
    if offset < 1:
        return None
    lines = _clean_lines(lines)

    at = []
    for index, line in enumerate(lines):
        if not looks_like_heading(line, title):
            continue
        target = index + offset
        if target < len(lines) and lines[target].strip():
            at.append(target + 1)
    if not at:
        return None
    return HeaderFinding(text=f"{offset}-я строка после заголовка",
                         count=len(at), total=len(lines), kind=HEAD_POSITION,
                         inside=True, at=at, value=str(offset),
                         example=_around(lines, at[0]))


def find_headers_inside(lines, title: str = "", repeat: int = INSIDE_REPEAT,
                        chapters: int = 0, pattern: str = "",
                        offset: int = 0) -> list[HeaderFinding]:
    """Все правила разом. Порядок — как в ТЗ: повтор, дубль, сосед.

    Книга одним файлом на тысячу глав — обычное дело, и сравнивать её
    не с чем: находка ищется внутри самого файла.
    """
    lines = _clean_lines(lines)
    repeats = find_repeats_inside(lines, repeat=repeat, chapters=chapters,
                                  title=title)
    found: list[HeaderFinding] = list(repeats)

    double = find_doubles_inside(lines, title)
    if double is not None:
        found.append(double)

    # Соседство добавляем только там, где первое правило само не сработало:
    # иначе одна и та же строка попадёт в список дважды.
    seen = {normalize_loose(f.text) for f in repeats}
    for neighbour in find_neighbours_inside(lines, repeats, title):
        if normalize_loose(neighbour.text) not in seen:
            found.append(neighbour)

    manual = find_by_pattern(lines, pattern)
    if manual is not None:
        found.append(manual)

    positional = find_by_position(lines, offset, title)
    if positional is not None:
        found.append(positional)

    return found


def peek(lines, count: int = HEAD_PEEK) -> list[dict]:
    """Первые строки файла с нумерацией.

    Показываются, когда правила ничего не нашли: «ничего не найдено» —
    не ответ, а вот первые строки сразу подсказывают, что здесь лишнее.
    """
    lines = _clean_lines(lines)
    return [{"number": number, "text": line}
            for number, line in enumerate(lines[:count], 1)]


def strip_headers_inside(lines, rules) -> list[str]:
    """Убирает шапку внутри одного файла по отмеченным правилам.

    `rules` — то, что вернул поиск: словари с `kind` и `text`. Строки
    сначала помечаются на удаление и только потом выкидываются: правила
    смотрят на исходную нумерацию и мешать друг другу не должны.
    """
    lines = _clean_lines(lines)
    drop: set[int] = set()

    texts = set()
    patterns = []
    offsets = []
    doubles = False

    for rule in rules or []:
        if isinstance(rule, str):
            kind, value, body = HEAD_REPEAT, "", rule
        else:
            kind = str(rule.get("kind") or HEAD_REPEAT)
            body = str(rule.get("text") or "")
            value = str(rule.get("value") or "")

        if kind == HEAD_DOUBLE:
            doubles = True
        elif kind == HEAD_MANUAL:
            patterns.append(value or body)
        elif kind == HEAD_POSITION:
            offsets.append(value or body)
        elif body.strip():
            texts.add(normalize_loose(body))

    if doubles:
        # `number` — номер первой строки тройки, считая с единицы, то есть
        # её же индекс плюс один. Значит, это индекс средней строки.
        for number, _ in _double_spots(lines):
            drop.add(number)      # название книги между заголовками
            drop.add(number + 1)  # повтор заголовка

    for pattern in patterns:
        finding = find_by_pattern(lines, pattern)
        if finding is not None:
            drop.update(index - 1 for index in finding.at)

    for offset in offsets:
        digits = re.search(r"\d+", str(offset))
        finding = find_by_position(lines, int(digits.group()) if digits else 0)
        if finding is not None:
            drop.update(index - 1 for index in finding.at)

    if texts:
        for index, line in enumerate(lines):
            if line.strip() and normalize_loose(line) in texts:
                drop.add(index)

    return [line for index, line in enumerate(lines) if index not in drop]


def _is_title_echo(line: str, title: str) -> bool:
    """Строка повторяет название главы из имени файла."""
    from .naming import parse

    wanted = normalize_loose(title)
    if not wanted:
        return False
    if normalize_loose(line) == wanted:
        return True
    # «Chapter 243: Finding the Culprit» против названия без номера.
    return normalize_loose(parse(line).title) == wanted


def strip_headers(paragraphs: list[str], title: str, texts) -> list[str]:
    """Убирает шапку из начала главы.

    Чистим только зону шапки: та же строка дальше по тексту — уже
    содержание, и трогать её нельзя.
    """
    wanted = {normalize_loose(t) for t in texts if str(t).strip()}
    drop_title = any(not str(t).strip() for t in texts)

    result = list(paragraphs)
    kept: list[str] = []
    checked = 0

    for index, line in enumerate(result):
        if checked >= HEAD_LINES:
            kept.extend(result[index:])
            break
        if not line.strip():
            continue
        checked += 1
        if normalize_loose(line) in wanted:
            continue
        if drop_title and _is_title_echo(line, title):
            continue
        kept.append(line)
    return kept


def is_scene_break(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and bool(SCENE_BREAK.match(stripped))


def is_system_message(text: str) -> bool:
    return bool(SYSTEM_MESSAGE.match(text or ""))


def prepare(paragraphs, title: str = "", options: PrepOptions | None = None) -> list[Block]:
    """Готовит абзацы главы к выводу.

    Убирает дубли названия, схлопывает разделители сцен, выбрасывает пустые
    абзацы и помечает игровые уведомления.
    """
    options = options or PrepOptions()
    blocks: list[Block] = []

    # 1. Пустые абзацы: расстояние задаётся интервалом, а не пустыми строками.
    cleaned = [p.strip() for p in paragraphs if not options.drop_empty or p.strip()]
    cleaned = [p for p in cleaned if p]

    # 2. Дубль названия в первых абзацах — удаляем все подряд, не только первый.
    if options.strip_title and title:
        cleaned = strip_leading_title(cleaned, title)

    for paragraph in cleaned:
        if is_scene_break(paragraph):
            if options.scene_style == SCENE_KEEP:
                blocks.append(Block(paragraph, KIND_SCENE))
            elif options.scene_style == SCENE_BLANK:
                blocks.append(Block("", KIND_SCENE))
            else:
                blocks.append(Block(SCENE_TEXT[options.scene_style], KIND_SCENE))
            continue
        kind = KIND_SYSTEM if is_system_message(paragraph) else KIND_TEXT
        blocks.append(Block(paragraph, kind))

    blocks = collapse_scenes(blocks)
    return trim_scenes(blocks)


def strip_leading_title(paragraphs: list[str], title: str) -> list[str]:
    """Убирает название главы из начала текста.

    Проверяются первые несколько абзацев, и удаляются **все** совпадения
    подряд: в исходнике название нередко стоит дважды.
    """
    wanted = normalize_title(title)
    # У главы без собственного имени («Глава 217») приставка — это всё
    # название, и `normalize_title` даёт пустую строку. Сверять тогда надо
    # строку целиком, иначе заголовок остаётся продублированным в тексте.
    whole = normalize_loose(title)
    if not wanted and not whole:
        return paragraphs

    index = 0
    while index < min(TITLE_LOOKAHEAD, len(paragraphs)):
        line = paragraphs[index]
        same = ((wanted and normalize_title(line) == wanted)
                or (whole and normalize_loose(line) == whole))
        if not same:
            break
        index += 1
    return paragraphs[index:]


def collapse_scenes(blocks: list[Block]) -> list[Block]:
    """Идущие подряд разделители схлопывает в один.

    На сайте они идут по несколько `<p>*</p>`, из-за чего в документе
    получалось по две-три звёздочки подряд.
    """
    result: list[Block] = []
    for block in blocks:
        if block.kind == KIND_SCENE and result and result[-1].kind == KIND_SCENE:
            continue
        result.append(block)
    return result


def trim_scenes(blocks: list[Block]) -> list[Block]:
    """Разделитель не должен быть первым или последним абзацем."""
    start, end = 0, len(blocks)
    while start < end and blocks[start].kind == KIND_SCENE:
        start += 1
    while end > start and blocks[end - 1].kind == KIND_SCENE:
        end -= 1
    return blocks[start:end]


def to_text(blocks: list[Block]) -> str:
    """Собирает блоки обратно в плоский текст — для .txt и .md."""
    return "\n\n".join(b.text for b in blocks if b.text)


# ------------------------------------------------- деление на части
#
# Живёт здесь, а не во вкладке «Переименовать», потому что делить
# главу на части просят две работы сразу: переименование файлов и
# сборка книги для загрузчика. Работа чисто текстовая — ни файлов,
# ни имён она не знает.


def split_into_parts(paragraphs: list[str], count: int) -> list[list[str]]:
    """Делит абзацы на `count` частей, максимально равных по числу символов.

    Режем только по границам абзацев. Разделитель сцен (`*`) не должен
    оказаться первым или последним абзацем части — такие границы сдвигаем.
    """
    if count < 2:
        return [list(paragraphs)]
    blocks = [p for p in paragraphs if p.strip()]
    if len(blocks) < count:
        # Абзацев меньше, чем частей — делить нечего.
        return [list(blocks)]

    lengths = [len(p) for p in blocks]
    total = sum(lengths)
    # Накопленная длина после каждого абзаца.
    cumulative: list[int] = []
    running = 0
    for length in lengths:
        running += length
        cumulative.append(running)

    cuts: list[int] = []
    for index in range(1, count):
        ideal = total * index / count
        # Граница — индекс абзаца, после которого режем.
        best = min(range(len(blocks)), key=lambda i: abs(cumulative[i] - ideal))
        cut = best + 1
        # Каждая часть должна быть непустой, границы строго возрастают.
        low = (cuts[-1] + 1) if cuts else 1
        high = len(blocks) - (count - index)
        cuts.append(max(low, min(cut, high)))

    cuts = _avoid_scene_breaks(blocks, cuts)

    parts: list[list[str]] = []
    start = 0
    for cut in [*cuts, len(blocks)]:
        parts.append(blocks[start:cut])
        start = cut
    return [p for p in parts if p]


def _avoid_scene_breaks(blocks: list[str], cuts: list[int]) -> list[int]:
    """Сдвигает границы так, чтобы `*` не открывал и не закрывал часть."""
    adjusted = []
    for index, cut in enumerate(cuts):
        low = (adjusted[-1] + 1) if adjusted else 1
        high = len(blocks) - (len(cuts) - index)
        for candidate in _nearby(cut, low, high):
            ends_with_break = SCENE_BREAK.match(blocks[candidate - 1])
            starts_with_break = SCENE_BREAK.match(blocks[candidate])
            if not ends_with_break and not starts_with_break:
                cut = candidate
                break
        adjusted.append(max(low, min(cut, high)))
    return adjusted


def _nearby(value: int, low: int, high: int):
    """Кандидаты в порядке удаления от исходной границы."""
    if low > high:
        return
    seen = set()
    for shift in range(0, high - low + 2):
        for candidate in (value - shift, value + shift):
            if low <= candidate <= high and candidate not in seen:
                seen.add(candidate)
                yield candidate
