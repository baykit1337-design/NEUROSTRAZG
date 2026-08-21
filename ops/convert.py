"""Перегон файлов из формата в формат. Один файл на входе — один на выходе.

Зачем отдельная вкладка. Раньше для этого приходилось брать «Объединить»:
она умеет читать любой формат и писать любой, но по дороге склеивает всё
в один файл. Чтобы получить те же двести глав, только в `.docx`, человек
запускал её двести раз — по разу на главу.

Чем отличается от соседей. «Разбить» режет один файл на много, «Объединить»
собирает много в один. Здесь количество не меняется: сколько файлов
выбрали, столько и получится. Меняется только формат.

Главы внутри файла остаются как есть: файл с целой книгой останется
книгой, файл с одной главой — главой. Резать и склеивать — не эта работа.
"""

from __future__ import annotations

import logging
from pathlib import Path

from core import formats
from core.models import OpReport
from core.text import PrepOptions

from .base import Progress, collect_files, skipped_files

log = logging.getLogger(__name__)


def scan(targets) -> dict:
    """Что попало под выбор — без чтения содержимого.

    Соседние вкладки на этом месте читают все главы: «Объединить» иначе
    не покажет их порядок, «Разбить» — число кусков. Здесь ни то, ни
    другое не нужно: сколько файлов выбрали, столько и выйдет. А чтение
    пятисот `.docx` только ради числа стоит десяток секунд — ровно та
    цена, которую в «Переименовать» уже однажды заплатили зря.
    """
    files = collect_files(targets)
    return {
        "files": [str(path) for path in files],
        "file_count": len(files),
        # Что лежало рядом, но по формату не подошло. Молчать нельзя:
        # иначе недостача обнаружится только в готовой папке.
        "skipped": skipped_files(targets),
    }


def _free_name(output: Path, stem: str, suffix: str, used: set[str]) -> Path:
    """Свободное имя в папке назначения.

    Одинаковые имена из разных папок — обычное дело: у двух книг главы
    зовутся одинаково. Молча затирать одно другим нельзя, поэтому к
    повтору дописывается номер.
    """
    name = f"{stem}{suffix}"
    if name.lower() not in used:
        used.add(name.lower())
        return output / name

    order = 2
    while f"{stem} ({order}){suffix}".lower() in used:
        order += 1
    name = f"{stem} ({order}){suffix}"
    used.add(name.lower())
    return output / name


def run(
    targets,
    output: Path,
    out_format: str = ".txt",
    encoding: str = "utf-8",
    headings: bool = True,
    prep: PrepOptions | None = None,
    style=None,
    progress: Progress | None = None,
) -> OpReport:
    """Перегоняет выбранное в другой формат, файл за файлом.

    Сбой на одном файле не останавливает остальные: из двухсот глав
    одна битая не должна стоить всей работы. Что не вышло — попадает в
    отчёт с причиной.
    """
    progress = progress or Progress()
    prep = prep or PrepOptions()

    suffix = out_format if out_format.startswith(".") else f".{out_format}"
    suffix = suffix.lower()
    if suffix not in formats.WRITABLE:
        raise ValueError(
            f"Не умею писать {suffix} — нужен один из "
            + ", ".join(formats.WRITABLE))

    files = collect_files(targets)
    if not files:
        raise ValueError("Не выбрано ни одного файла подходящего формата")

    output.mkdir(parents=True, exist_ok=True)
    report = OpReport(output=str(output), total=len(files))
    used: set[str] = set()
    same = 0

    for index, path in enumerate(files, 1):
        progress.check()
        target = _free_name(output, path.stem, suffix, used)

        # Файл уже в нужном формате. Не пропускаем: у вкладки есть и
        # подготовка текста, и своя кодировка — перегон в тот же формат
        # осмыслен. Но считаем отдельно, чтобы в итоге было видно.
        if path.suffix.lower() == suffix:
            same += 1

        try:
            chapters = formats.read(path)
            if not chapters:
                raise ValueError("в файле не нашлось ни одной главы")
            formats.write(target, chapters, prep=prep, style=style,
                          headings=headings, encoding=encoding,
                          title=path.stem)
            report.written += 1
        except Exception as exc:  # noqa: BLE001 — один файл не рушит пачку
            log.warning("Не перегнан %s: %s", path.name, exc)
            report.fail(path.name, "перегон", f"{type(exc).__name__}: {exc}")

        progress.step(index, len(files), f"Файл {index} из {len(files)}")

    if same:
        report.extra["same_format"] = same
    return report


__all__ = ["run", "scan"]
