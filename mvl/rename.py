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
    size: int = 0
    part: int | None = None
    text_parts: list[str] = field(default_factory=list)

    @property
    def number(self) -> int | None:
        return self.parts_of_name.number

    @property
    def title(self) -> str:
        return self.parts_of_name.title

    @property
    def service(self) -> bool:
        return self.parts_of_name.service

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "number": self.number,
            "part": self.part,
            "title": self.title,
            "size": self.size,
            "service": self.service,
        }


def read_paragraphs(path: Path) -> list[str]:
    """Абзацы файла — через общий модуль чтения (он же понимает epub)."""
    return read_source_paragraphs(path)


def scan(folder: str | Path, pattern: str | None = None) -> list[Chapter]:
    """Читает папку и раскладывает имена. Сортировка — по номеру главы."""
    directory = Path(folder).expanduser()
    if not directory.is_dir():
        raise RenameError(f"Папка не найдена: {directory}")

    chapters: list[Chapter] = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in READABLE:
            continue
        parts = parse_name(path.stem, pattern)
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
        raise RenameError("В папке нет файлов .txt, .md или .docx")

    return sort_chapters(chapters)


def sort_chapters(chapters: list[Chapter]) -> list[Chapter]:
    """Сначала главы по номеру, служебные — в конец, но не теряются."""
    return sorted(
        chapters,
        key=lambda c: (
            c.service,
            c.number if c.number is not None else 0,
            c.part if c.part is not None else 0,
            c.parts_of_name.seq if c.parts_of_name.seq is not None else 0,
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
    service: bool
    paragraphs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "old_name": self.old_name,
            "new_name": self.new_name,
            "number": self.number,
            "part": self.part,
            "title": self.title,
            "size": self.size,
            "service": self.service,
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
    skip_service: bool = True,
) -> list[PlanRow]:
    """Строит предпросмотр «старое имя → новое имя».

    `splits` — сколько частей сделать из главы, ключ это путь к файлу.
    `renumber_from` — нумеровать заново подряд, игнорируя номер из имени.
    """
    splits = splits or {}
    rows: list[PlanRow] = []
    next_number = renumber_from

    for chapter in sort_chapters(chapters):
        if chapter.service and skip_service:
            continue

        if chapter.service:
            # Служебный файл переименованию не поддаётся — оставляем как есть.
            rows.append(
                PlanRow(
                    source=str(chapter.path),
                    old_name=chapter.path.name,
                    new_name=safe_filename(chapter.path.stem),
                    number=None, part=None, title=chapter.title,
                    size=chapter.size, service=True,
                    paragraphs=chapter.text_parts,
                )
            )
            continue

        if renumber_from is not None:
            number = next_number
            next_number += 1
        else:
            number = chapter.number

        count = max(1, int(splits.get(str(chapter.path), 1) or 1))
        if count > 1:
            pieces = split_into_parts(chapter.text_parts, count)
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
                        size=sum(len(p) for p in piece), service=False,
                        paragraphs=piece,
                    )
                )
        else:
            rows.append(
                PlanRow(
                    source=str(chapter.path),
                    old_name=chapter.path.name,
                    new_name=build_name(number, chapter.part, chapter.title, fmt),
                    number=number, part=chapter.part, title=chapter.title,
                    size=chapter.size, service=False,
                    paragraphs=chapter.text_parts,
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
    on_progress=None,
    cancel: threading.Event | None = None,
) -> RenameReport:
    """Пишет результат в новую папку. Оригиналы не трогаются.

    Сбой на одном файле не останавливает остальные, но совпадение имён
    останавливает всё: иначе файлы молча затрут друг друга.
    """
    suffix = fmt if fmt in ("txt", "docx") else "txt"
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
            # Та же подготовка текста, что и в остальных путях вывода.
            blocks = prepare(row.paragraphs, row.title, prep)
            if suffix == "docx":
                from .word import add_blocks, new_document

                document = new_document(style)
                add_blocks(document, blocks, style, prep)
                document.save(str(target))
            else:
                target.write_text(to_text(blocks) + "\n", encoding="utf-8")
            report.written += 1
        except Exception as exc:
            log.warning("Не записан %s: %s", name, exc)
            report.failed += 1
            report.failed_files.append(f"{name}: {type(exc).__name__}: {exc}")

        if on_progress:
            on_progress(index, len(rows))

    return report
