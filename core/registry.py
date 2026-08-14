"""Универсальный реестр сущностей книги.

Схема намеренно не привязана к жанру. Всё в мире книги описывается тремя
таблицами: сущности, связи, события. Питомец — это сущность типа
«существо» со связью «принадлежит». Артефакт, техника, корабль, вассал,
титул описываются так же, без единой правки в коде.

Модуль знает только о данных: ни о сети, ни о модели, ни о вебе.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

#: Типы сущностей. Список расширяемый — при встрече незнакомого типа
#: запись не выбрасывается, он просто добавляется к известным.
TYPES = (
    "персонаж", "существо", "предмет", "способность",
    "локация", "организация", "титул", "термин",
)

#: Типы связей.
LINK_TYPES = (
    "принадлежит", "слуга", "родственник", "член", "ученик",
    "союзник", "враг", "владеет", "находится_в",
)

#: Статус сущности. «Мёртв» важен отдельно: действие после смерти —
#: одна из проверок.
STATUS_ALIVE = "жив"
STATUS_DEAD = "мёртв"

#: На столько символов могут отличаться имена, чтобы считаться вариантами
#: одного: «Тео» и «Тэо».
MERGE_DISTANCE = 2

#: Короткие имена сливать опаснее: «Ли» и «Ло» — разные люди, хотя
#: различие тоже в один символ.
SHORT_NAME = 5

#: Буквы, которые подменяют друг друга при записи одного и того же имени:
#: «Тео» и «Тэо», «Майя» и «Маия». Различие в такой паре — вариант
#: написания, а в любой другой — уже другое имя. Именно это отличает
#: «Тео/Тэо» от «Ли/Ло»: и там и там одна замена, но смысл разный.
CONFUSABLE = (
    frozenset("еэ"), frozenset("её"), frozenset("ий"), frozenset("иы"),
    frozenset("ъь"), frozenset("яа"), frozenset("юу"), frozenset("оа"),
    frozenset("сз"), frozenset("фв"), frozenset("гх"),
)


def _confusable(a: str, b: str) -> bool:
    pair = frozenset((a, b))
    return len(pair) == 2 and any(pair == group for group in CONFUSABLE)


def slug(name: str) -> str:
    """Идентификатор из имени. Латиница и цифры, остальное — через дефис."""
    text = unicodedata.normalize("NFKD", (name or "").strip().casefold())
    text = re.sub(r"[^\w]+", "-", text, flags=re.UNICODE)
    return text.strip("-") or "id"


def normalize(name: str) -> str:
    """Имя для сравнения: без регистра, лишних пробелов и знаков."""
    text = unicodedata.normalize("NFKC", (name or "").strip().casefold())
    text = re.sub(r"[\s]+", " ", text)
    return text.strip(" .,:;!?«»\"'-–—")


def distance(a: str, b: str) -> int:
    """Расстояние Левенштейна. Нужно, чтобы ловить варианты написания."""
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ca != cb),
            ))
        previous = current
    return previous[-1]


def looks_same(a: str, b: str) -> bool:
    """Похоже ли, что это два написания одного имени.

    У коротких имён порог строже: «Тео» и «Тэо» — одно, а «Ли» и «Ло» —
    разные люди, хотя различие тоже в один символ.
    """
    a, b = normalize(a), normalize(b)
    if not a or not b or a == b:
        return bool(a and a == b)

    if min(len(a), len(b)) < SHORT_NAME:
        # У короткого имени одна замена решает всё, поэтому требуем, чтобы
        # заменённые буквы были из тех, что подменяют друг друга.
        if len(a) != len(b):
            return False
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        return len(diff) == 1 and _confusable(*diff[0])

    return distance(a, b) <= MERGE_DISTANCE


@dataclass
class Entity:
    """Кто или что. Тип задаёт смысл, схема от него не зависит."""

    id: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    type: str = "термин"
    first_chapter: int | None = None
    status: str = STATUS_ALIVE
    attributes: dict = field(default_factory=dict)
    #: Запись подтверждена человеком либо пришла из глоссария. Модель её
    #: больше не перезаписывает — она считается истиной.
    confirmed: bool = False

    def __post_init__(self):
        if not self.id:
            self.id = slug(self.name)

    @property
    def names(self) -> list[str]:
        """Имя и все варианты — по ним сущность ищется в тексте."""
        return [self.name, *self.aliases]

    def knows(self, name: str) -> bool:
        wanted = normalize(name)
        return any(normalize(n) == wanted for n in self.names)

    def add_alias(self, name: str) -> None:
        if name and not self.knows(name):
            self.aliases.append(name)

    def as_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "aliases": list(self.aliases),
            "type": self.type, "first_chapter": self.first_chapter,
            "status": self.status, "attributes": dict(self.attributes),
            "confirmed": self.confirmed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Entity:
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            aliases=[str(a) for a in (data.get("aliases") or []) if str(a).strip()],
            type=str(data.get("type") or "термин"),
            first_chapter=_int(data.get("first_chapter")),
            status=str(data.get("status") or STATUS_ALIVE),
            attributes={str(k): v for k, v in (data.get("attributes") or {}).items()},
            confirmed=bool(data.get("confirmed")),
        )


@dataclass
class Link:
    """Связь между двумя сущностями: кто кому принадлежит, кто чей слуга."""

    source: str = ""
    target: str = ""
    type: str = ""
    since_chapter: int | None = None
    confirmed: bool = False

    @property
    def key(self) -> tuple:
        return (self.source, self.target, self.type)

    def as_dict(self) -> dict:
        return {"from": self.source, "to": self.target, "type": self.type,
                "since_chapter": self.since_chapter, "confirmed": self.confirmed}

    @classmethod
    def from_dict(cls, data: dict) -> Link:
        return cls(
            source=str(data.get("from") or data.get("source") or ""),
            target=str(data.get("to") or data.get("target") or ""),
            type=str(data.get("type") or ""),
            since_chapter=_int(data.get("since_chapter")),
            confirmed=bool(data.get("confirmed")),
        )


@dataclass
class Event:
    """Что произошло в главе. Цитата нужна, чтобы находку можно было
    проверить глазами, не открывая книгу."""

    chapter: int | None = None
    type: str = ""
    actor: str = ""
    object: str = ""
    quote: str = ""

    def as_dict(self) -> dict:
        return {"chapter": self.chapter, "type": self.type, "actor": self.actor,
                "object": self.object, "quote": self.quote}

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        return cls(
            chapter=_int(data.get("chapter")),
            type=str(data.get("type") or ""),
            actor=str(data.get("actor") or ""),
            object=str(data.get("object") or ""),
            quote=str(data.get("quote") or "")[:QUOTE_LIMIT],
        )


#: Цитата в находке — до 200 символов, дальше это уже пересказ главы.
QUOTE_LIMIT = 200


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Registry:
    """Свод фактов по книге: сущности, связи, события."""

    entities: dict[str, Entity] = field(default_factory=dict)
    links: list[Link] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    #: Главы, которые уже разобраны, — чтобы не слать их повторно.
    chapters: list[int] = field(default_factory=list)

    # ------------------------------------------------------------- поиск

    def find(self, name: str) -> Entity | None:
        """Сущность по имени или любому из вариантов."""
        wanted = normalize(name)
        if not wanted:
            return None
        by_id = self.entities.get(name) or self.entities.get(slug(name))
        if by_id is not None:
            return by_id
        for entity in self.entities.values():
            if entity.knows(name):
                return entity
        return None

    def similar(self, name: str) -> Entity | None:
        """Сущность с похожим именем: «Тео» против «Тэо»."""
        for entity in self.entities.values():
            if any(looks_same(n, name) for n in entity.names):
                return entity
        return None

    def of_type(self, kind: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.type == kind]

    def links_of(self, entity_id: str, kind: str = "") -> list[Link]:
        return [
            link for link in self.links
            if (link.source == entity_id or link.target == entity_id)
            and (not kind or link.type == kind)
        ]

    def owner_of(self, entity_id: str) -> str:
        """Кому принадлежит сущность. Пусто — ничьё."""
        for link in self.links:
            if link.source == entity_id and link.type in ("принадлежит", "слуга"):
                return link.target
        for link in self.links:
            if link.target == entity_id and link.type == "владеет":
                return link.source
        return ""

    # ------------------------------------------------------------ правка

    def add_entity(self, entity: Entity, merge: bool = True) -> Entity:
        """Добавляет сущность или дополняет уже известную.

        Подтверждённую запись модель не перезаписывает: человек уже сказал,
        как правильно, и переубеждать его незачем.
        """
        found = self.find(entity.name)
        if found is None and merge:
            twin = self.similar(entity.name)
            if twin is not None:
                # Вариант написания — в aliases, отдельной записи не заводим.
                twin.add_alias(entity.name)
                found = twin

        if found is None:
            if entity.id in self.entities:
                entity.id = _unique(entity.id, self.entities)
            self.entities[entity.id] = entity
            return entity

        if found.confirmed and not entity.confirmed:
            # Первое появление уточнить можно даже у подтверждённой записи:
            # это факт из текста, а не суждение.
            found.first_chapter = _earliest(found.first_chapter, entity.first_chapter)
            return found

        found.first_chapter = _earliest(found.first_chapter, entity.first_chapter)
        if entity.type and entity.type != "термин":
            found.type = entity.type
        if entity.status:
            found.status = entity.status
        for key, value in entity.attributes.items():
            found.attributes.setdefault(key, value)
        for alias in entity.aliases:
            found.add_alias(alias)
        if entity.confirmed:
            found.confirmed = True
        return found

    def add_link(self, link: Link) -> Link:
        for existing in self.links:
            if existing.key == link.key:
                existing.since_chapter = _earliest(
                    existing.since_chapter, link.since_chapter)
                existing.confirmed = existing.confirmed or link.confirmed
                return existing
        self.links.append(link)
        return link

    def add_event(self, event: Event) -> Event:
        self.events.append(event)
        return event

    def merge(self, keep_id: str, drop_id: str) -> Entity | None:
        """Сливает две записи: вторая уходит в варианты имени первой."""
        keep = self.entities.get(keep_id)
        drop = self.entities.get(drop_id)
        if keep is None or drop is None or keep is drop:
            return keep

        keep.add_alias(drop.name)
        for alias in drop.aliases:
            keep.add_alias(alias)
        keep.first_chapter = _earliest(keep.first_chapter, drop.first_chapter)
        for key, value in drop.attributes.items():
            keep.attributes.setdefault(key, value)

        for link in self.links:
            if link.source == drop_id:
                link.source = keep_id
            if link.target == drop_id:
                link.target = keep_id
        for event in self.events:
            if event.actor == drop_id:
                event.actor = keep_id
            if event.object == drop_id:
                event.object = keep_id

        del self.entities[drop_id]
        return keep

    def duplicates(self) -> list[tuple[str, str]]:
        """Пары записей, похожих настолько, что стоит предложить слияние."""
        found: list[tuple[str, str]] = []
        items = list(self.entities.values())
        for index, first in enumerate(items):
            for second in items[index + 1:]:
                if first.type != second.type:
                    continue
                if any(looks_same(a, b) for a in first.names for b in second.names):
                    found.append((first.id, second.id))
        return found

    # ------------------------------------------------------------ хранение

    def as_dict(self) -> dict:
        return {
            "entities": [e.as_dict() for e in self.entities.values()],
            "links": [l.as_dict() for l in self.links],
            "events": [e.as_dict() for e in self.events],
            "chapters": sorted(self.chapters),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Registry:
        registry = cls()
        for item in data.get("entities") or []:
            entity = Entity.from_dict(item)
            registry.entities[entity.id] = entity
        registry.links = [Link.from_dict(i) for i in data.get("links") or []]
        registry.events = [Event.from_dict(i) for i in data.get("events") or []]
        registry.chapters = [n for n in (data.get("chapters") or []) if _int(n) is not None]
        return registry

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Пишем через временный файл: обрыв на середине не должен оставить
        # покалеченный реестр вместо целого.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> Registry:
        path = Path(path)
        if not path.is_file():
            return cls()
        try:
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # Битый реестр не должен мешать работать: начинаем с чистого.
            return cls()

    def stats(self) -> dict:
        by_type: dict[str, int] = {}
        for entity in self.entities.values():
            by_type[entity.type] = by_type.get(entity.type, 0) + 1
        return {
            "entities": len(self.entities),
            "links": len(self.links),
            "events": len(self.events),
            "chapters": len(self.chapters),
            "confirmed": sum(1 for e in self.entities.values() if e.confirmed),
            "by_type": by_type,
        }


def _earliest(a: int | None, b: int | None) -> int | None:
    values = [v for v in (a, b) if v is not None]
    return min(values) if values else None


def _unique(base: str, taken: dict) -> str:
    index = 2
    while f"{base}-{index}" in taken:
        index += 1
    return f"{base}-{index}"
