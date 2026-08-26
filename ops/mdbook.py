"""Формат загрузчика: книга одним `.md` с заголовками в скобках.

Сайт, куда книга уезжает, читает один файл и режет его по строкам вида

    # [Название :|: Порядок :|: Платность :|: Том]

Всё, что стоит до первого такого заголовка, он выбрасывает. Из его
правил здесь нужны четыре:

* **Название** — любое, но `:|:` внутри быть не может: это разделитель.
* **Порядок** — число, необязателен. Без него сайт нумерует сам, продолжая
  от последнего заданного.
* **Платность** — `0`/`n` бесплатная, `1`/`y` платная, пробел — «как в
  форме на сайте».
* **Том** — любое имя, необязателен. Но если том есть, платность обязана
  быть заполнена хотя бы пробелом: иначе полей окажется меньше, и сайт
  прочитает том как платность.

Главная забота модуля — **не трогать ничего, кроме названия**. Когда
переписываются заголовки уже готовой книги, остаток строки сохраняется
дословно, вместе с пробелами: у сайта эти поля значат цену и том, и
«причесать» их значило бы поменять книге цену.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core import naming
from core.text import split_into_parts

#: Разделитель полей заголовка. Задан сайтом, менять нельзя.
MARK = ":|:"

#: Строка заголовка целиком. Скобки, решётка и пробелы вокруг них взяты
#: в свои группы нарочно: переводчик ставит их как придётся — то с
#: отступом в начале строки, то с пробелом в конце, — а нам эту строку
#: собирать обратно символ в символ.
HEAD_RE = re.compile(r"^(\s*#\s*\[)(.*)(\]\s*)$")

#: Платность: как её понимает сайт.
FREE, PAID = "0", "1"
PAYMENT = {"free": FREE, "paid": PAID, "form": " "}

#: Разделитель между номером и названием. Тот же список, что во вкладке
#: «Переименовать», плюс голый пробел: у загрузчика названия часто идут
#: без знака вовсе.
SEPARATORS = (" ", " — ", " - ", ": ", ". ")
DEFAULT_SEPARATOR = " — "


@dataclass
class Head:
    """Заголовок главы: название и всё остальное — дословно.

    `gap` и `tail` хранят исходную строку по кускам, чтобы её можно было
    собрать обратно символ в символ. Разбирать их на поля и собирать
    заново нельзя: лишний или потерянный пробел в платности меняет
    смысл, а мы правим только название.
    """

    title: str = ""
    #: Пробелы между названием и первым разделителем.
    gap: str = ""
    #: Всё от первого разделителя и до конца скобки, как было.
    tail: str = ""
    #: Чем строка открывается и чем закрывается — вместе с отступом и
    #: пробелами. Хранится дословно по той же причине, что и `tail`.
    opening: str = "# ["
    closing: str = "]"

    @property
    def fields(self) -> list[str]:
        """Порядок, платность, том — как их прочитает сайт."""
        if not self.tail:
            return []
        return [piece.strip() for piece in self.tail.split(MARK)[1:]]

    def field(self, at: int) -> str:
        found = self.fields
        return found[at] if at < len(found) else ""

    @property
    def order(self) -> str:
        return self.field(0)

    @property
    def paid(self) -> str:
        return self.field(1)

    @property
    def volume(self) -> str:
        return self.field(2)

    def line(self) -> str:
        return f"{self.opening}{self.title}{self.gap}{self.tail}{self.closing}"

    def with_title(self, title: str) -> Head:
        """Тот же заголовок с другим названием. Остальное — как было."""
        return Head(title=title, gap=self.gap, tail=self.tail,
                    opening=self.opening, closing=self.closing)

    def as_dict(self) -> dict:
        return {"title": self.title, "order": self.order, "paid": self.paid,
                "volume": self.volume, "line": self.line()}


def parse_head(line: str) -> Head | None:
    """Заголовок из строки. `None` — строка обычная, не заголовок."""
    found = HEAD_RE.match(line or "")
    if not found:
        return None
    opening, inside, closing = found.groups()
    at = inside.find(MARK)
    if at < 0:
        return Head(title=inside.strip(), opening=opening, closing=closing)
    left = inside[:at]
    return Head(title=left.strip(),
                gap=left[len(left.rstrip()):],
                tail=inside[at:],
                opening=opening, closing=closing)


def make_head(title: str, order: str = "", paid: str = "",
              volume: str = "") -> Head:
    """Заголовок с нуля.

    Пустые поля с конца не пишем вовсе: лишний разделитель сайт прочитает
    как «том без имени». А вот пропуск в середине оставляем — том без
    платности перед ним съедет на чужое поле.
    """
    title = str(title or "").replace(MARK, " ").strip()
    order, paid, volume = (str(x or "") for x in (order, paid, volume))

    rest: list[str] = []
    if volume.strip():
        rest = [order, paid or " ", volume]
    elif paid.strip():
        rest = [order, paid]
    elif order.strip():
        rest = [order]

    return Head(title=title,
                tail="".join(f" {MARK} {piece}" for piece in rest))


def read_book(text: str) -> tuple[str, list[tuple[Head, list[str]]]]:
    """Преамбула и главы книги.

    Преамбулу сайт выбрасывает, а мы её храним: человек мог написать там
    что-то для себя, и терять это при перезаписи заголовков незачем.
    """
    lead: list[str] = []
    chapters: list[tuple[Head, list[str]]] = []
    head: Head | None = None
    body: list[str] = []

    for line in (text or "").splitlines():
        found = parse_head(line)
        if found is not None:
            if head is not None:
                chapters.append((head, body))
            head, body = found, []
        elif head is None:
            lead.append(line)
        else:
            body.append(line)

    if head is not None:
        chapters.append((head, body))
    return "\n".join(lead), chapters


def write_book(chapters, lead: str = "") -> str:
    """Книга обратно в текст. Прочитанное и записанное совпадают."""
    # Именно `split`, а не `splitlines`: у преамбулы, кончающейся пустой
    # строкой, `splitlines` эту строку теряет — и книга собирается на
    # строку короче, чем была.
    out: list[str] = lead.split("\n") if lead else []
    for head, body in chapters:
        out.append(head.line())
        out.extend(body)
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- названия


@dataclass(frozen=True)
class TitleStyle:
    """Как собирать название главы из номера и имени."""

    prefix: str = naming.DEFAULT_PREFIX
    separator: str = DEFAULT_SEPARATOR

    def build(self, number, name: str = "", part=None) -> str:
        """«Глава 1171.2 — Название».

        Номера нет — остаётся одно имя: пролог и послесловие номера не
        имеют, и «Глава — Пролог» было бы неправдой.
        """
        name = str(name or "").strip()
        if number is None:
            return name or str(self.prefix or "").strip()

        mark = f"{number}.{part}" if part else str(number)
        head = f"{self.prefix} {mark}".strip()
        return f"{head}{self.separator}{name}" if name else head


def split_title(title: str) -> tuple[int | None, str]:
    """Номер главы и её имя — из заголовка на любом языке.

    Разбор берётся из ядра и на язык не опирается: ищется первая группа
    из 1–5 цифр, всё до неё («Chapter», «Глава», «第») отбрасывается.
    """
    parts = naming.parse(str(title or ""))
    return parts.number, parts.title


#: Начало заголовка, где номер главы уже записан: пометка главы на любом
#: языке (или ничего), сам номер и знак после него.
OWN_NUMBER = re.compile(
    rf"^\s*(?:{naming.CHAPTER_WORD})?\s*(\d{{1,5}})(?!\d)\s*[^\w\s]*\s*",
    re.IGNORECASE)


def bare_name(title: str, number=None) -> str:
    """Имя главы без её собственного номера в начале.

    Читалка отдаёт названием имя файла целиком — «Глава 101 - Название».
    Собери мы из него «Глава 101 — Глава 101 - Название», номер и слово
    встали бы дважды.

    Резать по первому числу, как это делает разбор имён файлов, здесь
    нельзя: у «Название 1» число — часть имени, и от названия не осталось
    бы ничего. Поэтому срезаем только настоящую пометку главы в начале, и
    только если номер в ней тот же самый.
    """
    title = str(title or "").strip()
    found = OWN_NUMBER.match(title)
    if not found:
        return title
    if number is not None and str(number) != found.group(1):
        return title
    return title[found.end():].strip()


def looks_translated(title: str, alphabet: str = "а-яёА-ЯЁ") -> bool:
    """Есть ли в названии русские буквы. Пустое имя — не в счёт."""
    return bool(re.search(f"[{alphabet}]", str(title or "")))


# --------------------------------------------------------------- работы


def paragraphs_of(lines: list[str]) -> list[str]:
    """Строки тела главы — в абзацы: делить на части можно только их."""
    blocks: list[str] = []
    buffer: list[str] = []
    for line in lines:
        if line.strip():
            buffer.append(line.strip())
        elif buffer:
            blocks.append("\n".join(buffer))
            buffer = []
    if buffer:
        blocks.append("\n".join(buffer))
    return blocks


def lines_of(paragraphs: list[str]) -> list[str]:
    """Абзацы обратно в строки — с пустой строкой между ними."""
    out: list[str] = [""]
    for block in paragraphs:
        out.append(block)
        out.append("")
    return out


def cut_into_parts(head: Head, body: list[str], count: int,
                   style: TitleStyle | None = None,
                   number=None, name: str = "") -> list[tuple[Head, list[str]]]:
    """Разбить главу на части. Порядок и платность у частей общие.

    Номер порядка у частей не трогаем: сайт нумерует подряд от последнего
    заданного, и поставь мы всем частям один номер — они встали бы одна
    на другую.
    """
    style = style or TitleStyle()
    blocks = paragraphs_of(body)
    if count < 2 or len(blocks) < 2:
        return [(head, body)]

    pieces = split_into_parts(blocks, count)
    if len(pieces) < 2:
        return [(head, body)]

    if number is None:
        number, name = split_title(head.title)

    out = []
    for index, piece in enumerate(pieces, 1):
        title = style.build(number, name, part=index) if number is not None \
            else f"{head.title} — часть {index}"
        # Порядок пишем только первой части: остальным сайт назначит свои
        # номера подряд, и они не столкнутся с уже занятыми.
        spare = head.with_title(title) if index == 1 else \
            make_head(title, "", head.paid, head.volume)
        out.append((spare, lines_of(piece)))
    return out


def from_chapters(chapters, style: TitleStyle | None = None,
                  paid: str = "", volume: str = "", first: int = 0,
                  parts: int = 1, numbering: bool = True) -> list:
    """Главы, прочитанные из файлов, — в главы книги для загрузчика.

    `first` — с какого номера порядка начать. Ноль означает «не писать
    порядок вовсе»: сайт расставит его сам, и это честнее выдуманных
    чисел, когда в именах файлов номеров не было.
    """
    style = style or TitleStyle()
    out: list[tuple[Head, list[str]]] = []
    order = first

    for chapter in chapters:
        number = chapter.number
        if number is None:
            number, _ = split_title(chapter.title)
        # Название у прочитанной главы — это имя файла целиком, вместе с
        # «Глава 101 - ». Возьми мы его как есть, вышло бы «Глава 101 —
        # Глава 101 - Название»: слово и номер встали бы дважды.
        name = bare_name(chapter.title, number)
        if not numbering:
            number = None
        title = style.build(number, name) if number is not None else \
            (name or chapter.title or style.prefix)
        head = make_head(title, str(order) if order else "", paid, volume)
        body = lines_of(list(chapter.paragraphs))

        pieces = cut_into_parts(head, body, parts, style, number, name)
        out.extend(pieces)
        if order:
            order += len(pieces)
    return out


__all__ = ["DEFAULT_SEPARATOR", "FREE", "HEAD_RE", "Head", "MARK", "PAID",
           "PAYMENT", "SEPARATORS", "TitleStyle", "cut_into_parts",
           "from_chapters", "lines_of", "looks_translated", "make_head",
           "paragraphs_of", "parse_head", "read_book", "split_title",
           "write_book"]
