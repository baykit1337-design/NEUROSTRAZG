"""Деление сплошного `.docx` на главы по разметке, а не по тексту.

Книгу нередко собирают копированием со страницы сайта прямо в Word. Если
при вставке не снимать форматирование, каждая глава ложится в свою рамку —
так Word переносит блок с рамкой из HTML, — а между рамками остаётся пустой
абзац. Заголовков внутри при этом может не быть вовсе.

Текстом такую границу не опознать: `core.headings` ищет строку вида
«Глава 12», а её там нет. Зато граница отлично видна в разметке файла, и
читается она отсюда.

Три признака, все три встречаются на настоящих вставках:

* **рамка** — у абзацев главы стоит `w:pBdr`; верхняя граница у первого,
  нижняя у последнего, боковые у всех;
* **таблица** — тот же блок с рамкой Word иногда переносит таблицей в одну
  ячейку, и тогда вся глава лежит внутри `w:tbl`;
* **пустой абзац** — разделитель, когда рамок нет совсем.

Работаем на уровне XML, а не `python-docx`-абзацев: обычному читателю
пустые абзацы не нужны, и он их выбрасывает — а здесь ровно они и есть
граница. По той же причине читатель не годится и для таблиц: в
`document.paragraphs` их содержимое не попадает вовсе.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import Chapter
from .readers.base import ReadError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: Границы, которые Word записывает, но не рисует. `nil` и `none` в файле
#: означают «стороны нет»: Word пишет все четыре стороны всегда, и без
#: этой проверки любой абзац выглядел бы обведённым.
NO_BORDER = {"", "nil", "none"}

#: Заголовок, оставшийся от разметки страницы: «# Название главы». Такие
#: строки приезжают со страниц, отдающих текст в Markdown. Решётки — не
#: часть названия, и в имя файла им попадать незачем.
HASH_TITLE = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")

#: Способы деления. `auto` пробует их по очереди: сначала рамки, потом
#: пустой абзац. Порядок не случаен — рамка граница надёжная, а пустой
#: абзац встречается и внутри главы.
WAYS = ("boxes", "blank", "auto")


class NoBlocksFound(Exception):
    """Разметка есть, а границ по ней не видно."""

    def __init__(self, way: str):
        self.way = way
        super().__init__(WAY_TROUBLE.get(way, WAY_TROUBLE["auto"]))


WAY_TROUBLE = {
    "boxes": "Рамок в документе не нашлось: у абзацев нет ни границ, ни "
             "таблиц. Похоже, форматирование при вставке всё-таки снялось.",
    "blank": "Пустых абзацев между главами не нашлось — делить нечем.",
    "auto": "Границ глав в разметке не видно: ни рамок, ни пустых абзацев. "
            "Остаётся делить по заголовку — опишите его шаблоном.",
}


@dataclass
class Line:
    """Абзац документа вместе с тем, что о нём говорит разметка."""

    text: str
    #: Отпечаток боковых границ: толщина и цвет. Пустой — абзац вне рамки.
    #: Боковые, а не все четыре, потому что рамка вокруг блока живёт именно
    #: на них: верх бывает только у первого абзаца, низ — только у
    #: последнего, а бока идут через весь блок.
    box: str = ""
    #: Отпечаток всех четырёх сторон. По нему Word решает, склеивать ли
    #: соседние абзацы в один прямоугольник: одинаковые склеиваются, и
    #: черты между ними не рисуется.
    edges: str = ""
    #: Верхняя и нижняя границы у самого абзаца.
    opens: bool = False
    closes: bool = False
    #: Номер таблицы, если абзац лежит в ней. Таблица всегда целая глава.
    table: int | None = None


@dataclass
class Cut:
    """Результат деления: главы и то, чем их поделили."""

    groups: list[list[str]] = field(default_factory=list)
    way: str = ""


def _text_of(node) -> str:
    """Текст абзаца. Собираем из кусков сами — `w:t` бывает разорван."""
    parts = [piece.text or "" for piece in node.iter(f"{W}t")]
    # Мягкий перенос внутри абзаца — тоже пробел, иначе слова слипнутся.
    text = "".join(parts).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _border_of(node) -> tuple[str, str, bool, bool]:
    """Отпечатки рамки абзаца (боковой и полный) и наличие верха с низом."""
    properties = node.find(f"{W}pPr")
    frame = properties.find(f"{W}pBdr") if properties is not None else None
    if frame is None:
        return "", "", False, False

    sides: list[str] = []
    everything: list[str] = []
    top = bottom = False
    for side in ("top", "bottom", "left", "right"):
        edge = frame.find(f"{W}{side}")
        if edge is None:
            continue
        value = (edge.get(f"{W}val") or "").lower()
        if value in NO_BORDER:
            continue
        mark = (f"{side}:{value}:{edge.get(f'{W}sz') or ''}"
                f":{edge.get(f'{W}color') or ''}")
        everything.append(mark)
        if side == "top":
            top = True
        elif side == "bottom":
            bottom = True
        else:
            sides.append(mark)
    return "|".join(sides), "|".join(everything), top, bottom


def lines(path: Path) -> list[Line]:
    """Абзацы документа по порядку — с пустыми и с содержимым таблиц."""
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - зависимость стоит всегда
        raise ReadError("Для .docx нужен python-docx") from exc
    try:
        document = Document(str(path))
    except Exception as exc:
        raise ReadError(f"{type(exc).__name__}: {exc}") from exc

    rows: list[Line] = []
    tables = 0
    for node in document.element.body.iterchildren():
        tag = node.tag.split("}")[-1]
        if tag == "p":
            box, edges, opens, closes = _border_of(node)
            rows.append(Line(text=_text_of(node), box=box, edges=edges,
                             opens=opens, closes=closes))
        elif tag == "tbl":
            tables += 1
            for cell in node.iter(f"{W}p"):
                rows.append(Line(text=_text_of(cell), table=tables))
    return rows


def by_boxes(rows: list[Line]) -> list[list[str]]:
    """Делит по рамкам и таблицам — там, где Word рисует между абзацами черту.

    Рамка вокруг главы — это не одна рамка на весь блок: Word ставит её
    **каждому абзацу отдельно**, а потом склеивает соседние в один
    прямоугольник. Отсюда и правило: новая глава начинается там, где
    прямоугольник разрывается.

    Разрыв бывает двух родов:

    * сменились боковые границы — в том числе пропали совсем, а это и есть
      пустой абзац между главами;
    * стороны у соседей описаны по-разному, и при этом у верхнего есть
      низ или у нижнего есть верх — тогда Word чертит между ними линию.
      Одинаково описанных соседей он склеивает молча, поэтому файл, где у
      всех абзацев подряд стоят все четыре стороны, — это одна рамка, а не
      двести отдельных.

    Абзац вне рамки главой не считается: пустой отделяет рамки друг от
    друга, а непустой — подпись или остаток разметки, и он приписывается к
    предыдущей главе. Заводить на него отдельную главу нельзя: первым же
    файлом на диск легла бы строка «Читать далее».
    """
    groups: list[list[str]] = []
    last: Line | None = None

    for row in rows:
        if row.table is not None or (last is not None and last.table is not None):
            starts = row.table != (last.table if last else None)
        elif not row.box:
            starts = False
        elif last is None or row.box != last.box:
            starts = True
        else:
            drawn = last.closes or row.opens
            starts = drawn and row.edges != last.edges

        if starts or not groups:
            groups.append([])
        if row.text:
            groups[-1].append(row.text)
        last = row

    return [group for group in groups if group]


def by_blank(rows: list[Line]) -> list[list[str]]:
    """Делит по пустым абзацам.

    Сколько их подряд — неважно: и один, и три означают одно и то же.
    """
    groups: list[list[str]] = []
    fresh = True
    for row in rows:
        if not row.text:
            fresh = True
            continue
        if fresh:
            groups.append([])
            fresh = False
        groups[-1].append(row.text)
    return groups


def cut(rows: list[Line], way: str = "auto") -> Cut:
    """Главы и способ, которым их поделили.

    `auto` пробует рамки, потом пустой абзац, и берёт первый способ, давший
    больше одной главы. Одна глава — это не деление, а исходный файл целиком.
    """
    order = ("boxes", "blank") if way == "auto" else (way,)
    for name in order:
        groups = by_boxes(rows) if name == "boxes" else by_blank(rows)
        if len(groups) > 1:
            return Cut(groups=groups, way=name)
    raise NoBlocksFound(way)


def chapters(path: Path, way: str = "auto") -> tuple[list[Chapter], str]:
    """Главы из документа и способ деления — для сообщения человеку.

    Номера здесь не проставляются: их неоткуда взять, в тексте их нет.
    Нумерацию задаёт «Разбить» подряд, начиная с указанного числа.
    """
    found = cut(lines(path), way)
    made: list[Chapter] = []
    for group in found.groups:
        title, body = _heading(group)
        made.append(Chapter(title=title, paragraphs=body, source=str(path)))
    return made, found.way


def _heading(group: list[str]) -> tuple[str, list[str]]:
    """Название главы из первой строки, если она им выглядит.

    Строка «# Возвращение» — заголовок, доставшийся от разметки страницы.
    В тексте ей делать нечего: она станет названием, а иначе решётка
    попала бы и в имя файла, и первой строкой в текст.
    """
    if not group:
        return "", []
    match = HASH_TITLE.match(group[0])
    if match:
        return match.group(1).strip(), group[1:]
    return "", list(group)
