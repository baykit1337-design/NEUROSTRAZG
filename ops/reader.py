"""Просмотр главы прямо в программе.

Сейчас, чтобы посмотреть одну главу, приходится открывать Word. Здесь то
же самое видно на месте: текст в том оформлении, что будет на выходе,
переход между главами, правка с сохранением.

Правка пишет поверх исходного файла — это единственное место в программе,
которое так делает, и потому единственное, где сохранение спрашивается
явно. Копия при этом уходит в корзину.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from core import formats
from core.models import OpReport
from core.readers.base import ReadError
from core.text import PrepOptions, prepare, to_text

from . import history
from .base import collect_files, read_all

log = logging.getLogger(__name__)


@dataclass
class Entry:
    """Глава в списке: чем её показать и как назвать."""

    index: int = 0
    label: str = ""
    title: str = ""
    source: str = ""
    size: int = 0

    def as_dict(self) -> dict:
        return {"index": self.index, "label": self.label, "title": self.title,
                "source": self.source, "size": self.size}


@dataclass
class Page:
    """Одна открытая глава."""

    index: int = 0
    total: int = 0
    label: str = ""
    title: str = ""
    source: str = ""
    paragraphs: list[str] = field(default_factory=list)
    #: Находки проверки по этой главе — подсвечиваются прямо в тексте.
    findings: list = field(default_factory=list)

    @property
    def has_prev(self) -> bool:
        return self.index > 0

    @property
    def has_next(self) -> bool:
        return self.index < self.total - 1

    def as_dict(self) -> dict:
        return {
            "index": self.index, "total": self.total, "label": self.label,
            "title": self.title, "source": self.source,
            "paragraphs": self.paragraphs, "findings": self.findings,
            "has_prev": self.has_prev, "has_next": self.has_next,
            "text": "\n\n".join(self.paragraphs),
        }


def listing(targets) -> dict:
    """Список глав для перехода стрелками."""
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report)

    entries = [
        Entry(index=index, label=chapter.label, title=chapter.title,
              source=chapter.source, size=chapter.size)
        for index, chapter in enumerate(chapters)
    ]
    return {
        "chapters": [e.as_dict() for e in entries],
        "total": len(entries),
        "unreadable": [f.as_text() for f in report.failures],
    }


def open_at(targets, index: int = 0, prep: PrepOptions | None = None,
            kinds=None) -> Page:
    """Глава по номеру в списке, в том же виде, что будет на выходе."""
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report)
    if not chapters:
        raise ReadError("Не удалось прочитать ни одной главы")

    index = max(0, min(int(index), len(chapters) - 1))
    chapter = chapters[index]

    # Через ту же подготовку текста, что и запись: иначе читалка показывала
    # бы одно, а в файл легло бы другое.
    blocks = prepare(chapter.paragraphs, chapter.title, prep)
    paragraphs = [block.text for block in blocks if block.text.strip()]

    page = Page(index=index, total=len(chapters), label=chapter.label,
                title=chapter.title, source=chapter.source,
                paragraphs=paragraphs)
    page.findings = _findings(chapter.source, paragraphs, kinds)
    return page


def _findings(source: str, paragraphs: list[str], kinds=None) -> list[dict]:
    """Находки проверки по этой главе — чтобы подсветить их в тексте.

    Проверка работает по файлу, а в файле может лежать вся книга сразу.
    Поэтому оставляем только те находки, чей абзац виден на этой странице:
    иначе читалка подсвечивала бы то, чего на экране нет.
    """
    # Пустой список — это снятая галочка «подсветить находки», а не
    # «проверить всё»: разница видна только здесь, дальше `None` и `[]`
    # для проверки уже одно и то же.
    if kinds is not None and not kinds:
        return []
    if not source or not Path(source).is_file():
        return []
    try:
        from mvl import textcheck

        report = textcheck.check(Path(source), kinds=kinds)
    except Exception as exc:  # noqa: BLE001 — проверка не должна мешать чтению
        log.warning("Проверка главы %s не прошла: %s", source, exc)
        return []

    shown = {p.strip() for p in paragraphs}
    found = []
    for finding in report.findings:
        data = finding.as_dict()
        context = (data.get("context") or "").strip()
        if context and context not in shown:
            continue
        found.append(data)
    return found


class SaveError(Exception):
    """Сохранить не удалось."""


def save(source: str, text: str, backup: bool = True) -> dict:
    """Пишет правку поверх исходного файла.

    Перед записью файл уходит в корзину: это единственное место, где
    программа меняет исходник, и без копии откатывать было бы нечего.
    """
    path = Path(source).expanduser()
    if not path.is_file():
        raise SaveError(f"Файл не найден: {path}")

    paragraphs = [line.strip() for line in (text or "").split("\n\n")
                  if line.strip()]
    if not paragraphs:
        raise SaveError("Пустой текст сохранять нечего")

    try:
        chapters = formats.read(path)
    except ReadError as exc:
        raise SaveError(str(exc)) from exc

    if not chapters:
        raise SaveError("В файле нет глав")
    if len(chapters) > 1:
        # Записать одну главу в файл, где их сто, значит стереть остальные
        # девяносто девять. Такую правку делают в «Разбить».
        raise SaveError(
            f"В файле {len(chapters)} глав — правка поверх сотрёт остальные. "
            "Сначала разбейте книгу на файлы по главам.")

    chapter = chapters[0]
    chapter.paragraphs = paragraphs

    saved = history.backup_file(path, "правка-в-читалке") if backup else ""

    try:
        formats.write(path, [chapter], headings=True, title=chapter.title)
    except Exception as exc:  # noqa: BLE001 — показываем причину целиком
        raise SaveError(f"{type(exc).__name__}: {exc}") from exc

    history.add("правка главы", source=str(path), output=str(path),
                files=1, backup=saved)
    return {"saved": str(path), "paragraphs": len(paragraphs), "backup": saved}
