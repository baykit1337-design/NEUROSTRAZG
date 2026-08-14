"""Пересказ по собранным фактам (3.5 ТЗ NEUROSTRAZH).

Две разные вещи под одним словом.

**По главам** — из уже собранных фактов, без единого запроса к модели.
Главы разобраны на этапе анализа, и события в реестре уже лежат; платить
второй раз за то, что известно, незачем. Такой пересказ ничего не
сочиняет — он ровно то, что модель нашла в тексте.

**Аннотация книги** — один запрос: связный текст из разрозненных фактов
сам не соберётся. Отсюда и объём в ТЗ: полторы тысячи знаков это примерно
то, что человек читает перед тем, как решить, браться ли за книгу.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.registry import Registry
from llm import prompts

#: Сколько событий брать в пересказ одной главы. Больше — уже не пересказ,
#: а протокол.
EVENTS_PER_CHAPTER = 6

#: Сколько глав отдавать модели на аннотацию. Пятьсот глав в один запрос не
#: влезут, а сюжет виден и по началу с концом.
CHAPTERS_FOR_ANNOTATION = 60

#: Границы аннотации из ТЗ.
ANNOTATION_MIN = 1000
ANNOTATION_MAX = 1500


class RetellError(Exception):
    """Пересказать не из чего."""


@dataclass
class ChapterRetell:
    """Пересказ одной главы."""

    chapter: int = 0
    lines: list[str] = field(default_factory=list)
    new_names: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def as_dict(self) -> dict:
        return {"chapter": self.chapter, "lines": self.lines,
                "new_names": self.new_names, "text": self.text}


def _name(registry: Registry, key: str) -> str:
    """Имя сущности по идентификатору. Незнакомый — как есть."""
    entity = registry.entities.get(key)
    if entity is not None:
        return entity.name
    found = registry.find(key)
    return found.name if found is not None else key


def _line(registry: Registry, event) -> str:
    """Одно событие человеческой строкой.

    Без цитаты: цитаты уже видны в реестре, а в пересказе они превратили бы
    его обратно в текст главы.
    """
    actor = _name(registry, event.actor)
    obj = _name(registry, event.object)
    kind = event.type or "событие"

    if actor and obj:
        return f"{actor} — {kind} — {obj}"
    if actor:
        return f"{actor} — {kind}"
    if obj:
        return f"{kind} — {obj}"
    return kind


def chapters(registry: Registry) -> list[ChapterRetell]:
    """Пересказ по главам. Новых запросов не делает."""
    by_chapter: dict[int, ChapterRetell] = {}

    for event in registry.events:
        if event.chapter is None:
            continue
        found = by_chapter.setdefault(event.chapter, ChapterRetell(chapter=event.chapter))
        line = _line(registry, event)
        # Одно и то же событие модель нередко возвращает дважды.
        if line not in found.lines and len(found.lines) < EVENTS_PER_CHAPTER:
            found.lines.append(line)

    # Кто появился впервые: по этому видно, где в книге прибавилось имён.
    for entity in registry.entities.values():
        if entity.first_chapter is None:
            continue
        found = by_chapter.setdefault(
            entity.first_chapter, ChapterRetell(chapter=entity.first_chapter))
        if entity.name not in found.new_names:
            found.new_names.append(entity.name)

    return [by_chapter[number] for number in sorted(by_chapter)]


def chapters_text(registry: Registry) -> str:
    """Пересказ по главам простым текстом — годится и для .md, и для .docx."""
    out: list[str] = []
    for item in chapters(registry):
        out.append(f"# Глава {item.chapter}")
        if item.new_names:
            out.append("Впервые появляются: " + ", ".join(item.new_names))
        out.extend(item.lines or ["Событий не отмечено."])
        out.append("")
    return "\n".join(out).strip()


def facts_lines(registry: Registry, limit: int = CHAPTERS_FOR_ANNOTATION) -> list[str]:
    """Факты для аннотации, сжатые до строк.

    Берём начало и конец: завязка и развязка говорят о книге больше, чем
    любая середина, а весь реестр в один запрос всё равно не поместится.
    """
    all_chapters = chapters(registry)
    if len(all_chapters) > limit:
        half = limit // 2
        all_chapters = all_chapters[:half] + all_chapters[-half:]

    lines = []
    for entity in sorted(registry.entities.values(),
                         key=lambda e: (e.first_chapter or 0))[:40]:
        lines.append(f"{entity.type}: {entity.name}"
                     + (f" ({entity.status})" if entity.status else ""))
    for item in all_chapters:
        for line in item.lines:
            lines.append(f"глава {item.chapter}: {line}")
    return lines


def annotation(registry: Registry, client, model: str = "") -> dict:
    """Общая аннотация книги. Один запрос к модели."""
    lines = facts_lines(registry)
    if not lines:
        raise RetellError(
            "Фактов нет — сначала разберите главы на вкладке «Анализ»")

    text = client.generate(prompts.summary(lines), json_only=False, model=model)
    text = (text or "").strip()
    if not text:
        raise RetellError("Модель вернула пустой ответ")

    return {
        "text": text,
        "length": len(text),
        # Объём из ТЗ. Не обрезаем: обрезанная на полуслове аннотация хуже
        # длинной, — но говорим, что вышло за рамки.
        "within": ANNOTATION_MIN <= len(text) <= ANNOTATION_MAX,
        "chapters": len(chapters(registry)),
    }
