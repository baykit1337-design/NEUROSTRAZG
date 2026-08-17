"""Расшифровка названий на страницах Фанкью (5.2 ТЗ NEUROSTRAZH).

Сайт подменяет часть иероглифов символами из служебной области Unicode и
рисует их своим шрифтом. Затронуты только три поля: название книги, автор
и описание. Всё остальное — числа, идентификаторы, ссылки — приходит
чистым, поэтому качать книги и следить за движением рейтинга можно и без
расшифровки.

Соответствие «служебный код → настоящий знак» лежит в самом шрифте, в
таблице `cmap`: имена глифов у этого шрифта заданы через кодовую точку
(`uni4E2D`), и по ним знак восстанавливается напрямую. Это основной путь,
и он не требует ничего, кроме `fonttools`.

Когда имена глифов ничего не говорят — а сайт может их обезличить, — есть
запасной путь: сравнение по начертанию. Глифы шрифта сайта рисуются в
картинки 64×64 и сверяются с теми же знаками, отрисованными обычным
шрифтом с полным покрытием. Он требует `Pillow` и `numpy` и эталонного
шрифта, поэтому включается, только когда всё это на месте.

Таблица кэшируется по **хешу файла шрифта**, а не по имени семейства:
имя сайт может оставить прежним, подменив сам файл, и тогда кэш по имени
молча отдавал бы старую таблицу. Имя семейства при этом запоминается
рядом — по нему находится последний разобранный для него файл.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: Служебная область Unicode, куда сайт уводит подменённые знаки.
PRIVATE_FROM = 0xE000
PRIVATE_TO = 0xF8FF

#: Имя семейства и адрес шрифта прямо в стилях страницы.
FAMILY = re.compile(r"font-family\s*:\s*['\"]?([\w-]+)['\"]?", re.I)
SOURCE = re.compile(r"url\(['\"]?(https?://[^)'\"]+\.(?:woff2?|otf|ttf))", re.I)

#: В каком порядке брать форматы одного и того же шрифта.
#:
#: Сайт перечисляет три: `.woff2`, `.woff` и `.otf`. Первым в списке идёт
#: `.woff2`, но он сжат brotli, и без этого пакета `fontTools` его просто
#: не откроет — расшифровка молча не начиналась. У `.otf` распаковки нет
#: вовсе, поэтому берём его первым, а сжатые оставляем на случай, когда
#: `.otf` на странице не перечислен.
FORMAT_ORDER = (".otf", ".ttf", ".woff", ".woff2")

#: Имя глифа вида `uni4E2D` или `u4E2D` — из него и берётся знак.
GLYPH = re.compile(r"^uni?([0-9A-Fa-f]{4,6})$")

_LOCK = threading.Lock()
#: Разобранные таблицы по хешу файла шрифта.
_TABLES: dict[str, dict] = {}
#: Какой файл разбирали последним для этого семейства.
_FAMILIES: dict[str, str] = {}
#: Отчёты о разборе — по тому же ключу, что и таблицы.
_REPORTS: dict[str, "FontReport"] = {}

#: Как называется способ, которым получена таблица.
BY_NAMES = "по именам глифов"
BY_SHAPE = "по начертанию"

#: Насколько картинки должны совпасть, чтобы считать знаки одним и тем же.
#: Порог показывается в отчёте: подбирать его вслепую невозможно.
SHAPE_THRESHOLD = 0.86

#: Размер картинки для сравнения начертаний.
SHAPE_SIZE = 64


class FontUnavailable(Exception):
    """Расшифровать нечем. Не поломка: рейтинг работает и без имён."""


@dataclass
class FontReport:
    """Что случилось при разборе шрифта (2.5 ТЗ).

    «Названия расшифровать не удалось» — не ответ: непонятно, сел ли
    сайт, сменилась ли разметка, не скачался ли файл или дело в способе
    сравнения. Здесь по пунктам, на каком шаге всё встало.
    """

    family: str = ""
    url: str = ""
    #: Скачался ли файл шрифта и сколько в нём байт.
    downloaded: bool = False
    size: int = 0
    #: Хеш файла — он же ключ кэша.
    digest: str = ""
    #: Сколько всего глифов в шрифте и сколько из них служебных.
    glyphs: int = 0
    private: int = 0
    #: Сколько сопоставилось и сколько осталось без пары.
    mapped: int = 0
    unmapped: int = 0
    method: str = ""
    threshold: float = 0.0
    #: Почему не вышло, если не вышло.
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.mapped > 0

    def as_dict(self) -> dict:
        return {
            "family": self.family, "url": self.url,
            "downloaded": self.downloaded, "size": self.size,
            "digest": self.digest, "glyphs": self.glyphs,
            "private": self.private, "mapped": self.mapped,
            "unmapped": self.unmapped, "method": self.method,
            "threshold": round(self.threshold, 2), "error": self.error,
            "ok": self.ok,
        }


def has_secret(text) -> bool:
    """Есть ли в строке подменённые знаки."""
    return any(PRIVATE_FROM <= ord(ch) <= PRIVATE_TO for ch in str(text or ""))


def sources_of(css: str) -> list[str]:
    """Все адреса шрифта со страницы, в порядке предпочтения формата.

    Один и тот же шрифт перечислен в нескольких форматах. Порядок в
    стилях — не наш: там первым идёт самый компактный, а нам нужен самый
    простой в разборе.
    """
    found = SOURCE.findall(css or "")

    def rank(url: str) -> int:
        low = url.lower()
        for index, suffix in enumerate(FORMAT_ORDER):
            if low.endswith(suffix):
                return index
        return len(FORMAT_ORDER)

    # Порядок внутри одного формата сохраняем: `sorted` устойчив.
    return sorted(dict.fromkeys(found), key=rank)


def font_of(css: str) -> tuple[str, str]:
    """Имя семейства и лучший из адресов файла."""
    family = FAMILY.search(css or "")
    found = sources_of(css)
    return (family.group(1) if family else "", found[0] if found else "")


def digest_of(data: bytes) -> str:
    """Отпечаток файла шрифта — он же ключ кэша.

    По имени семейства кэшировать нельзя: сайт может оставить имя
    прежним, подменив файл, и тогда кэш молча отдавал бы старую таблицу.
    """
    return hashlib.sha256(data or b"").hexdigest()[:16]


def _open_font(data: bytes):
    """Разобранный шрифт. Исключения — человеческим языком."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise FontUnavailable(
            "Расшифровка названий требует пакета fonttools: "
            "pip install fonttools") from exc

    import io

    try:
        return TTFont(io.BytesIO(data), lazy=True)
    except Exception as exc:  # noqa: BLE001 — причину показываем целиком
        raise FontUnavailable(f"Шрифт не разобрался: {exc}") from exc


def _from_font(data: bytes, report: FontReport | None = None) -> dict:
    """Таблица подстановки из файла шрифта.

    Сначала по именам глифов — это дёшево и не требует ничего лишнего.
    Не вышло — сравнение по начертанию, если для него всё установлено.
    """
    report = report if report is not None else FontReport()
    font = _open_font(data)

    try:
        cmap = font.getBestCmap()
    except Exception as exc:  # noqa: BLE001 — причину показываем целиком
        raise FontUnavailable(f"В шрифте нет таблицы символов: {exc}") from exc

    private = {code: glyph for code, glyph in cmap.items()
               if PRIVATE_FROM <= code <= PRIVATE_TO}
    report.glyphs = len(cmap)
    report.private = len(private)

    table = {}
    for code, glyph in private.items():
        found = GLYPH.match(str(glyph))
        if found:
            table[chr(code)] = chr(int(found.group(1), 16))

    if table:
        report.method = BY_NAMES
        report.mapped = len(table)
        report.unmapped = len(private) - len(table)
        return table

    # Имена глифов ничего не сказали — пробуем начертание.
    table = _by_shape(font, private, report)
    report.mapped = len(table)
    report.unmapped = len(private) - len(table)
    if not table and not report.error:
        report.error = ("имена глифов обезличены, а сравнение по начертанию "
                        "ничего не подобрало")
    return table


def _by_shape(font, private: dict, report: FontReport) -> dict:
    """Запасной путь: сверка начертаний (2.5 ТЗ).

    Глиф шрифта сайта рисуется в картинку 64×64 и сверяется с тем же
    знаком, отрисованным обычным шрифтом с полным покрытием. Совпало выше
    порога — знак найден.

    Путь необязательный: без Pillow, numpy или эталонного шрифта он
    просто не включается, и об этом честно пишется в отчёте.
    """
    report.method = BY_SHAPE
    report.threshold = SHAPE_THRESHOLD

    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except ImportError:
        report.error = ("сравнение по начертанию требует Pillow: "
                        "pip install pillow numpy")
        return {}
    try:
        import numpy
    except ImportError:
        report.error = ("сравнение по начертанию требует numpy: "
                        "pip install pillow numpy")
        return {}

    reference = reference_font()
    if reference is None:
        report.error = ("нет эталонного шрифта с китайским покрытием — "
                        "положите .ttf рядом с программой в fonts/")
        return {}

    from fontTools.pens.recordingPen import RecordingPen  # noqa: F401

    ours = _shapes_of_font(font, private, numpy)
    if not ours:
        report.error = "глифы шрифта не нарисовались"
        return {}

    theirs = _shapes_of_reference(reference, numpy)
    if not theirs:
        report.error = "эталонные знаки не нарисовались"
        return {}

    table = {}
    for code, picture in ours.items():
        best, score = "", 0.0
        for sign, sample in theirs.items():
            near = _likeness(picture, sample, numpy)
            if near > score:
                best, score = sign, near
        if best and score >= SHAPE_THRESHOLD:
            table[chr(code)] = best
    return table


def _likeness(one, two, numpy) -> float:
    """Насколько две картинки похожи: доля совпавших точек."""
    return float((one == two).mean())


def _shapes_of_font(font, private: dict, numpy) -> dict:
    """Картинки глифов шрифта сайта по кодовым точкам."""
    from PIL import Image, ImageDraw

    try:
        glyphs = font.getGlyphSet()
    except Exception:  # noqa: BLE001 — шрифт без контуров бывает
        return {}

    from fontTools.pens.basePen import BasePen

    upem = font["head"].unitsPerEm if "head" in font else 1000
    scale = SHAPE_SIZE / float(upem or 1000)

    class Pen(BasePen):
        """Рисует контуры глифа прямо в картинку."""

        def __init__(self, glyph_set, draw):
            super().__init__(glyph_set)
            self.draw = draw
            self.points: list = []

        def _moveTo(self, pt):
            self.points = [self._at(pt)]

        def _lineTo(self, pt):
            self.points.append(self._at(pt))

        def _curveToOne(self, a, b, pt):
            self.points.append(self._at(pt))

        def _closePath(self):
            if len(self.points) > 2:
                self.draw.polygon(self.points, fill=1)
            self.points = []

        def _at(self, pt):
            # Начало координат у шрифта внизу, у картинки сверху.
            x = pt[0] * scale
            y = SHAPE_SIZE - pt[1] * scale - SHAPE_SIZE * 0.12
            return (x, y)

    shapes = {}
    for code, name in private.items():
        try:
            picture = Image.new("1", (SHAPE_SIZE, SHAPE_SIZE), 0)
            pen = Pen(glyphs, ImageDraw.Draw(picture))
            glyphs[name].draw(pen)
            pen._closePath()
            shapes[code] = numpy.array(picture, dtype=bool)
        except Exception:  # noqa: BLE001 — один глиф не повод бросать все
            continue
    return shapes


def _shapes_of_reference(path, numpy) -> dict:
    """Картинки частых иероглифов, отрисованных обычным шрифтом."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        face = ImageFont.truetype(str(path), int(SHAPE_SIZE * 0.86))
    except Exception:  # noqa: BLE001 — эталон может не читаться
        return {}

    shapes = {}
    for sign in common_signs():
        picture = Image.new("1", (SHAPE_SIZE, SHAPE_SIZE), 0)
        try:
            ImageDraw.Draw(picture).text((SHAPE_SIZE // 2, SHAPE_SIZE // 2),
                                         sign, font=face, fill=1, anchor="mm")
        except Exception:  # noqa: BLE001 — знака может не быть в шрифте
            continue
        shapes[sign] = numpy.array(picture, dtype=bool)
    return shapes


#: Где искать эталонный шрифт с китайским покрытием. Свой каталог первым:
#: в системе такого шрифта может не быть вовсе.
REFERENCE_DIRS = ("fonts",)
REFERENCE_NAMES = (
    "NotoSansSC-Regular.otf", "NotoSansCJKsc-Regular.otf",
    "NotoSerifCJKsc-Regular.otf", "SourceHanSansSC-Regular.otf",
)
SYSTEM_DIRS = (
    "/usr/share/fonts/opentype/noto", "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/opentype", "/usr/share/fonts/truetype",
    "/Library/Fonts", "C:/Windows/Fonts",
)


def reference_font():
    """Путь к эталонному шрифту. None — сравнивать не с чем."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    for folder in REFERENCE_DIRS:
        for name in REFERENCE_NAMES:
            path = root / folder / name
            if path.exists():
                return path

    for folder in SYSTEM_DIRS:
        place = Path(folder)
        if not place.is_dir():
            continue
        for name in REFERENCE_NAMES:
            path = place / name
            if path.exists():
                return path
    return None


#: Частые иероглифы для сверки начертаний. Полный набор здесь не нужен:
#: подменяются знаки из названий книг, а они берутся из этого же ряда.
COMMON = (
    "的一是不了人我在有他这为之大来以个中上们到说国和地也子时道年得就那"
    "要下出生自己面前头天可用小天里过日种行方多定家法进主上手民对十机重"
    "力三又心战二问但身长儿回位分爱老因很给名法间斯知世什两次使身者被高"
    "已亲其进此话常与活正感见明问力理尔点文几定本公特做外孩相西果走将月"
    "十实向声车全信重三机工物气每并别真打太新比才便夫再书部水像眼等体却"
    "加电主界门利海受听表德少克代员许稜先口由死安写性马光白或住难望教命"
    "花结乐色更拉东神记处让母父应直字场平报友关放至张认接告入笑内英军候"
    "民岁往何度山觉路带万男边风解叫任金快原吃妈变通师立象数四失满战远格"
)


def common_signs() -> tuple:
    """Эталонный набор знаков, без повторов и в стабильном порядке."""
    seen: list[str] = []
    for sign in COMMON:
        if sign not in seen:
            seen.append(sign)
    return tuple(seen)


def table_for(family: str, data: bytes | None = None,
              url: str = "") -> dict:
    """Готовая таблица подстановки.

    Ключ кэша — хеш самого файла: имя семейства сайт может оставить
    прежним, подменив шрифт, и кэш по имени молча отдавал бы старую
    таблицу. Уже разобранный файл второй раз не разбирается: на странице
    рейтинга сто книг, и делать это на каждую было бы расточительно.
    """
    family = str(family or "")

    if not data:
        # Файла нет — вдруг для этого семейства мы уже что-то разбирали.
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
        with _LOCK:
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
    log.info("Шрифт «%s» (%s): подстановок %s из %s, способ «%s»",
             family, key, report.mapped, report.private, report.method)
    return table


def report_for(family: str = "", digest: str = "") -> FontReport | None:
    """Отчёт о последнем разборе — по хешу файла либо по семейству."""
    with _LOCK:
        if digest:
            return _REPORTS.get(digest)
        key = _FAMILIES.get(str(family or ""))
        return _REPORTS.get(key) if key else None


def known(family: str) -> bool:
    """Разбирали ли уже шрифт этого семейства."""
    with _LOCK:
        key = _FAMILIES.get(str(family or ""))
        return bool(key) and key in _TABLES


def decode(text, table: dict | None) -> str:
    """Возвращает строку с восстановленными знаками.

    Знак, которого нет в таблице, остаётся как есть: показать строку с
    одним пропуском лучше, чем не показать вовсе.
    """
    text = str(text or "")
    if not table or not has_secret(text):
        return text
    return "".join(table.get(ch, ch) for ch in text)


def forget() -> None:
    with _LOCK:
        _TABLES.clear()
        _FAMILIES.clear()
        _REPORTS.clear()
