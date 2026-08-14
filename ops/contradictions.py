"""Поиск противоречий: второй проход по фактам со сверкой против реестра.

Проверки универсальные, без привязки к жанру. Реестр знает, кому что
принадлежит и кто жив, — этого достаточно, чтобы заметить ошибку в
грамматически безупречном предложении.

Ни одной проверки «по ключевым словам» здесь нет: всё считается по связям
и статусам, поэтому новый тип сущности не требует правок.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.registry import (
    QUOTE_LIMIT,
    Registry,
    STATUS_DEAD,
    looks_same,
    normalize,
)
from llm.cache import FactsCache

#: Виды находок и как они называются в отчёте.
KINDS = {
    "foreign_entity": "Чужая сущность",
    "after_death": "Действие после смерти",
    "foreign_ability": "Чужая способность",
    "name_variants": "Разнобой имён",
    "attribute_change": "Смена атрибута",
    "link_conflict": "Противоречие связи",
    "too_early": "Появление раньше срока",
    "location_clash": "Локация не сходится",
}

#: Связи, означающие принадлежность: по ним считается «чей».
OWNING = ("принадлежит", "слуга", "владеет")

#: Связи, которые не могут действовать одновременно между теми же людьми.
EXCLUSIVE = (
    frozenset({"слуга", "родственник"}),
    frozenset({"союзник", "враг"}),
    frozenset({"ученик", "родственник"}),
)

#: Атрибуты, которые сами по себе не меняются: смена без события подозрительна.
STABLE = ("пол", "раса", "вид")


@dataclass
class Finding:
    """Одна находка: где, что и чему противоречит."""

    kind: str
    chapter: int | None
    quote: str = ""
    message: str = ""
    entity: str = ""
    related: str = ""

    def __post_init__(self):
        # Цитата обрезается здесь, а не при выводе: находку читают и из
        # отчёта, и из интерфейса, и длина должна быть одна.
        self.quote = (self.quote or "")[:QUOTE_LIMIT]

    @property
    def kind_name(self) -> str:
        return KINDS.get(self.kind, self.kind)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "kind_name": self.kind_name,
            "chapter": self.chapter, "quote": self.quote,
            "message": self.message, "entity": self.entity,
            "related": self.related,
        }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    chapters: int = 0

    @property
    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
        return counts

    def as_dict(self) -> dict:
        return {
            "findings": [f.as_dict() for f in self.findings],
            "total": len(self.findings),
            "chapters": self.chapters,
            "summary": [
                {"kind": k, "kind_name": KINDS.get(k, k), "count": v}
                for k, v in sorted(self.summary.items(), key=lambda kv: -kv[1])
            ],
        }


def _name(registry: Registry, entity_id: str) -> str:
    entity = registry.entities.get(entity_id)
    return entity.name if entity else entity_id


def check(registry: Registry, root: Path, kinds=None) -> Report:
    """Сверяет факты по главам против реестра."""
    wanted = set(kinds) if kinds else set(KINDS)
    report = Report()
    entries = FactsCache(Path(root)).entries()
    report.chapters = len(entries)

    # Разнобой имён и появление раньше срока считаются по всему реестру, а
    # не по отдельной главе.
    if "name_variants" in wanted:
        report.findings.extend(_name_variants(registry))

    seen_attributes: dict[tuple[str, str], tuple[str, int | None]] = {}
    seen_links: dict[tuple[str, str], list] = {}

    for entry in entries:
        facts = entry.facts or {}
        number = entry.number if entry.number is not None else facts.get("chapter")

        if "attribute_change" in wanted:
            report.findings.extend(
                _attribute_change(registry, facts, number, seen_attributes))
        if "link_conflict" in wanted:
            report.findings.extend(
                _link_conflict(registry, facts, number, seen_links))
        if "too_early" in wanted:
            report.findings.extend(_too_early(registry, facts, number))

        for event in facts.get("events") or []:
            actor = registry.find(str(event.get("actor") or ""))
            obj = registry.find(str(event.get("object") or ""))
            quote = str(event.get("quote") or "")

            if "after_death" in wanted and actor is not None:
                report.findings.extend(
                    _after_death(registry, actor, number, quote))
            if actor is not None and obj is not None:
                if "foreign_ability" in wanted and obj.type == "способность":
                    report.findings.extend(
                        _foreign(registry, actor, obj, number, quote,
                                 "foreign_ability"))
                elif "foreign_entity" in wanted:
                    report.findings.extend(
                        _foreign(registry, actor, obj, number, quote,
                                 "foreign_entity"))
            if "location_clash" in wanted and actor is not None:
                report.findings.extend(
                    _location(registry, facts, actor, number, quote))

    report.findings.sort(key=lambda f: (f.chapter is None, f.chapter or 0, f.kind))
    return report


def _foreign(registry, actor, obj, number, quote, kind) -> list[Finding]:
    """Действующий использует то, что закреплено за другим."""
    owner = registry.owner_of(obj.id)
    if not owner or owner == actor.id:
        return []
    # Союзник или член той же организации — не чужой.
    if _allied(registry, actor.id, owner):
        return []

    what = "способность" if kind == "foreign_ability" else obj.type
    return [Finding(
        kind=kind, chapter=number, quote=quote,
        entity=obj.id, related=owner,
        message=(f"{actor.name} использует «{obj.name}» ({what}), "
                 f"но в реестре это закреплено за: {_name(registry, owner)}"),
    )]


def _allied(registry: Registry, first: str, second: str) -> bool:
    for link in registry.links:
        pair = {link.source, link.target}
        if pair == {first, second} and link.type in ("союзник", "член", "родственник"):
            return True
    return False


def _after_death(registry, actor, number, quote) -> list[Finding]:
    """Сущность со статусом «мёртв» действует."""
    if actor.status != STATUS_DEAD:
        return []
    died = _died_at(registry, actor.id)
    if died is not None and number is not None and number <= died:
        # В самой главе гибели действовать ещё можно.
        return []
    return [Finding(
        kind="after_death", chapter=number, quote=quote, entity=actor.id,
        message=(f"{actor.name} действует, хотя в реестре помечен как мёртвый"
                 + (f" (глава {died})" if died is not None else "")),
    )]


def _died_at(registry: Registry, entity_id: str) -> int | None:
    for event in registry.events:
        if event.object == entity_id or event.actor == entity_id:
            if event.type in ("гибель", "смерть"):
                return event.chapter
    return None


def _name_variants(registry: Registry) -> list[Finding]:
    """Варианты написания, не сведённые в aliases."""
    found = []
    for first_id, second_id in registry.duplicates():
        first = registry.entities[first_id]
        second = registry.entities[second_id]
        found.append(Finding(
            kind="name_variants", chapter=first.first_chapter,
            entity=first_id, related=second_id,
            message=(f"«{first.name}» и «{second.name}» похожи настолько, "
                     f"что это, вероятно, одно и то же — сведите в варианты имени"),
        ))
    return found


def _attribute_change(registry, facts, number, seen) -> list[Finding]:
    """Пол, ранг или фракция изменились без события."""
    found = []
    for item in facts.get("entities") or []:
        entity = registry.find(str(item.get("name") or ""))
        if entity is None:
            continue
        for key, value in (item.get("attributes") or {}).items():
            if key not in STABLE:
                continue
            value = str(value)
            mark = (entity.id, key)
            previous = seen.get(mark)
            if previous is None:
                seen[mark] = (value, number)
                continue
            if normalize(previous[0]) != normalize(value):
                found.append(Finding(
                    kind="attribute_change", chapter=number, entity=entity.id,
                    message=(f"у «{entity.name}» признак «{key}» был "
                             f"«{previous[0]}» (глава {previous[1]}), "
                             f"стал «{value}»"),
                ))
                seen[mark] = (value, number)
    return found


def _link_conflict(registry, facts, number, seen) -> list[Finding]:
    """Слуга внезапно назван братом."""
    found = []
    for item in facts.get("links") or []:
        source = registry.find(str(item.get("from") or ""))
        target = registry.find(str(item.get("to") or ""))
        kind = str(item.get("type") or "").strip()
        if source is None or target is None or not kind:
            continue

        pair = tuple(sorted((source.id, target.id)))
        kinds = seen.setdefault(pair, [])
        for known, chapter in kinds:
            if known == kind:
                break
            if any({known, kind} <= group for group in EXCLUSIVE):
                found.append(Finding(
                    kind="link_conflict", chapter=number,
                    entity=source.id, related=target.id,
                    message=(f"«{source.name}» и «{target.name}»: связь была "
                             f"«{known}» (глава {chapter}), стала «{kind}»"),
                ))
                break
        kinds.append((kind, number))
    return found


def _too_early(registry, facts, number) -> list[Finding]:
    """Сущность упомянута до главы, в которой появляется по реестру."""
    if number is None:
        return []
    found = []
    for item in facts.get("entities") or []:
        entity = registry.find(str(item.get("name") or ""))
        if entity is None or entity.first_chapter is None:
            continue
        if number < entity.first_chapter:
            found.append(Finding(
                kind="too_early", chapter=number, entity=entity.id,
                message=(f"«{entity.name}» упомянут в главе {number}, "
                         f"а появляется только в {entity.first_chapter}"),
            ))
    return found


def _location(registry, facts, actor, number, quote) -> list[Finding]:
    """Персонаж в двух местах в одной сцене."""
    places = []
    for item in facts.get("links") or []:
        if str(item.get("type") or "") != "находится_в":
            continue
        source = registry.find(str(item.get("from") or ""))
        target = registry.find(str(item.get("to") or ""))
        if source is not None and source.id == actor.id and target is not None:
            places.append(target)

    unique = []
    for place in places:
        if not any(looks_same(place.name, p.name) for p in unique):
            unique.append(place)
    if len(unique) < 2:
        return []

    listing = ", ".join(f"«{p.name}»" for p in unique)
    return [Finding(
        kind="location_clash", chapter=number, quote=quote, entity=actor.id,
        message=f"{actor.name} в одной главе находится сразу в: {listing}",
    )]
