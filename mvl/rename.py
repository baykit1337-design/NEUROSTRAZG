"""Переименование и деление глав.

Имена от WebToEpub приходят вперемешку: порядковый номер файла не совпадает
с номером главы, а первой идёт служебная «Информация». Здесь имя
раскладывается на части, собирается заново по галочкам, а сами главы при
необходимости режутся на несколько файлов.

Оригиналы не трогаются никогда — результат пишется в новую папку.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field, replace
from pathlib import Path

from core import formats, naming
#: Под именем `Chapter` в этом модуле живёт своя запись — файл на диске.
#: Ядровая глава нужна только для записи, поэтому берётся под своим именем.
from core.models import Chapter as OutChapter

from .booksplit import Cancelled, safe_name
from .source import read_paragraphs as read_source_paragraphs
from .textprep import SCENE_BREAK, PrepOptions, prepare, to_text
from .word import Style, split_paragraphs

log = logging.getLogger(__name__)

#: Что умеет прочитать ядро. Свой список здесь держать нельзя: добавив
#: формат в core, пришлось бы вспоминать и про эту строку.
READABLE = formats.READABLE

# Разбор и сборка имён живут только в core/naming.py. Здесь — имена, под
# которыми к ним обращается остальной код вкладки.
CHAPTER_WORD = naming.CHAPTER_WORD
SEQ_RE = naming.SEQ_RE
NUMBER_RE = naming.NUMBER_RE
DEFAULT_PATTERN = naming.DEFAULT_PATTERN
DEFAULT_PREFIX = naming.DEFAULT_PREFIX
DEFAULT_SEPARATOR = naming.DEFAULT_SEPARATOR
SEPARATORS = naming.SEPARATORS
FORBIDDEN_MAP = naming.FORBIDDEN_MAP

NameParts = naming.NameParts
safe_filename = naming.safe_filename
has_forbidden = naming.has_forbidden


class RenameError(Exception):
    """Что-то не так с папкой или параметрами — показываем пользователю."""


class NameCollision(RenameError):
    """Два файла претендуют на одно имя."""


def parse_name(stem: str, pattern: str | None = None) -> NameParts:
    """Разбор имени из ядра, с ошибкой в терминах вкладки.

    Своё регулярное выражение вводит человек, и сломать его несложно.
    Маршрут ловит RenameError, поэтому переводим ошибку разбора в неё —
    иначе битый шаблон уходит в 500 вместо понятного сообщения.
    """
    try:
        return naming.parse(stem, pattern)
    except naming.NamingError as exc:
        raise RenameError(str(exc)) from exc


@dataclass
class Chapter:
    """Одна глава: файл на диске плюс то, что вышло из его имени."""

    path: Path
    parts_of_name: NameParts
    #: Объём в знаках. `None` — файл ещё не читали (см. `HEAVY`).
    size: int | None = 0
    part: int | None = None
    text_parts: list[str] = field(default_factory=list)
    #: Прочитано ли тело файла. У тяжёлых форматов при показе списка —
    #: нет: читаются они только тогда, когда текст действительно нужен.
    loaded: bool = True
    #: Номер, присвоенный по порядку в папке, когда в имени числа не было.
    assigned: int | None = None
    #: Разбор вызывает сомнения: номера нет или он выбивается из диапазона.
    #: Строка помечается значком, но из списка не исчезает — решает человек.
    suspect: bool = False
    #: Почему помечена — текст для подсказки в интерфейсе.
    suspect_reason: str = ""

    @property
    def number(self) -> int | None:
        """Номер из имени, а если его там не было — присвоенный по порядку."""
        if self.parts_of_name.number is not None:
            return self.parts_of_name.number
        return self.assigned

    @property
    def title(self) -> str:
        return self.parts_of_name.title

    def body(self) -> list[str]:
        """Абзацы главы. Тяжёлый файл читается здесь, и только раз."""
        if not self.loaded:
            try:
                self.text_parts = read_paragraphs(self.path)
            except Exception as exc:  # noqa: BLE001 — один файл не рушит папку
                log.warning("Не прочитан %s: %s", self.path.name, exc)
                self.text_parts = []
            self.size = sum(len(p) for p in self.text_parts)
            self.loaded = True
        return self.text_parts

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "number": self.number,
            "part": self.part,
            "title": self.title,
            "size": self.size,
            "suspect": self.suspect,
            "suspect_reason": self.suspect_reason,
            # Номер не из имени, а присвоен по порядку в папке.
            "assigned": self.parts_of_name.number is None,
        }


#: Форматы, чтение которых стоит дорого. Замерено на главах по сорок
#: абзацев: .docx — 46 мс на файл, .rtf — 13 мс, всё остальное меньше
#: двух. На папке в пятьсот глав это разница между «сразу» и «полминуты
#: перед пустым экраном» — а список строится по именам, текст ему не
#: нужен. Поэтому такие файлы читаются лениво, к моменту записи.
HEAVY = frozenset({".docx", ".rtf"})


def read_paragraphs(path: Path) -> list[str]:
    """Абзацы файла — через общий модуль чтения (он же понимает epub)."""
    return read_source_paragraphs(path)


def scan(folder: str | Path, pattern: str | None = None) -> list[Chapter]:
    """Читает папку и раскладывает имена. Сортировка — по номеру главы.

    Ни один текстовый файл из списка не выпадает. Файлу без числа в имени
    номер присваивается по порядку в папке, а сомнительный разбор
    помечается значком «проверьте» — но галочка остаётся доступной, снять
    её может только человек.
    """
    directory = Path(folder).expanduser()
    if not directory.is_dir():
        raise RenameError(f"Папка не найдена: {directory}")

    chapters: list[Chapter] = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in READABLE:
            continue
        parts = parse_name(path.stem, pattern)

        # Тяжёлые форматы при показе списка не читаем: разбор .docx стоит
        # 46 мс на файл, и на пятистах это полминуты ожидания перед
        # пустым экраном — а список строится по именам, текст ему не
        # нужен вовсе. Прочитаем, когда дело дойдёт до записи.
        if path.suffix.lower() in HEAVY:
            chapters.append(
                Chapter(path=path, parts_of_name=parts, part=parts.part,
                        size=None, loaded=False)
            )
            continue

        try:
            paragraphs = read_paragraphs(path)
        except Exception as exc:
            log.warning("Не прочитан %s: %s", path.name, exc)
            paragraphs = []
        chapters.append(
            Chapter(
                path=path,
                parts_of_name=parts,
                part=parts.part,
                size=sum(len(p) for p in paragraphs),
                text_parts=paragraphs,
            )
        )

    if not chapters:
        raise RenameError(
            "В папке нет файлов поддерживаемых форматов: "
            + ", ".join(READABLE)
        )

    chapters = sort_chapters(chapters)
    _mark(chapters)
    return chapters


def _mark(chapters: list[Chapter]) -> None:
    """Присваивает номера безномерным и помечает сомнительный разбор."""
    outliers = naming.suspects(c.parts_of_name.number for c in chapters)

    # Номер по порядку в папке — только тем, у кого числа в имени не было.
    order = 0
    for chapter in chapters:
        if chapter.parts_of_name.number is None:
            order += 1
            chapter.assigned = order
            chapter.suspect = True
            chapter.suspect_reason = (
                f"числа в имени нет, присвоен номер {order} по порядку в папке")
        elif chapter.parts_of_name.number in outliers:
            chapter.suspect = True
            chapter.suspect_reason = (
                f"номер {chapter.parts_of_name.number} выбивается из "
                f"общего диапазона — проверьте разбор")


def sort_chapters(chapters: list[Chapter]) -> list[Chapter]:
    """По номеру главы; файлы без номера в имени — в конец, но не теряются."""
    return sorted(
        chapters,
        key=lambda c: (
            c.parts_of_name.number is None,
            c.parts_of_name.number or 0,
            c.part if c.part is not None else 0,
            c.parts_of_name.seq if c.parts_of_name.seq is not None else 0,
            c.path.name.lower(),
        ),
    )


# --------------------------------------------------------------- сборка имени


NameFormat = naming.NameFormat
build_name = naming.build


# ------------------------------------------------------------ деление на части


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


# ------------------------------------------------------------------- план работ


@dataclass
class PlanRow:
    """Строка предпросмотра: что было и что станет."""

    source: str
    old_name: str
    new_name: str
    number: int | None
    part: int | None
    title: str
    size: int
    #: Разбор вызывает сомнения — строка помечается, но переименовывается.
    suspect: bool = False
    paragraphs: list[str] = field(default_factory=list)
    #: Лежит ли текст здесь. `False` — файл тяжёлый и ещё не читан, его
    #: возьмут с диска в момент записи. Отличать это от «глава пустая»
    #: обязательно: иначе пустой файл затирал бы содержимое исходного.
    loaded: bool = True

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "number": self.number,
            "part": self.part,
            "title": self.title,
            "size": self.size,
            "suspect": self.suspect,
        }


@dataclass
class RenameReport:
    output_dir: str = ""
    written: int = 0
    failed: int = 0
    failed_files: list[str] = field(default_factory=list)
    total: int = 0

    def as_dict(self) -> dict:
        return {
            "output_dir": self.output_dir,
            "written": self.written,
            "failed": self.failed,
            "failed_files": self.failed_files,
            "total": self.total,
        }


def make_plan(
    chapters: list[Chapter],
    fmt: NameFormat,
    splits: dict[str, int] | None = None,
    renumber_from: int | None = None,
    chosen: set[str] | None = None,
) -> list[PlanRow]:
    """Строит предпросмотр «старое имя → новое имя».

    `splits` — сколько частей сделать из главы, ключ это путь к файлу.
    `renumber_from` — нумеровать заново подряд, игнорируя номер из имени.
    `chosen` — пути отмеченных галочками файлов; None означает «все».

    Сплошная нумерация растворяет старые части. Книга, поделённая на
    151.1, 151.2, 151.3, — это триста файлов, и при нумерации подряд
    каждый становится отдельной главой: 151, 152, 153. Оставлять при
    этом прежний номер части нельзя, иначе выходит «Глава 151.1, Глава
    152.1» — число, которое уже ничего не значит. Часть, нарезанная
    здесь и сейчас, — другое дело: она остаётся, без неё куски главы
    получили бы одно имя и затёрли друг друга.

    Понятия «служебный файл» нет: из списка сам по себе не выпадает ни один
    файл. Что не нужно, человек снимает галочкой.
    """
    splits = splits or {}
    rows: list[PlanRow] = []
    next_number = renumber_from

    for chapter in sort_chapters(chapters):
        if chosen is not None and str(chapter.path) not in chosen:
            continue

        if renumber_from is not None:
            number = next_number
            next_number += 1
        else:
            number = chapter.number

        count = max(1, int(splits.get(str(chapter.path), 1) or 1))
        if count > 1:
            # Резать без текста нельзя — эту главу читаем сейчас. Их
            # обычно единицы, а не вся папка.
            pieces = split_into_parts(chapter.body(), count)
            # У разрезанной главы номер части в имени обязателен: без него
            # все части получат одно имя и затрут друг друга.
            part_fmt = fmt if fmt.part else replace(fmt, part=True)
            for index, piece in enumerate(pieces, 1):
                rows.append(
                    PlanRow(
                        source=str(chapter.path),
                        old_name=chapter.path.name,
                        new_name=build_name(number, index, chapter.title, part_fmt),
                        number=number, part=index, title=chapter.title,
                        size=sum(len(p) for p in piece), suspect=chapter.suspect,
                        paragraphs=piece,
                    )
                )
        else:
            # Нумеруем подряд — прежняя часть растворяется в новом номере.
            part = None if renumber_from is not None else chapter.part
            rows.append(
                PlanRow(
                    source=str(chapter.path),
                    old_name=chapter.path.name,
                    new_name=build_name(number, part, chapter.title, fmt),
                    number=number, part=part, title=chapter.title,
                    size=chapter.size, suspect=chapter.suspect,
                    # Текст не тянем: если файл ещё не читан, его прочтёт
                    # запись. Предпросмотр имён в тексте не нуждается.
                    paragraphs=chapter.text_parts,
                    loaded=chapter.loaded,
                )
            )

    return rows


def find_collisions(rows: list[PlanRow], suffix: str = "txt") -> list[str]:
    """Ищет одинаковые имена в плане.

    Совпадение имён — ошибка логики, а не повод дописать «(2)»: именно так
    вторая часть главы затирала первую.
    """
    seen: dict[str, str] = {}
    clashes: list[str] = []
    for row in rows:
        name = f"{safe_filename(row.new_name)}.{suffix}".lower()
        if name in seen:
            clashes.append(f"«{row.new_name}.{suffix}» — из {seen[name]} и {row.old_name}")
        else:
            seen[name] = row.old_name
    return clashes


def apply_plan(
    rows: list[PlanRow],
    output_dir: Path,
    fmt: str = "txt",
    style: Style | None = None,
    prep: PrepOptions | None = None,
    headings: bool = True,
    encoding: str = "utf-8",
    on_progress=None,
    cancel: threading.Event | None = None,
) -> RenameReport:
    """Пишет результат в новую папку. Оригиналы не трогаются.

    Сбой на одном файле не останавливает остальные, но совпадение имён
    останавливает всё: иначе файлы молча затрут друг друга.
    """
    # Список форматов один на всю программу — тот же, что у «Разбить» и
    # «Объединить». Раньше эта вкладка писала файлы сама и умела только
    # два формата, из-за чего в одной программе их было три разных набора.
    suffix = str(fmt or "txt").lstrip(".").lower()
    if f".{suffix}" not in formats.WRITABLE:
        suffix = "txt"
    clashes = find_collisions(rows, suffix)
    if clashes:
        raise NameCollision(
            "Совпадают имена файлов, запись остановлена:\n" + "\n".join(clashes[:10])
        )

    prep = prep or PrepOptions()
    output_dir.mkdir(parents=True, exist_ok=True)
    report = RenameReport(output_dir=str(output_dir), total=len(rows))

    for index, row in enumerate(rows, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled()

        name = f"{safe_filename(row.new_name) or f'{index:04d}'}.{suffix}"
        try:
            target = output_dir / name
            # Тяжёлый файл до сих пор не читан — вот теперь он и нужен.
            # Список глав строится по именам, и заставлять человека
            # ждать разбора всей папки ради предпросмотра незачем.
            paragraphs = (list(row.paragraphs) if row.loaded
                          else read_paragraphs(Path(row.source)))
            # Пишем через общий слой: он знает все форматы и применяет ту
            # же подготовку текста, что и остальные пути вывода.
            formats.write(
                target,
                [OutChapter(number=row.number, part=row.part, title=row.title,
                            paragraphs=paragraphs, source=row.source)],
                prep=prep, style=style, headings=headings, encoding=encoding,
            )
            report.written += 1
        except Exception as exc:
            log.warning("Не записан %s: %s", name, exc)
            report.failed += 1
            report.failed_files.append(f"{name}: {type(exc).__name__}: {exc}")

        if on_progress:
            on_progress(index, len(rows))

    return report
