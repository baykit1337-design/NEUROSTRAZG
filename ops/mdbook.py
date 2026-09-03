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
    #:
    #: Пробел перед решёткой — не украшение: так пишет заголовок
    #: переводчик, из которого книгу сюда приносят, и так она возвращается
    #: с сайта. Прочитанный заголовок сохраняет своё начало дословно, а
    #: это — начало заголовка, написанного с нуля.
    opening: str = " # ["
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


def _slot(value: str) -> str:
    """Поле заголовка: с ведущим пробелом, если в нём что-то есть."""
    return f" {value}" if value else ""


def make_head(title: str, order: str = "", paid: str = "",
              volume: str = "") -> Head:
    """Заголовок с нуля.

    Все три поля пишутся всегда, даже пустые:

        # [Глава 31 :|: :|: 1 :|: ]

    Сначала пустые поля с конца здесь опускались — и это была выдумка.
    Так пишет сам загрузчик, и так выглядит книга, которую он отдаёт
    обратно; строка с одним разделителем вместо трёх — уже другая
    строка. Пустой том на конце оставляет пробел перед скобкой: у
    загрузчика он там и стоит.
    """
    title = str(title or "").replace(MARK, " ").strip()
    order, paid, volume = (str(x or "").strip() for x in (order, paid, volume))

    return Head(title=title,
                tail=f" {MARK}{_slot(order)}"
                     f" {MARK}{_slot(paid)}"
                     f" {MARK}{_slot(volume) or ' '}")


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


def split_mark(title: str) -> tuple[int | None, int | None, str]:
    """Номер главы, номер части и имя — из заголовка на любом языке.

    Разбор берётся из ядра и на язык не опирается: ищется первая группа
    из 1–5 цифр, всё до неё («Chapter», «Глава», «第») отбрасывается.

    Номер части нужен отдельно, потому что он есть. Пока его отбрасывали,
    «Глава 201.2» становилась при перезаписи «Главой 201» — второй такой
    же, как её первая часть, — и книга уезжала на сайт с настоящими
    дублями. Проверка нумерации при этом ругалась на дубли ещё до
    перезаписи: части 201.1 и 201.2 она считала одной главой дважды.
    """
    parts = naming.parse(str(title or ""))
    return parts.number, parts.part, parts.title


def split_title(title: str) -> tuple[int | None, str]:
    """Номер главы и её имя. Часть — в `split_mark`."""
    number, _, name = split_mark(title)
    return number, name


#: Начало заголовка, где номер главы уже записан: пометка главы на любом
#: языке (или ничего), сам номер и знак после него.
#:
#: Номер части снимается вместе с номером главы: у файла «Глава 201.2 -
#: Название» пометкой главы является всё «Глава 201.2», а не «Глава 201».
#: Пока часть в пометку не входила, от неё оставалась «2», и в книге
#: выходило «Глава 201.2 — 2 - Название».
OWN_NUMBER = re.compile(
    rf"^\s*(?:{naming.CHAPTER_WORD})?\s*(\d{{1,5}})(?:\.(\d{{1,3}}))?(?!\d)"
    r"\s*[^\w\s]*\s*",
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


#: Сколько находок одного рода показывать. Полторы тысячи глав дадут при
#: разнобое список во весь экран, а чинить его всё равно по одной.
SHOW = 12


def _ranges(numbers: list[int]) -> list[str]:
    """Подряд идущие числа — одной строкой: «1170–1175»."""
    out: list[str] = []
    for number in sorted(numbers):
        if out:
            low, _, high = out[-1].partition("–")
            if number == int(high or low) + 1:
                out[-1] = f"{low}–{number}"
                continue
        out.append(str(number))
    return out


def _mark_text(mark) -> str:
    """Номер главы для человека: «201» или «201.2»."""
    number, part = mark
    return f"{number}.{part}" if part else str(number)


#: Со скольких номеров книга считается достаточно большой, чтобы у неё
#: был свой ритм. Меньше — и «у каждого номера по две главы» означает
#: только то, что глав всего две.
ENOUGH = 10


def _rhythm(counts) -> int:
    """Сколько глав в этой книге приходится на один номер.

    Обычно одна. Но книгу, поделённую надвое, отдают загрузчику парами:
    «Глава 295» дважды подряд, без номера части в заголовке. Для такой
    книги две главы под номером — норма, а не дубль.

    Ритм признаём только явный: так должно жить большинство номеров, и
    самих номеров должно быть достаточно. Две главы под одним номером в
    книге из двух глав — это дубль, а не ритм: за ним не стоит ничего,
    кроме себя самого. Разнобой ритмом тоже не считается — иначе
    случайный перекос объявил бы нормой то, что нормой не является.
    """
    if len(counts) < ENOUGH:
        return 1
    tally: dict[int, int] = {}
    for value in counts.values():
        tally[value] = tally.get(value, 0) + 1
    usual = max(tally, key=lambda value: (tally[value], -value))
    return usual if tally[usual] * 2 > len(counts) else 1


def inspect(chapters) -> dict:
    """Что не так с нумерацией книги.

    Загрузчик сортирует главы по полю «Порядок», а человек читает номер в
    названии — и разъезжаются они молча. Пропуск в номерах значит, что
    главу потеряли по дороге; повтор — что она уедет на сайт дважды;
    номер назад — что порядок собьётся.
    """
    numbers: list[int] = []
    nameless: list[str] = []
    backwards: list[str] = []
    orders: list[str] = []
    plain: list[str] = []

    #: Пары «номер, часть». Дублем считается совпадение пары, а не номера:
    #: «Глава 201.1» и «Глава 201.2» — две части одной главы, а не одна
    #: глава дважды. Книгу, поделённую на части руками, прежняя проверка
    #: объявляла сплошным непорядком.
    marks: list[tuple[int, int | None]] = []

    #: Тела глав: одинаковый текст — одна и та же глава, под какими бы
    #: номерами она ни стояла. Одинаковый номер этого ещё не значит.
    same: dict[str, list[str]] = {}

    previous = None
    for head, body in chapters:
        number, part, _ = split_mark(head.title)
        if number is None:
            nameless.append(head.title)
        else:
            if previous is not None and number < previous:
                backwards.append(f"{previous} → {number}")
            previous = number
            numbers.append(number)
            marks.append((number, part))
        if head.order.strip():
            orders.append(head.order.strip())
        if not looks_translated(head.title):
            plain.append(head.title)

        # Пустую главу сравнивать не с чем: пустые совпадают все со
        # всеми, и книга без тел глав вышла бы сплошным повтором.
        text = "\n".join(line.strip() for line in body if line.strip())
        if text:
            mark = _mark_text((number, part)) if number is not None \
                else (head.title or "без номера")
            same.setdefault(text, []).append(mark)

    # Дубль — это повтор главы, а не повтор её номера.
    #
    # Здесь проверка и врала. Настоящая книга: у каждой главы по две-три
    # части, пометка «(Часть 2)» стоит не везде, а у иной части и
    # название своё. Номер при этом один. Проверка объявляла дублями
    # двести шестьдесят девять номеров — почти всю книгу, — и за этим
    # списком не было видно ничего.
    #
    # Одинаковый номер — ещё не одна и та же глава. Одинаковый текст —
    # она и есть: такая уедет на сайт дважды.
    doubles = [" = ".join(marks[:SHOW])
               for marks in same.values() if len(marks) > 1]

    # Сколько глав под каждым номером — и сколько их тут обычно.
    counts: dict[int, int] = {}
    for number, _ in marks:
        counts[number] = counts.get(number, 0) + 1
    usual = _rhythm(counts)

    # Пропажу в такой книге иначе не видно вовсе: глава ушла, а номер
    # остался — дыры в номерах нет. Видно её по тому, что глав под
    # номером стало меньше, чем у соседей.
    thin = sorted(number for number, count in counts.items() if count < usual)

    seen = {number for number, _ in marks}

    gaps: list[int] = []
    if numbers:
        low, high = min(numbers), max(numbers)
        # Дыру ищем только внутри своего же диапазона: книга может
        # начинаться с 1168-й главы, и «нет глав с 1 по 1167» — не находка.
        gaps = [n for n in range(low, high + 1) if n not in seen]

    order_seen, order_doubles = set(), []
    for value in orders:
        if value in order_seen and value not in order_doubles:
            order_doubles.append(value)
        order_seen.add(value)

    return {
        "total": len(chapters),
        "numbered": len(numbers),
        "first": min(numbers) if numbers else None,
        "last": max(numbers) if numbers else None,
        "nameless": nameless[:SHOW],
        "nameless_count": len(nameless),
        "gaps": _ranges(gaps)[:SHOW],
        "gaps_count": len(gaps),
        "doubles": doubles[:SHOW],
        "doubles_count": len(doubles),
        #: Сколько глав приходится на номер в этой книге и где их меньше.
        "per_number": usual,
        "thin": _ranges(thin)[:SHOW],
        "thin_count": len(thin),
        "backwards": backwards[:SHOW],
        "backwards_count": len(backwards),
        "order_doubles": order_doubles[:SHOW],
        "order_doubles_count": len(order_doubles),
        "untranslated": len(plain),
        "ok": not (gaps or doubles or thin or backwards
                   or order_doubles),
    }


def number_parts(taken) -> list:
    """Проставить номера частям, у которых их не было.

    `taken` — тройки «номер, часть, название», как их отдаёт разбор
    заголовков. Возвращает такие же тройки, но у подряд идущих глав с
    одним номером появляются части: 1, 2, 3.

    Зачем. Настоящая книга: у главы две-три части, и пометки части у них
    то есть, то нет — «Глава 295», «Глава 295 (Часть 2)», а следом две
    «Главы 296» подряд без всяких пометок. Загрузчику это уедет как одна
    и та же глава несколько раз, и порядок на сайте соберётся наугад.

    Считаем по соседству, а не по всей книге. Две главы с одним номером,
    стоящие рядом, — почти наверняка куски одной; те же два номера в
    разных концах книги — скорее чужая ошибка, и склеивать их в части
    было бы выдумкой.

    Часть, которая уже проставлена, не трогаем: она пришла от человека,
    и знать лучше него нам неоткуда. Одиночную главу частью не делаем —
    «Глава 300.1» без «300.2» означала бы часть, которой нет.
    """
    fresh = list(taken)
    at = 0
    while at < len(fresh):
        number = fresh[at][0]
        if number is None:
            at += 1
            continue
        end = at
        while end + 1 < len(fresh) and fresh[end + 1][0] == number:
            end += 1
        # Куском одной главы считаем только то, что идёт подряд и не
        # размечено. Хоть у одной части номер уже есть — значит, человек
        # разметил их сам, и наша помощь тут лишняя.
        if end > at and all(part is None for _, part, _ in fresh[at:end + 1]):
            for shift, place in enumerate(range(at, end + 1), 1):
                one_number, _, name = fresh[place]
                fresh[place] = (one_number, shift, name)
        at = end + 1
    return fresh


def paragraphs_of(lines: list[str]) -> list[str]:
    """Строки тела главы — в абзацы: делить на части можно только их.

    Абзац — это строка. Не «кусок между пустыми строками»: книгу для
    загрузчика пишут без пустых строк вовсе, и по прежнему правилу вся
    глава оказывалась одним абзацем — а значит, неделимой.
    """
    return [line.strip() for line in lines if line.strip()]


def lines_of(paragraphs: list[str]) -> list[str]:
    """Абзацы обратно в строки — по строке на абзац, без пустых.

    Пустая строка между абзацами превращается на сайте в пустой абзац, и
    книга уезжает туда с огромными отступами между строками. Так же — без
    пустых строк — пишет книгу и переводчик, из которого её сюда приносят;
    расхождение здесь означало бы, что после нашей обработки книга
    выглядит иначе, чем до неё.
    """
    return [block for block in paragraphs if block]


def to_standard(chapters) -> list[tuple[Head, list[str]]]:
    """Книгу — к тому виду, в котором её ждёт загрузчик.

    Старые книги приходят такими, какими их отдал прежний конвертер:
    заголовок без пробела перед решёткой и пустая строка между абзацами.
    Прочитанный заголовок мы храним дословно — и правильно делаем, менять
    чужую строку молча нельзя, — но починить её иногда просят прямо.

    Пустая строка превращается на сайте в пустой абзац, и книга уезжает
    туда с огромными отступами между строками; пробел перед решёткой
    ставит и переводчик, из которого книгу сюда приносят.

    Названия, порядок, платность и том не трогаем: это правка вида, а не
    содержания.
    """
    out: list[tuple[Head, list[str]]] = []
    for head, body in chapters:
        # Начало и конец строки берём умолчанием `Head` — оно и есть
        # стандарт; всё остальное переносим как было.
        fresh = Head(title=head.title, gap=head.gap, tail=head.tail)
        out.append((fresh, lines_of(paragraphs_of(body))))
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


#: Что делать с названием главы, собирая книгу из файлов.
KEEP, DROP = "keep", "drop"


def from_chapters(chapters, style: TitleStyle | None = None,
                  paid: str = "", volume: str = "", first: int = 0,
                  parts: int = 1, numbering: bool = True,
                  names: str = KEEP) -> list:
    """Главы, прочитанные из файлов, — в главы книги для загрузчика.

    `first` — с какого номера порядка начать. Ноль означает «не писать
    порядок вовсе»: сайт расставит его сам, и это честнее выдуманных
    чисел, когда в именах файлов номеров не было.

    `names` — оставить название из имени файла или убрать его, оставив
    один номер. Выбора этого здесь не было вовсе: имя файла всегда шло в
    заголовок, и книгу с заголовками «Глава 82» собрать было нечем —
    убрать их можно было только вторым проходом, по уже готовой книге.
    """
    style = style or TitleStyle()
    out: list[tuple[Head, list[str]]] = []
    order = first

    for chapter in chapters:
        # Номер части берём у главы, а не заново из названия: читатель
        # уже разобрал имя файла. Пока часть отбрасывали, «Глава 201.2»
        # становилась в книге «Главой 201» — второй такой же, как её
        # первая часть.
        number, part = chapter.number, chapter.part
        if number is None:
            # Строгим разбором, а не общим. Читалка номер уже искала и не
            # нашла — значит, в заголовке его нет, и докапываться до
            # первой попавшейся цифры тут не надо. Из епаба так выходила
            # «Глава 3 — "Act 3 is about to begin."»: цифра из названия
            # становилась номером главы, а книга потом выстраивалась по
            # этим числам.
            found = naming.parse_title(chapter.title)
            number, part = found.number, found.part
        # Название у прочитанной главы — это имя файла целиком, вместе с
        # «Глава 101 - ». Возьми мы его как есть, вышло бы «Глава 101 —
        # Глава 101 - Название»: слово и номер встали бы дважды.
        name = bare_name(chapter.title, number)
        if not numbering:
            number = None
        # Убрать название можно только там, где остаётся номер: у пролога
        # его нет, и «Глава» вместо «Пролога» — неправда.
        if names == DROP and number is not None:
            name = ""
        title = style.build(number, name, part=part) if number is not None else \
            (name or chapter.title or style.prefix)
        head = make_head(title, str(order) if order else "", paid, volume)
        body = lines_of(list(chapter.paragraphs))

        pieces = cut_into_parts(head, body, parts, style, number, name)
        out.extend(pieces)
        if order:
            order += len(pieces)
    return out


__all__ = ["DEFAULT_SEPARATOR", "DROP", "FREE", "HEAD_RE", "Head", "KEEP",
           "MARK", "PAID",
           "PAYMENT", "SEPARATORS", "TitleStyle", "cut_into_parts",
           "from_chapters", "inspect", "lines_of", "looks_translated",
           "make_head", "number_parts",
           "paragraphs_of", "parse_head", "read_book", "split_title",
           "to_standard",
           "write_book"]
