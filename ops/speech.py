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
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

    def as_dict(self) -> dict:
        return {"chapter": self.chapter, "before": self.before,
                "after": self.after}


@dataclass
class Report:
    chapters: int = 0
    lines: int = 0
    changed: int = 0
    samples: list[Change] = field(default_factory=list)

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


__all__ = ["DASH", "QUOTES", "SHOW", "Change", "Report", "dashed", "inspect",
           "rewrite"]
