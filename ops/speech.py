"""Прямая речь в кавычках — прямой речью через тире.

Перевод отдаёт реплики так, как они стояли в оригинале, — в кавычках:

    «Я-я в порядке...♥»
    «Быстрее».

По-русски прямая речь пишется через тире:

    — Я-я в порядке...♥
    — Быстрее.

Правится это иначе как вручную никак: реплик в книге тысячи, а простой
заменой «« → — » кавычки слетят и с названий, и с цитат внутри строки.

Отсюда правило, узкое нарочно: **реплика — это абзац, начинающийся с
кавычки**. Кавычка в середине строки остаётся кавычкой:

    Он читал «Войну и мир».      ← не трогаем, абзац начат не с кавычки
    Он сказал: «Быстрее».        ← тоже: это не реплика, а слова автора

Закрывающая кавычка снимается только своя — первая после открывающей.
Что стояло за ней, остаётся на месте:

    «Быстрее».                → — Быстрее.
    «Что?» — спросил он.      → — Что? — спросил он.

Ничего не переписывает само: сначала показывает каждую строку «до и
после», а пишет — рядом с исходником, новым файлом.

Формат файла роли не играет. Работа живёт в «Инструментах» и берёт то же,
что и остальные работы там: файлы или папку любого читаемого формата —
`.docx`, `.txt`, `.rtf`, `.odt`, `.fb2`, `.md`. Речь в кавычках попадается
не только в собранной книге: чаще всего её и правят в вордовском файле,
до всякой сборки.

Готовая книга для загрузчика — особый случай, и он разобран отдельно.
Прочитай мы её обычным читателем, строки-заголовки `# [Название :|: …]`
стали бы обычным текстом, а при записи первая из них поехала бы. Поэтому
такую книгу разбирает `ops/mdbook`, и заголовки возвращаются на место
дословно.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from core import formats, naming
from core.models import OpReport

from . import mdbook
from .base import Progress, collect_files, spread

#: Знак прямой речи. Тире, а не дефис и не минус: короткий знак на этом
#: месте загрузчик покажет как дефис посреди строки.
DASH = "—"

#: Пары кавычек, за которыми может прятаться реплика. Ёлочки — главное:
#: так речь приходит от переводчика. Лапки и прямая кавычка попадаются в
#: сливах, а правило для них ровно то же.
#:
#: У прямой кавычки открывающая и закрывающая — один знак; поиск «первой
#: закрывающей после открывающей» это переживает.
QUOTES = (("«", "»"), ("“", "”"), ('"', '"'))

#: Сколько строк показывать в списке «до и после». Книга бывает на
#: полторы тысячи глав, а решение принимают по первым двум десяткам.
SHOW = 60


def dashed(line: str) -> str:
    """Одна строка. Не реплика — вернётся как была.

    Одна на осмотр и на запись: разойдись они, и в списке значилось бы
    одно, а в книгу легло бы другое.
    """
    text = str(line or "")
    body = text.strip()
    for opening, closing in QUOTES:
        if not body.startswith(opening):
            continue
        at = body.find(closing, len(opening))
        if at < 0:
            # Кавычка не закрыта. Речь это или нет — непонятно, а
            # догадка испортила бы строку молча.
            return text
        inside = body[len(opening):at].strip()
        if not inside:
            return text
        rest = body[at + len(closing):]
        return f"{DASH} {inside}{rest}"
    return text


@dataclass
class Change:
    """Одна строка до и после. Показывается целиком: решение принимают
    по тексту реплики, а не по её длине."""

    chapter: str = ""
    before: str = ""
    after: str = ""
    file: str = ""

    def as_dict(self) -> dict:
        return {"chapter": self.chapter, "before": self.before,
                "after": self.after, "file": self.file}


@dataclass
class Report:
    chapters: int = 0
    lines: int = 0
    changed: int = 0
    samples: list[Change] = field(default_factory=list)
    #: Сколько файлов просмотрено и какие не открылись. Работа берёт
    #: папку целиком, и сбой одного файла не повод бросать остальные.
    files: int = 0
    unreadable: list = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """Речи в кавычках нет — переписывать нечего."""
        return not self.changed

    def summary(self) -> str:
        if self.clean:
            return f"Глав: {self.chapters} · речи в кавычках не нашлось"
        return (f"Глав: {self.chapters} · реплик в кавычках: {self.changed}"
                f" из {self.lines} строк")

    def as_dict(self) -> dict:
        return {"chapters": self.chapters, "lines": self.lines,
                "changed": self.changed, "clean": self.clean,
                "files": self.files,
                "unreadable": self.unreadable,
                "summary": self.summary(),
                "samples": [change.as_dict() for change in self.samples],
                "more": max(0, self.changed - len(self.samples))}


def inspect(chapters) -> Report:
    """Что изменится. `chapters` — пары «заголовок, абзацы»."""
    report = Report()
    for title, paragraphs in chapters:
        report.chapters += 1
        for line in paragraphs:
            report.lines += 1
            made = dashed(line)
            if made == line:
                continue
            report.changed += 1
            if len(report.samples) < SHOW:
                report.samples.append(Change(title, line, made))
    return report


def rewrite(chapters) -> tuple[list[tuple[str, list[str]]], int]:
    """Главы с речью через тире. Возвращает главы и число правок.

    Исходные главы не меняются: переписанное всегда пишется рядом, а не
    поверх.
    """
    made: list[tuple[str, list[str]]] = []
    count = 0
    for title, paragraphs in chapters:
        kept: list[str] = []
        for line in paragraphs:
            fresh = dashed(line)
            count += fresh != line
            kept.append(fresh)
        made.append((title, kept))
    return made, count


# ------------------------------------------------------------ по файлам


def _book(path: Path):
    """Главы книги для загрузчика — или `None`, если это не она.

    Отличать надо до чтения обычным читателем: у такой книги строки
    `# [Название :|: …]` не текст, а заголовки, и вернуть их надо
    дословно, вместе с ценой и томом.
    """
    if path.suffix.lower() not in (".md", ".markdown"):
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lead, chapters = mdbook.read_book(text)
    return (lead, chapters) if chapters else None


def _pieces(path: Path) -> list[tuple[str, list[str]]]:
    """Файл — в пары «заголовок, абзацы», как их берёт `inspect`."""
    book = _book(path)
    if book is not None:
        return [(head.title, mdbook.paragraphs_of(lines))
                for head, lines in book[1]]
    return [(chapter.title, list(chapter.paragraphs))
            for chapter in formats.read(path)]


def look(targets, progress: Progress | None = None) -> Report:
    """Что изменится в выбранных файлах. Ничего не пишет."""
    progress = progress or Progress()
    report = Report()
    files = collect_files(targets)
    report.files = len(files)

    for index, path in enumerate(files, 1):
        progress.check()
        try:
            pieces = _pieces(path)
        except Exception as exc:  # noqa: BLE001 — сбой файла не повод бросать
            report.unreadable.append(f"{path.name}: {type(exc).__name__}: {exc}")
            pieces = []
        # Считает всё тот же `inspect`: расщепи мы счёт на два, в списке
        # значилось бы одно, а в файл легло бы другое.
        piece = inspect(pieces)
        report.chapters += piece.chapters
        report.lines += piece.lines
        report.changed += piece.changed
        for change in piece.samples:
            if len(report.samples) < SHOW:
                change.file = path.name
                report.samples.append(change)
        progress.step(index, len(files), f"Смотрим {path.name}")
    return report


def run(targets, output_dir, out_format: str = "", encoding: str = "utf-8",
        progress: Progress | None = None) -> OpReport:
    """Переписывает речь через тире в новую папку. Оригиналы не трогает."""
    progress = progress or Progress()
    output_dir = Path(str(output_dir)).expanduser()
    report = OpReport(output=str(output_dir))

    files = collect_files(targets)
    if not files:
        raise ValueError("Не нашлось ни одного файла.")
    output_dir.mkdir(parents=True, exist_ok=True)
    report.total = len(files)

    # Имена считаем здесь, до раскладки по ядрам: они зависят от того,
    # что уже занято, и не должны зависеть от того, кто какой файл
    # успел сделать первым.
    used: set[str] = set()
    jobs = []
    for path in files:
        book = _book(path)
        suffix = ".md" if book is not None else (out_format or path.suffix or ".txt")
        jobs.append((str(path), str(_free(output_dir, path.stem, suffix, used)),
                     encoding))

    made = spread(_one_file, jobs, progress,
                  heavy=any(formats.is_heavy(Path(target).suffix)
                            for _, target, _ in jobs),
                  note="Файл")

    changed = 0
    for path, done in zip(files, made):
        count, trouble = done
        if trouble:
            report.fail(path.name, "правка", trouble)
        else:
            report.written += 1
            changed += count

    report.extra["changed"] = changed
    return report


def _one_file(job) -> tuple:
    """Один файл: «сколько строк переписано, что стряслось».

    Функция уровня модуля — иначе её не отправить в другой процесс; беда
    возвращается значением по той же причине.
    """
    source, target, encoding = job
    try:
        return _one(Path(source), Path(target), encoding), ""
    except Exception as exc:  # noqa: BLE001 — сбой файла не повод бросать
        return 0, f"{type(exc).__name__}: {exc}"


def _one(path: Path, target: Path, encoding: str) -> int:
    """Один файл. Возвращает число переписанных строк."""
    book = _book(path)

    if book is not None:
        # У книги для загрузчика заголовки возвращаются дословно: цена и
        # том живут в той же строке, и пересобрать её значило бы поменять
        # книге цену.
        lead, chapters = book
        made, count = rewrite([(head.title, mdbook.paragraphs_of(lines))
                               for head, lines in chapters])
        rebuilt = [(head, mdbook.lines_of(paragraphs))
                   for (head, _), (_, paragraphs) in zip(chapters, made)]
        target.write_text(mdbook.write_book(rebuilt, lead), encoding="utf-8")
        return count

    read = formats.read(path)
    made, count = rewrite([(chapter.title, list(chapter.paragraphs))
                           for chapter in read])
    # Копия, а не правка на месте: прочитанное — не наше, и менять его
    # молча нельзя, даже если после нас им никто не пользуется.
    fresh = [replace(chapter, paragraphs=paragraphs)
             for chapter, (_, paragraphs) in zip(read, made)]

    formats.write(target, fresh, headings=True, encoding=encoding,
                  title=fresh[0].title if fresh else path.stem)
    return count


def _free(output_dir: Path, stem: str, suffix: str, used: set) -> Path:
    """Имя, которое ещё не занято в этой работе.

    Папку берут целиком, а в ней могут лежать «глава.txt» и «глава.docx»:
    приведи мы оба к одному формату — второй затёр бы первый.
    """
    stem = naming.safe_filename(stem) or "файл"
    name = f"{stem}{suffix}"
    number = 2
    while name.lower() in used:
        name = f"{stem} ({number}){suffix}"
        number += 1
    used.add(name.lower())
    return output_dir / name


__all__ = ["DASH", "QUOTES", "SHOW", "Change", "Report", "dashed", "inspect",
           "look", "rewrite", "run"]
