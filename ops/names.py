"""Глоссарий имён: свести написания одного имени в словарь автозамен.

У машинного перевода имя плавает от главы к главе: Юй Шэн в первой сотне
и Ю Шен в третьей. Реестр «Анализа» про это уже знает — он сводит
написания одного имени в `aliases`, иначе считал бы одного человека
двумя. Здесь накопленное превращается в словарь замен для той замены по
словарю, что уже написана в `ops/replace`.

Своей замены здесь нет намеренно: она есть, проверена и умеет
предпросмотр. Этот модуль отвечает на единственный вопрос — **что** на
**что** менять.

Чего здесь нет и не будет — замены прозвищ. `alias` бывает и вариантом
написания, и вторым именем: «Учитель Ю» — тот же человек, но заменить
его на «Юй Шэн» значит переписывать книгу. Вариантами считаются только
те имена, которые `looks_same` признаёт написаниями одного, — тот же
порог, по которому реестр сущности и сливает. Всё остальное остаётся как
есть.

Правила выходят с границами слова. Замена по словарю ищет обычным
текстом, и правило «Ли = Ли Мин» переписало бы «Лиза» в «Ли Минза»:
короткое имя сидит внутри десятка обычных слов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.registry import looks_same, normalize

#: Приставка, которой словарь замен помечает регулярное выражение.
REGEX_MARK = "re:"

#: Заголовок сохранённого словаря. Человек откроет файл и должен понять,
#: откуда он взялся и что будет, если строку убрать.
HEADER = (
    "# Глоссарий имён — собран из реестра «Анализа».\n"
    "# Слева написание, которое встретилось; справа — то, к которому\n"
    "# приводим. Строку можно убрать или поправить: словарь обычный.\n"
)


@dataclass
class Group:
    """Одно имя во всех написаниях, какие встретились в книге."""

    canonical: str = ""
    variants: list[str] = field(default_factory=list)
    entity_id: str = ""
    kind: str = ""
    #: Написание подтверждено человеком или пришло из глоссария.
    confirmed: bool = False
    first_chapter: int | None = None

    @property
    def names(self) -> list[str]:
        return [self.canonical, *self.variants]

    def as_dict(self) -> dict:
        return {"canonical": self.canonical, "variants": list(self.variants),
                "entity_id": self.entity_id, "kind": self.kind,
                "confirmed": self.confirmed,
                "first_chapter": self.first_chapter}


def _spellings(entity) -> list[str]:
    """Имена сущности, которые и правда написания одного и того же.

    Прозвище и второе имя сюда не попадают: их менять нельзя.
    """
    out, seen = [], set()
    for name in entity.names:
        name = (name or "").strip()
        key = normalize(name)
        if not key or key in seen:
            continue
        if name != entity.name and not looks_same(name, entity.name):
            continue
        seen.add(key)
        out.append(name)
    return out


def _pick(names: list[str], preferred: str, confirmed: bool) -> str:
    """Какое написание считать главным.

    Подтверждённое человеком сильнее всего: он уже сказал, как правильно.

    Дальше — более полное написание: у имён с китайского выпадают как раз
    буквы, «Ю Шен» получается из «Юй Шэн», а не наоборот. Имя самой
    записи преимущества не даёт: реестр завёл её под тем написанием,
    которое просто встретилось первым, и правотой это не является.

    Последним — по алфавиту. Не потому, что алфавит что-то значит, а
    потому, что у одного и того же реестра ответ должен быть один и тот
    же: иначе словарь менялся бы от порядка записей в файле.
    """
    if confirmed and preferred:
        return preferred
    return sorted(names, key=lambda n: (-len(n), n))[0]


def groups(registry) -> list[Group]:
    """Что стоит свести к одному написанию.

    Записи с одним-единственным написанием сюда не попадают: менять у них
    нечего, а в списке они были бы шумом.
    """
    found: list[Group] = []

    for entity in (registry.entities or {}).values():
        names = _spellings(entity)
        if not names:
            continue

        # Тот же человек мог осесть двумя записями — реестр их сливает не
        # всегда: разбор идёт кусками, и вторая запись заводится в другом
        # куске. Ищем близнеца среди уже собранных групп.
        twin = next((g for g in found
                     if g.kind == entity.type
                     and any(looks_same(a, b) for a in g.names for b in names)),
                    None)
        if twin is not None:
            for name in names:
                if all(normalize(name) != normalize(x) for x in twin.names):
                    twin.variants.append(name)
            if entity.confirmed and not twin.confirmed:
                twin.confirmed = True
                twin.canonical = entity.name
                twin.entity_id = entity.id
            twin.first_chapter = _earliest(twin.first_chapter,
                                           entity.first_chapter)
            continue

        # Главным пока ставим имя самой записи — то, под которым её вёл
        # реестр. Выбирать по-настоящему рано: к группе ещё могут
        # подтянуться близнецы, и выбор пришлось бы делать дважды.
        found.append(Group(
            canonical=entity.name,
            variants=[n for n in names if n != entity.name],
            entity_id=entity.id, kind=entity.type,
            confirmed=entity.confirmed,
            first_chapter=entity.first_chapter))

    for group in found:
        # Теперь группа собрана целиком — можно выбирать. Написания
        # берём из одного списка: считай мы главное по одному правилу, а
        # остальные по другому, одно из них потерялось бы.
        canonical = _pick(group.names, group.canonical, group.confirmed)
        group.variants = [n for n in group.names
                          if normalize(n) != normalize(canonical)]
        group.canonical = canonical

    return [g for g in found if g.variants]


def _earliest(a, b):
    numbers = [x for x in (a, b) if isinstance(x, int)]
    return min(numbers) if numbers else None


def rule_of(variant: str, canonical: str) -> str:
    """Одна строка словаря — с границами слова.

    Без границ «Тэо = Тео» переписало бы «Тэодора» в «Теодора»: замена по
    словарю ищет обычным текстом и про слова ничего не знает.

    Пробел возвращаем как есть: `re.escape` пишет его как `\\ ` — на
    поиск это не влияет, а файл человек открывает и правит руками, и
    имя из двух слов должно читаться именем, а не шифром.
    """
    body = re.escape(variant).replace("\\ ", " ")
    return f"{REGEX_MARK}\\b{body}\\b = {canonical}"


def as_dictionary(chosen, header: bool = True) -> str:
    """Словарь замен для `ops/replace` — тем же текстом «было = стало»."""
    lines = []
    for group in chosen or []:
        canonical = str(group.canonical or "").strip()
        if not canonical:
            continue
        for variant in group.variants:
            variant = str(variant or "").strip()
            if variant and normalize(variant) != normalize(canonical):
                lines.append(rule_of(variant, canonical))
    if not lines:
        return ""
    return (HEADER if header else "") + "\n".join(lines) + "\n"


def from_dicts(rows) -> list[Group]:
    """Группы обратно из того, что прислала страница.

    Человек мог сменить главное написание и выбросить лишние — словарь
    собирается по его выбору, а не по нашему предложению.
    """
    out = []
    for row in rows or []:
        row = row or {}
        canonical = str(row.get("canonical") or "").strip()
        if not canonical:
            continue
        variants = [str(v).strip() for v in (row.get("variants") or [])
                    if str(v).strip()]
        out.append(Group(canonical=canonical,
                         variants=[v for v in variants
                                   if normalize(v) != normalize(canonical)],
                         entity_id=str(row.get("entity_id") or ""),
                         kind=str(row.get("kind") or "")))
    return out


def merge_into(existing: str, addition: str) -> tuple[str, int]:
    """Дописать правила в уже существующий словарь книги.

    Переписать файл целиком нельзя: там лежат замены, которые человек
    вносил руками, и глоссарий не вправе их стирать — он про имена, а
    словарь про всё сразу.

    Правило, которое в файле уже есть, второй раз не добавляется: иначе
    список рос бы с каждым нажатием, а замены дублировались.
    Возвращает готовый текст и число дописанных строк.
    """
    from .replace import parse_dictionary

    existing = existing or ""
    known = {rule.find for rule in parse_dictionary(existing)}

    fresh = [line for line in (addition or "").splitlines()
             if line.strip() and not line.strip().startswith("#")]
    add = []
    for line in fresh:
        left = line.partition("=")[0].strip()
        if left.lower().startswith(REGEX_MARK):
            left = left[len(REGEX_MARK):].strip()
        if left and left not in known:
            known.add(left)
            add.append(line)

    if not add:
        return existing, 0

    tail = "\n".join(add) + "\n"
    if not existing.strip():
        return (HEADER + tail), len(add)
    return (existing.rstrip("\n") + "\n\n" + HEADER + tail), len(add)


def summary(found) -> dict:
    """Сводка для подписи: сколько имён и сколько написаний уйдёт."""
    found = list(found or [])
    return {"names": len(found),
            "variants": sum(len(g.variants) for g in found),
            "confirmed": sum(1 for g in found if g.confirmed)}


__all__ = ["Group", "HEADER", "REGEX_MARK", "as_dictionary", "from_dicts",
           "groups", "merge_into", "rule_of", "summary"]
