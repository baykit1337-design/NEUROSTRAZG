"""Статистика книги.

Помогает решить, какие главы делить, и пригодится для описания на
площадке выкладки: всего глав, символов, слов, среднее на главу, самая
короткая и самая длинная, примерное время чтения.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median

from core.models import OpReport

from .base import Progress, collect_files, read_all

#: Скорость чтения художественного текста по-русски, слов в минуту.
#: Значение усреднённое: точности тут и не требуется, нужен порядок.
WORDS_PER_MINUTE = 180

#: Слово — буквы и цифры подряд. Знаки препинания словами не считаем.
WORD = re.compile(r"[^\W_]+", re.UNICODE)

#: Сколько столбиков рисовать в распределении объёма.
BUCKETS = 40


@dataclass
class ChapterStat:
    label: str = ""
    title: str = ""
    characters: int = 0
    words: int = 0
    paragraphs: int = 0
    source: str = ""

    def as_dict(self) -> dict:
        return {"label": self.label, "title": self.title,
                "characters": self.characters, "words": self.words,
                "paragraphs": self.paragraphs, "source": self.source}


@dataclass
class Report:
    chapters: list[ChapterStat] = field(default_factory=list)
    unreadable: list = field(default_factory=list)

    @property
    def total_characters(self) -> int:
        return sum(c.characters for c in self.chapters)

    @property
    def total_words(self) -> int:
        return sum(c.words for c in self.chapters)

    @property
    def minutes(self) -> int:
        return round(self.total_words / WORDS_PER_MINUTE) if self.total_words else 0

    def as_dict(self) -> dict:
        if not self.chapters:
            return {"chapters": 0, "unreadable": self.unreadable}

        sizes = [c.characters for c in self.chapters]
        shortest = min(self.chapters, key=lambda c: c.characters)
        longest = max(self.chapters, key=lambda c: c.characters)

        return {
            "chapters": len(self.chapters),
            "characters": self.total_characters,
            "words": self.total_words,
            "paragraphs": sum(c.paragraphs for c in self.chapters),
            "average": round(self.total_characters / len(self.chapters)),
            # Медиана честнее среднего: одна глава-гигант его перекашивает.
            "median": round(median(sizes)),
            "shortest": shortest.as_dict(),
            "longest": longest.as_dict(),
            "minutes": self.minutes,
            "reading_time": _human_time(self.minutes),
            "buckets": self.buckets(),
            "sizes": sizes,
            "unreadable": self.unreadable,
        }

    def buckets(self, count: int = BUCKETS) -> list[dict]:
        """Распределение объёма по главам — для столбиков в интерфейсе.

        На пятистах главах рисовать пятьсот столбиков бессмысленно:
        соседние сливаются. Поэтому главы группируются, и в столбике —
        средний объём группы.
        """
        if not self.chapters:
            return []

        step = max(1, len(self.chapters) // count + (1 if len(self.chapters) % count else 0))
        made = []
        for start in range(0, len(self.chapters), step):
            group = self.chapters[start:start + step]
            made.append({
                "from": group[0].label or group[0].title,
                "to": group[-1].label or group[-1].title,
                "count": len(group),
                "characters": round(sum(c.characters for c in group) / len(group)),
            })
        return made


def _human_time(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} мин"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} ч {rest} мин" if rest else f"{hours} ч"
    days, hours = divmod(hours, 24)
    return f"{days} дн {hours} ч" if hours else f"{days} дн"


def collect(targets, progress: Progress | None = None) -> Report:
    """Считает статистику по выбранным главам."""
    report = OpReport()
    files = collect_files(targets)
    chapters = read_all(files, report, progress)

    result = Report(unreadable=[f.as_text() for f in report.failures])
    for chapter in chapters:
        text = chapter.text
        result.chapters.append(ChapterStat(
            label=chapter.label or "",
            title=chapter.title,
            characters=len(text),
            words=len(WORD.findall(text)),
            paragraphs=len(chapter.paragraphs),
            source=chapter.source,
        ))
    return result
