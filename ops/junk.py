"""Мусор в главах готовой книги: повторы, дубли заголовка и артефакты.

Слив кладёт в каждую главу лишнее, и в готовом `.md` это видно только
глазами и только если пролистать всю книгу:

    # [Chapter 241_ Panicking Count Ashton :|: :|: 1 :|: ]
    Summoners War: Only I Summoned Divine Beasts   ← название книги
    Chapter 241: Panicking Count Ashton            ← тот же заголовок
    "Это…" — сказал граф Эштон, дрожа.

Название книги в главе не нужно, а второй заголовок загрузчик прочитает
как начало ещё одной главы. Плюс сюда же попадает всё, что не перевелось:
иероглифы и английские абзацы посреди русского текста.

Для папки с главами то же самое умеет `ops/headers` — там строка,
встретившаяся почти во всех файлах, содержанием быть не может. Здесь
книга лежит одним файлом, и «почти во всех файлах» считать не по чему,
поэтому за главы берутся куски между заголовками загрузчика.

Ничего не удаляет само: показывает находки, а убирает только отмеченные.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from core import naming
from core.text import HEAD_MAX, normalize_loose, normalize_title

#: Подписи находок. Список закрытый: интерфейс берёт названия отсюда.
KINDS = {
    "echo": "Заголовок повторён в тексте",
    "repeat": "Одна строка почти в каждой главе",
    "cjk": "Иероглифы",
    "latin": "Не переведено",
    "symbols": "Посторонние знаки",
}

#: Находки, за которыми стоит настоящая беда загрузчика: второй заголовок
#: он прочитает как начало новой главы, а название книги уедет в текст.
SPOILS = frozenset({"echo", "repeat"})

#: Сколько первых абзацев главы считаем зоной шапки. Дальше идёт текст,
#: и совпадение там — совпадение, а не мусор.
HEAD_LINES = 4

#: В какой доле глав строка должна встретиться, чтобы считаться названием
#: книги. Порог тот же, что у `ops/headers`: там он оправдал себя.
SHARE = 0.8

#: Меньше этого числа глав сравнивать бессмысленно: в одной главе любая
#: строка встречается «во всех ста процентах глав».
ENOUGH = 3

#: И не меньше стольких глав подряд. Пользовательское правило: строка,
#: попавшаяся в десяти главах, — уже не совпадение.
MANY = 10

#: Больше этого числа примеров в одной находке не показываем.
SHOW = 20

#: Заголовок начинается с пометки главы и номера — именно начинается.
#: «…в главе 12 говорилось» тоже содержит и слово, и число, но это
#: обычный текст, и вычёркивать такую строку из книги нельзя.
STARTS = re.compile(rf"^\s*{naming.CHAPTER_WORD}\s*(\d{{1,5}})(?!\d)", re.IGNORECASE)

CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
LATIN = re.compile(r"[A-Za-z]")
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")

#: Знак, который в русском тексте делать нечего. Пунктуация, пробелы,
#: цифры и типографика сюда не попадают: они в тексте законны.
def _odd(char: str) -> bool:
    if char.isspace() or char.isdigit():
        return False
    if CYRILLIC.match(char):
        return False
    kind = unicodedata.category(char)
    # P* — пунктуация, Z* — пробелы, S* — знаки вроде «°» и «—».
    return kind[0] not in ("P", "Z", "S")


@dataclass
class Find:
    """Одна находка: что нашли, где и сколько раз."""

    kind: str
    text: str = ""
    count: int = 0
    where: list[str] = field(default_factory=list)
    sample: str = ""

    @property
    def kind_name(self) -> str:
        return KINDS.get(self.kind, self.kind)

    @property
    def spoils(self) -> bool:
        return self.kind in SPOILS

    @property
    def key(self) -> str:
        """Чем находка называется в запросе на удаление."""
        return f"{self.kind}:{normalize_loose(self.text)}" if self.text else self.kind

    def as_dict(self) -> dict:
        return {"kind": self.kind, "kind_name": self.kind_name, "key": self.key,
                "text": self.text, "count": self.count, "spoils": self.spoils,
                "where": self.where[:SHOW], "sample": self.sample}


@dataclass
class Report:
    chapters: int = 0
    finds: list[Find] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.finds

    def summary(self) -> str:
        if self.clean:
            return f"Глав: {self.chapters} · лишнего не нашлось"
        spoils = sum(f.count for f in self.finds if f.spoils)
        rest = sum(f.count for f in self.finds if not f.spoils)
        parts = [f"Глав: {self.chapters}"]
        if spoils:
            parts.append(f"мешает загрузчику: {spoils}")
        if rest:
            parts.append(f"артефактов: {rest}")
        return " · ".join(parts)

    def as_dict(self) -> dict:
        return {"chapters": self.chapters, "clean": self.clean,
                "summary": self.summary(),
                "total": sum(f.count for f in self.finds),
                "finds": [f.as_dict() for f in self.finds]}


def echoes(line: str, title: str) -> bool:
    """Строка под заголовком повторяет сам заголовок.

    Сравниваем не буквы, а номер с названием: у загрузчика заголовок
    записан «Chapter 241_ Panicking Count Ashton», а в тексте под ним
    стоит то «Глава 241», то «Chapter 241: Panicking Count Ashton». Букв
    общих мало, а глава — одна и та же.
    """
    line, title = (line or "").strip(), (title or "").strip()
    if not line or not title or len(line) > HEAD_MAX:
        return False

    here, there = normalize_title(line), normalize_title(title)
    if here and here == there:
        return True

    if not STARTS.match(line):
        return False
    one, two = naming.parse(line), naming.parse(title)
    if one.number is None or one.number != two.number:
        return False
    # Номер совпал. Либо строка из одного номера и состоит («Глава 241»),
    # либо название при нём то же самое, только записано иначе.
    return not one.title or normalize_title(one.title) == normalize_title(two.title)


def _head(paragraphs) -> list[str]:
    return [line.strip() for line in paragraphs[:HEAD_LINES] if line.strip()]


def _artefact(body: str) -> str:
    """Какого рода артефакт эта строка. Пусто — строка нормальная.

    Абзац без единой кириллической буквы в русском переводе переводом не
    является: либо оригинал, который модель пропустила, либо служебная
    строка сайта. Одно английское слово посреди фразы находкой не
    считаем — имена и названия так и пишут.
    """
    if not body or CYRILLIC.search(body):
        return ""
    if CJK.search(body):
        return "cjk"
    if LATIN.search(body):
        return "latin"
    return "symbols" if any(_odd(char) for char in body) else ""


def _repeats(chapters) -> set[str]:
    """Строки зоны шапки, стоящие почти в каждой главе, — название книги.

    Считаются только они: чтобы решить, повтор это или текст, нужны все
    главы сразу, поэтому проход отдельный.
    """
    total = len(chapters)
    if total < ENOUGH:
        return set()

    seen: dict[str, int] = {}
    for title, paragraphs in chapters:
        counted: set[str] = set()
        for line in _head(paragraphs):
            if len(line) > HEAD_MAX or echoes(line, title):
                continue
            key = normalize_loose(line)
            if not key or key in counted:
                continue
            counted.add(key)
            seen[key] = seen.get(key, 0) + 1

    limit = max(MANY if total >= MANY else ENOUGH, int(total * SHARE))
    return {key for key, count in seen.items() if count >= limit}


def sort_out(line: str, index: int, title: str, repeats) -> str:
    """К какой находке отнести эту строку. Пусто — строка нужная.

    Порядок закрытый и один на осмотр и на чистку: строка попадает ровно
    в одну находку. Иначе название книги по-английски считалось бы и
    повтором, и непереведённым абзацем, а в сводке одна беда выглядела
    бы двумя.
    """
    body = (line or "").strip()
    if not body:
        return ""
    # Заголовок и название книги — только в зоне шапки: та же строка в
    # середине главы уже текст, и вычёркивать её нельзя.
    if index < HEAD_LINES:
        if echoes(body, title):
            return "echo"
        if normalize_loose(body) in repeats:
            return "repeat"
    return _artefact(body)


def inspect(chapters) -> Report:
    """Что в главах лишнего. `chapters` — пары «заголовок, абзацы»."""
    chapters = [(title, list(paragraphs)) for title, paragraphs in chapters]
    report = Report(chapters=len(chapters))
    repeats = _repeats(chapters)

    found: dict[str, Find] = {}
    for title, paragraphs in chapters:
        for index, line in enumerate(paragraphs):
            kind = sort_out(line, index, title, repeats)
            if not kind:
                continue
            body = line.strip()
            # У повтора своя строка на каждую находку: их может быть
            # несколько, и убирать их надо порознь.
            key = f"repeat:{normalize_loose(body)}" if kind == "repeat" else kind
            entry = found.get(key)
            if entry is None:
                found[key] = entry = Find(
                    kind, text=body if kind == "repeat" else "",
                    sample=body[:HEAD_MAX])
            entry.count += 1
            if len(entry.where) < SHOW:
                entry.where.append(title)

    order = list(KINDS)
    report.finds = sorted(found.values(),
                          key=lambda f: (order.index(f.kind), -f.count))
    return report


def clean(chapters, keys) -> tuple[list[tuple[str, list[str]]], int]:
    """Главы без отмеченных находок. Возвращает главы и число снятых строк.

    Разбирает строки тот же `sort_out`, что и осмотр: иначе в отчёте
    значилось бы одно, а из книги ушло бы другое. Исходные главы не
    меняются — чистка всегда пишется рядом, а не поверх.
    """
    chapters = [(title, list(paragraphs)) for title, paragraphs in chapters]
    wanted = set(keys or ())
    texts = {key.split(":", 1)[1] for key in wanted if key.startswith("repeat:")}
    # Повтор снимается по своей строке, остальные находки — по роду
    # целиком: «убрать все иероглифы» иначе пришлось бы отмечать построчно.
    kinds = {key for key in wanted if not key.startswith("repeat:")}
    repeats = _repeats(chapters)

    made: list[tuple[str, list[str]]] = []
    gone = 0
    for title, paragraphs in chapters:
        kept: list[str] = []
        for index, line in enumerate(paragraphs):
            kind = sort_out(line, index, title, repeats)
            drop = (kind in kinds if kind and kind != "repeat"
                    else kind == "repeat" and normalize_loose(line.strip()) in texts)
            if drop:
                gone += 1
                continue
            kept.append(line)
        made.append((title, kept))
    return made, gone
