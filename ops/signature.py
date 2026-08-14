"""Шапка и подпись в главах.

Имя переводчика, ссылка на канал, просьба поддержать — то, что дописывают
к каждой главе перед выкладкой.

Применяется при экспорте и только к копии: в исходных файлах ничего не
сохраняется. Иначе после двух прогонов подпись оказалась бы в главе
дважды, а после трёх — трижды.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core import formats, naming
from core.models import Chapter, OpReport
from core.text import PrepOptions

from .base import Progress, collect_files, read_all

#: Подстановки, которые можно вписать в шаблон.
PLACEHOLDERS = {
    "{номер}": "номер главы",
    "{название}": "название главы",
    "{всего_глав}": "сколько глав в подборке",
    "{дата}": "сегодняшняя дата",
}

#: Разделитель между шапкой и текстом — пустая строка, поэтому шаблон
#: разбивается на абзацы по переводам строки.
LINE_BREAK = re.compile(r"\n\s*\n|\n")


@dataclass
class Template:
    """Что дописать в начало и в конец главы."""

    head: str = ""
    foot: str = ""
    #: В первой и последней главе шапку с подписью обычно не хотят: там
    #: своё оформление — аннотация и послесловие.
    skip_edges: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> Template:
        data = data or {}
        return cls(
            head=str(data.get("head") or ""),
            foot=str(data.get("foot") or ""),
            skip_edges=bool(data.get("skip_edges")),
        )

    def as_dict(self) -> dict:
        return {"head": self.head, "foot": self.foot,
                "skip_edges": self.skip_edges}

    @property
    def empty(self) -> bool:
        return not (self.head.strip() or self.foot.strip())


def fill(text: str, chapter: Chapter, total: int) -> list[str]:
    """Подставляет значения и режет шаблон на абзацы."""
    if not text.strip():
        return []

    filled = (text
              .replace("{номер}", chapter.label or "")
              .replace("{название}", chapter.title or "")
              .replace("{всего_глав}", str(total))
              .replace("{дата}", date.today().strftime("%d.%m.%Y")))
    return [line.strip() for line in LINE_BREAK.split(filled) if line.strip()]


def apply_to(chapter: Chapter, template: Template, total: int,
             first: bool = False, last: bool = False) -> Chapter:
    """Глава с шапкой и подписью. Исходная не меняется."""
    if template.skip_edges and (first or last):
        return chapter

    return Chapter(
        number=chapter.number, part=chapter.part, title=chapter.title,
        paragraphs=[
            *fill(template.head, chapter, total),
            *chapter.paragraphs,
            *fill(template.foot, chapter, total),
        ],
        source=chapter.source,
    )


def preview(targets, template: Template) -> dict:
    """Как будет выглядеть первая глава. На диск ничего не пишется."""
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report)
    if not chapters:
        raise ValueError("Не удалось прочитать ни одной главы")

    total = len(chapters)
    sample = apply_to(chapters[0], template, total, first=True)
    return {
        "total": total,
        "chapter": sample.title,
        "paragraphs": sample.paragraphs[:12],
        "head": fill(template.head, chapters[0], total),
        "foot": fill(template.foot, chapters[0], total),
        "unreadable": [f.as_text() for f in report.failures],
    }


def run(
    targets,
    output_dir: Path,
    template: Template,
    out_format: str = "",
    prep: PrepOptions | None = None,
    style=None,
    encoding: str = "utf-8",
    progress: Progress | None = None,
) -> OpReport:
    """Пишет главы с шапкой и подписью в новую папку."""
    if template.empty:
        raise ValueError("Шаблоны пусты: нечего добавлять")

    progress = progress or Progress()
    report = OpReport(output=str(output_dir))

    files = collect_files(targets)
    chapters = read_all(files, report, progress)
    if not chapters:
        detail = report.failures[0].as_text() if report.failures else ""
        raise ValueError(f"Не удалось прочитать ни одной главы. {detail}".strip())

    output_dir.mkdir(parents=True, exist_ok=True)
    report.total = len(chapters)
    width = naming.name_width(len(chapters))
    used: set[str] = set()
    last_index = len(chapters) - 1

    for index, chapter in enumerate(chapters):
        progress.check()
        changed = apply_to(chapter, template, len(chapters),
                           first=index == 0, last=index == last_index)

        source = Path(chapter.source) if chapter.source else None
        suffix = out_format or (source.suffix if source else ".txt")
        stem = source.stem if source else \
            f"{index + 1:0{width}d} - {naming.safe_filename(chapter.title)}"
        if f"{stem}{suffix}".lower() in used:
            stem = f"{stem} ({index + 1})"
        used.add(f"{stem}{suffix}".lower())

        try:
            formats.write(output_dir / f"{stem}{suffix}", [changed],
                          prep=prep, style=style, headings=True,
                          encoding=encoding, title=changed.title)
            report.written += 1
        except Exception as exc:
            report.fail(f"{stem}{suffix}", "запись", f"{type(exc).__name__}: {exc}")

        progress.step(index + 1, len(chapters), f"Глава {index + 1} из {len(chapters)}")

    return report
