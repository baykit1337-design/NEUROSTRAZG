"""Цифры Цидяня, спрятанные за шрифтом.

На странице рейтинга число месячных билетов не написано. Вместо него
стоят знаки из неназначенной области Unicode, а рядом — свой шрифт,
который рисует их как цифры:

    <style>@font-face { font-family: qXUqdlfe;
      src: url('…/qd_anti_spider/qXUqdlfe.ttf') format('truetype'); }</style>
    <span class="qXUqdlfe">&#100386;&#100386;&#100379;&#100382;&#100386;</span>

Читателю видно «20717», разбору — пять чужих знаков. Имя семейства и
набор кодов сайт меняет от страницы к странице, так что запомнить
таблицу раз и навсегда нельзя: её каждый раз достают из самого шрифта.

Путей два, как и у Фанкью. Сначала по **именам глифов**: если глиф
называется `four`, `uni0034` или просто `4`, цифра известна сразу и
ничего рисовать не нужно. Когда имена обезличены — по **начертанию**:
глиф рисуется в картинку, обрезается по краям чернил и сверяется с теми
же десятью цифрами, отрисованными обычным шрифтом. Обрезка тут важнее,
чем у иероглифов: у цифр разных гарнитур совпадают пропорции, но не
кегль, и без выравнивания по краям сравнение врёт.

Отличие от `fanqiefont` — в том, где искать. Фанкью уводит знаки в
служебную область (E000–F8FF), Цидянь берёт коды откуда придётся
(0x18822). Поэтому здесь ищут не по диапазону, а по имени семейства:
цифры лежат в теге с классом, равным этому имени.

Чего живьём никто не видел: самого файла шрифта. Разбор проверен на
шрифте, собранном для проверки из системного, — с переставленными
кодами и стёртыми именами глифов, то есть ровно с тем, что делает сайт.
"""

from __future__ import annotations

import logging
import re
import threading

from .fanqiefont import FontReport, FontUnavailable, digest_of

log = logging.getLogger(__name__)

#: Имя семейства и адрес файла в стилях рядом с числом.
FAMILY = re.compile(r"font-family\s*:\s*['\"]?([\w-]+)['\"]?", re.I)
SOURCE = re.compile(r"url\(['\"]?(https?://[^)'\"]+?\.(?:ttf|otf|woff2?|eot))",
                    re.I)

#: В каком порядке брать форматы. `.eot` сайт перечисляет первым, но это
#:形式 для старого IE, и `fontTools` его не откроет; `.woff2` сжат brotli
#: и без этого пакета тоже не откроется. Простое — вперёд.
FORMAT_ORDER = (".ttf", ".otf", ".woff", ".woff2", ".eot")

#: Имена глифов, по которым цифра видна сразу.
WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
         "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}
CODED = re.compile(r"^uni?(00)?3([0-9])$", re.I)

DIGITS = "0123456789"

#: Размер картинки для сверки начертаний. Цифра выше, чем шире, поэтому
#: и рамка не квадратная — иначе при обрезке всё растянется по-разному.
SHAPE_W, SHAPE_H = 48, 64

#: Насколько картинки должны совпасть. Порог низкий нарочно: он тут не
#: судья, а сторож. Судит лучшее совпадение из десяти — на проверке оно
#: выбрало верную цифру во всех сорока случаях, у самой трудной пары
#: совпадение было 0.75. Порог отсекает другое: когда в шрифте нарисованы
#: вовсе не цифры и похожего нет ни на что.
SHAPE_THRESHOLD = 0.70

BY_NAMES = "по именам глифов"
BY_SHAPE = "по начертанию"

_LOCK = threading.Lock()
_TABLES: dict[str, dict] = {}
_FAMILIES: dict[str, str] = {}
_REPORTS: dict[str, FontReport] = {}


def font_of(css: str) -> tuple[str, str]:
    """Имя семейства и лучший из адресов файла из куска стилей."""
    family = FAMILY.search(css or "")
    found = SOURCE.findall(css or "")

    def rank(url: str) -> int:
        low = url.lower()
        for index, suffix in enumerate(FORMAT_ORDER):
            if low.endswith(suffix):
                return index
        return len(FORMAT_ORDER)

    ordered = sorted(dict.fromkeys(found), key=rank)
    return (family.group(1) if family else "", ordered[0] if ordered else "")


def _open(data: bytes):
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise FontUnavailable(
            "Расшифровка чисел требует пакета fonttools: "
            "pip install fonttools") from exc

    import io

    try:
        return TTFont(io.BytesIO(data), lazy=True)
    except Exception as exc:  # noqa: BLE001 — причину показываем целиком
        raise FontUnavailable(f"Шрифт не разобрался: {exc}") from exc


def _digit_of(name: str) -> str:
    """Цифра по имени глифа. Пусто — имя ничего не говорит."""
    said = str(name or "").strip()
    if said in WORDS:
        return WORDS[said]
    if len(said) == 1 and said in DIGITS:
        return said
    found = CODED.match(said)
    return found.group(2) if found else ""


def _from_font(data: bytes, report: FontReport) -> dict:
    """Таблица «знак страницы → цифра» из файла шрифта."""
    font = _open(data)
    try:
        cmap = font.getBestCmap()
    except Exception as exc:  # noqa: BLE001 — причину показываем целиком
        raise FontUnavailable(f"В шрифте нет таблицы символов: {exc}") from exc

    # Знаки, ради которых всё затевалось: настоящие цифры сайт в этот
    # шрифт не кладёт, а всё, что кладёт, — подмена.
    hidden = {code: glyph for code, glyph in cmap.items() if code > 0x20}
    report.glyphs = len(cmap)
    report.private = len(hidden)

    table = {}
    for code, glyph in hidden.items():
        digit = _digit_of(glyph)
        if digit:
            table[chr(code)] = digit

    if table:
        report.method = BY_NAMES
        report.mapped = len(table)
        report.unmapped = len(hidden) - len(table)
        return table

    table = _by_shape(font, hidden, report)
    report.mapped = len(table)
    report.unmapped = len(hidden) - len(table)
    if not table and not report.error:
        report.error = ("имена глифов обезличены, а по начертанию ни одна "
                        "цифра не подобралась")
    return table


# ------------------------------------------------------------ начертания

def _by_shape(font, hidden: dict, report: FontReport) -> dict:
    """Сверка начертаний: глиф сайта против обычных цифр."""
    report.method = BY_SHAPE
    report.threshold = SHAPE_THRESHOLD

    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        report.error = ("сверка начертаний требует Pillow: "
                        "pip install pillow numpy")
        return {}
    try:
        import numpy
    except ImportError:
        report.error = ("сверка начертаний требует numpy: "
                        "pip install pillow numpy")
        return {}

    references = reference_fonts()
    if not references:
        report.error = "не нашлось обычного шрифта, с которым сверять цифры"
        return {}

    ours = _shapes_of_font(font, hidden, numpy)
    if not ours:
        report.error = "глифы шрифта не нарисовались"
        return {}

    # Образцов берём несколько гарнитур. Одной мало: четвёрка с
    # перекладиной наверху и четвёрка с открытым верхом — разные рисунки,
    # и цифра антиквы, сверяемая с одним гротеском, уходит не туда.
    theirs: list[tuple[str, object]] = []
    for path in references:
        for digit, sample in _shapes_of_reference(path, numpy).items():
            theirs.append((digit, sample))
    if not theirs:
        report.error = "образцовые цифры не нарисовались"
        return {}

    table = {}
    for code, picture in ours.items():
        best, score = "", 0.0
        for digit, sample in theirs:
            near = float((picture == sample).mean())
            if near > score:
                best, score = digit, near
        if best and score >= SHAPE_THRESHOLD:
            table[chr(code)] = best

    # Проверка по смыслу, а не по порогу. Шрифт прячет десять цифр, и
    # каждая в нём ровно одна: если две подмены указали на одну цифру,
    # сверка где-то ошиблась — и мы не знаем где. Показать в рейтинге
    # число, собранное из таких цифр, хуже, чем не показать никакого:
    # неверное число выглядит достоверно и ничем себя не выдаёт.
    if len(set(table.values())) != len(table):
        report.error = ("по начертанию две подмены сошлись на одной цифре — "
                        "таблице верить нельзя")
        return {}
    return table


def _trim(picture, numpy):
    """Картинка, обрезанная по краям чернил и растянутая в общую рамку.

    Без этого сравнение врёт: одна и та же цифра в двух гарнитурах стоит
    на разной высоте и занимает разную долю кегля, и совпадение падает
    ниже любого разумного порога просто из-за сдвига.
    """
    from PIL import Image

    ink = numpy.argwhere(picture)
    if not len(ink):
        return None
    top, left = ink.min(axis=0)
    bottom, right = ink.max(axis=0)
    cut = Image.fromarray(picture[top:bottom + 1, left:right + 1])
    return numpy.array(cut.resize((SHAPE_W, SHAPE_H)), dtype=bool)


def _shapes_of_font(font, hidden: dict, numpy) -> dict:
    """Картинки глифов шрифта сайта по кодовым точкам."""
    from fontTools.pens.basePen import BasePen
    from PIL import Image, ImageDraw

    try:
        glyphs = font.getGlyphSet()
    except Exception:  # noqa: BLE001 — шрифт без контуров бывает
        return {}

    upem = font["head"].unitsPerEm if "head" in font else 1000
    scale = SHAPE_H / float(upem or 1000)
    #: На сколько отрезков разбивать кривую. Цифры круглые: если брать
    #: одни узлы, ноль превратится в четырёхугольник.
    steps = 8

    class Pen(BasePen):
        """Собирает контуры глифа в списки точек."""

        def __init__(self, glyph_set):
            super().__init__(glyph_set)
            self.contours: list[list] = []
            self.points: list = []

        def _moveTo(self, pt):
            self._flush()
            self.points = [self._at(pt)]

        def _lineTo(self, pt):
            self.points.append(self._at(pt))

        def _curveToOne(self, one, two, pt):
            start = self.points[-1] if self.points else self._at(one)
            a, b, c = self._at(one), self._at(two), self._at(pt)
            for step in range(1, steps + 1):
                t = step / steps
                back = 1 - t
                x = (back ** 3 * start[0] + 3 * back * back * t * a[0]
                     + 3 * back * t * t * b[0] + t ** 3 * c[0])
                y = (back ** 3 * start[1] + 3 * back * back * t * a[1]
                     + 3 * back * t * t * b[1] + t ** 3 * c[1])
                self.points.append((x, y))

        def _closePath(self):
            self._flush()

        def _endPath(self):
            self._flush()

        def _flush(self):
            if len(self.points) > 2:
                self.contours.append(self.points)
            self.points = []

        def _at(self, pt):
            # Начало координат у шрифта внизу, у картинки сверху.
            return (pt[0] * scale, SHAPE_H - pt[1] * scale)

    shapes = {}
    for code, name in hidden.items():
        try:
            pen = Pen(glyphs)
            glyphs[name].draw(pen)
            pen._flush()
            if not pen.contours:
                continue
            # Каждый контур рисуется отдельно и накладывается «исключающим
            # или»: у цифр 0, 6, 8 внутри дырка, и залей мы всё разом,
            # ноль стал бы пятном, неотличимым от восьмёрки.
            board = None
            for contour in pen.contours:
                layer = Image.new("1", (SHAPE_H, SHAPE_H), 0)
                ImageDraw.Draw(layer).polygon(contour, fill=1)
                mark = numpy.array(layer, dtype=bool)
                board = mark if board is None else (board ^ mark)
            trimmed = _trim(board, numpy)
            if trimmed is not None:
                shapes[code] = trimmed
        except Exception:  # noqa: BLE001 — один глиф не повод бросать все
            continue
    return shapes


def _shapes_of_reference(path, numpy) -> dict:
    """Картинки обычных цифр, с которыми идёт сверка."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        face = ImageFont.truetype(str(path), int(SHAPE_H * 0.8))
    except Exception:  # noqa: BLE001 — шрифт может не читаться
        return {}

    shapes = {}
    for digit in DIGITS:
        picture = Image.new("1", (SHAPE_H * 2, SHAPE_H * 2), 0)
        try:
            ImageDraw.Draw(picture).text((SHAPE_H, SHAPE_H), digit,
                                         font=face, fill=1, anchor="mm")
        except Exception:  # noqa: BLE001 — знака может не быть
            continue
        trimmed = _trim(numpy.array(picture, dtype=bool), numpy)
        if trimmed is not None:
            shapes[digit] = trimmed
    return shapes


#: Где искать обычные шрифты для сверки. Годится любой с латиницей —
#: цифры есть везде, китайское покрытие здесь не нужно. Список нарочно
#: разношёрстный: гротеск, антиква и моноширинный рисуют цифры по-разному,
#: и чем шире набор образцов, тем меньше шансов, что глиф сайта не найдёт
#: себе пары.
REFERENCE_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/times.ttf",
)

#: Сколько образцов достаточно. Каждая гарнитура — десять отрисовок и
#: десять сравнений на глиф; брать все, что есть в системе, ни к чему.
REFERENCE_LIMIT = 4


def reference_fonts() -> list:
    """Пути к обычным шрифтам. Пусто — сверять не с чем."""
    from pathlib import Path

    found: list = []
    root = Path(__file__).resolve().parent.parent.parent
    for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf",
                 "DejaVuSerif.ttf"):
        near = root / "fonts" / name
        if near.exists():
            found.append(near)
    for path in REFERENCE_PATHS:
        place = Path(path)
        if place.exists():
            found.append(place)
        if len(found) >= REFERENCE_LIMIT:
            break
    return found[:REFERENCE_LIMIT]


def reference_font():
    """Первый из образцовых шрифтов. None — сверять не с чем."""
    found = reference_fonts()
    return found[0] if found else None


# ----------------------------------------------------------------- снаружи

def table_for(family: str, data: bytes | None = None, url: str = "") -> dict:
    """Готовая таблица подстановки. Ключ кэша — хеш файла шрифта."""
    family = str(family or "")

    if not data:
        with _LOCK:
            known_key = _FAMILIES.get(family)
            found = _TABLES.get(known_key) if known_key else None
        if found is not None:
            return found
        raise FontUnavailable(f"Шрифт «{family}» ещё не скачан")

    key = digest_of(data)
    with _LOCK:
        found = _TABLES.get(key)
        if found is not None:
            _FAMILIES[family] = key
            return found

    report = FontReport(family=family, url=url, downloaded=True,
                        size=len(data), digest=key)
    try:
        table = _from_font(data, report)
    except FontUnavailable as exc:
        report.error = str(exc)
        with _LOCK:
            _REPORTS[key] = report
            _FAMILIES[family] = key
        raise

    with _LOCK:
        _TABLES[key] = table
        _REPORTS[key] = report
        _FAMILIES[family] = key
    log.info("Цифровой шрифт «%s» (%s): подстановок %s из %s, способ «%s»",
             family, key, report.mapped, report.private, report.method)
    return table


def report_for(family: str = "", digest: str = "") -> FontReport | None:
    """Отчёт о последнем разборе — по хешу файла либо по семейству."""
    with _LOCK:
        if digest:
            return _REPORTS.get(digest)
        key = _FAMILIES.get(str(family or ""))
        return _REPORTS.get(key) if key else None


def decode(text, table: dict | None) -> str:
    """Строка с восстановленными цифрами.

    Знак, которого нет в таблице, остаётся как есть: пусть лучше в числе
    будет видна дыра, чем оно молча окажется другим числом.
    """
    said = str(text or "")
    if not table:
        return said
    return "".join(table.get(ch, ch) for ch in said)


def number_of(text, table: dict | None):
    """Число из строки со скрытыми цифрами. None — расшифровать не вышло."""
    said = decode(text, table).strip().replace(",", "").replace("\xa0", "")
    return int(said) if said.isdigit() else None


def forget() -> None:
    with _LOCK:
        _TABLES.clear()
        _FAMILIES.clear()
        _REPORTS.clear()


__all__ = ["BY_NAMES", "BY_SHAPE", "FontUnavailable", "decode", "font_of",
           "forget", "number_of", "reference_font", "report_for", "table_for"]
