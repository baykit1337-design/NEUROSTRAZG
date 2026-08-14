"""Глоссарий: импорт от переводчика и выгрузка обратно.

Круг замыкается так: реестр собирается по книге, выгружается глоссарием,
скармливается переводчику перед следующей партией глав — и имена
перестают плавать. Обратно принимается то, что переводчик уже накопил.

Записи из глоссария считаются подтверждёнными сразу: их писал человек,
переубеждать его модель не должна.
"""

from __future__ import annotations

import csv
import io
import json

from core.registry import Entity, Registry

#: Форматы, которые принимаем и отдаём.
FORMATS = ("txt", "json", "csv", "md")

#: `ключ = значение`. Разделителем бывает и двоеточие, и стрелка.
SEPARATORS = ("=", "→", "->", "\t", ":")

#: Строки, которые в глоссарии не значат ничего.
COMMENTS = ("#", "//", ";")


def parse(text: str) -> list[tuple[str, str]]:
    """Пары «оригинал → перевод» из любого поддерживаемого формата.

    Формат определяется по содержимому, а не по расширению: файл могли
    переименовать, а глоссарий — это две колонки в любом виде.
    """
    text = (text or "").strip()
    if not text:
        return []

    if text[0] in "[{":
        pairs = _from_json(text)
        if pairs:
            return pairs

    # CSV узнаётся по запятой или точке с запятой в первой значимой строке.
    first = next((l for l in text.splitlines() if l.strip()
                  and not l.strip().startswith(COMMENTS)), "")
    if ("," in first or ";" in first) and not _has_separator(first):
        pairs = _from_csv(text)
        if pairs:
            return pairs

    return _from_lines(text)


def _has_separator(line: str) -> bool:
    return any(sep in line for sep in SEPARATORS)


def _from_json(text: str) -> list[tuple[str, str]]:
    try:
        data = json.loads(text)
    except ValueError:
        return []

    pairs: list[tuple[str, str]] = []
    if isinstance(data, dict):
        # Либо плоский словарь, либо {"entities": [...]} нашей выгрузки.
        items = data.get("entities")
        if isinstance(items, list):
            for item in items:
                name = str((item or {}).get("name") or "").strip()
                if name:
                    pairs.append((name, str((item or {}).get("translation") or "")))
            return pairs
        for key, value in data.items():
            if isinstance(value, (str, int, float)):
                pairs.append((str(key), str(value)))
        return pairs

    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("source") or "").strip()
                value = str(item.get("translation") or item.get("target") or "")
                if name:
                    pairs.append((name, value))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((str(item[0]), str(item[1])))
    return pairs


def _from_csv(text: str) -> list[tuple[str, str]]:
    try:
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    pairs = []
    for row in csv.reader(io.StringIO(text), dialect):
        if not row or not str(row[0]).strip():
            continue
        if str(row[0]).strip().startswith(COMMENTS):
            continue
        pairs.append((str(row[0]).strip(),
                      str(row[1]).strip() if len(row) > 1 else ""))
    # Заголовок таблицы значением не является.
    if pairs and pairs[0][0].lower() in ("name", "имя", "оригинал", "source", "key"):
        pairs = pairs[1:]
    return pairs


def _from_lines(text: str) -> list[tuple[str, str]]:
    pairs = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(COMMENTS):
            continue
        # Markdown-таблица: | оригинал | перевод |
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 2 and not set(cells[0]) <= set("-: "):
                if cells[0].lower() not in ("name", "имя", "оригинал"):
                    pairs.append((cells[0], cells[1]))
            continue

        for sep in SEPARATORS:
            if sep in line:
                left, _, right = line.partition(sep)
                if left.strip():
                    pairs.append((left.strip(), right.strip()))
                break
    return pairs


def load_into(registry: Registry, text: str, kind: str = "термин") -> int:
    """Вносит глоссарий в реестр. Записи сразу подтверждённые.

    Перевод кладётся в атрибуты, а не в имя: имя — то, как сущность
    называется в тексте, и подменять его нельзя, иначе сверка перестанет
    находить её в главах.
    """
    added = 0
    for name, value in parse(text):
        if not name.strip():
            continue
        entity = registry.find(name)
        if entity is None:
            entity = registry.add_entity(
                Entity(name=name, type=kind, confirmed=True), merge=False)
            added += 1
        entity.confirmed = True
        if value:
            entity.attributes["перевод"] = value
            entity.add_alias(value)
    return added


# ------------------------------------------------------------- выгрузка


def _rows(registry: Registry, types=None) -> list[tuple[str, str]]:
    """Пары «как встретилось → как писать».

    Смысл выгрузки в том, чтобы имена перестали плавать, поэтому слева
    стоит любой встреченный вариант, а справа — тот, которого держаться.
    Обратное («Тео = Тэо») велело бы переводчику писать вариант, то есть
    ровно то, от чего уходим.
    """
    wanted = set(types) if types else None
    rows = []
    for entity in sorted(registry.entities.values(), key=lambda e: e.name.lower()):
        if wanted and entity.type not in wanted:
            continue

        canonical = str(entity.attributes.get("перевод") or "").strip()
        if canonical:
            # Перевод задан — к нему и сводим все написания, включая имя.
            rows.append((entity.name, canonical))
            rows.extend((alias, canonical) for alias in entity.aliases
                        if alias.strip() and alias.strip() != canonical)
        elif entity.aliases:
            # Перевода нет, но варианты есть: сводим их к основному имени.
            rows.extend((alias, entity.name) for alias in entity.aliases
                        if alias.strip())
        else:
            # Ни перевода, ни вариантов — строка на заполнение переводчику.
            rows.append((entity.name, ""))
    return rows


def dump(registry: Registry, fmt: str = "txt", types=None) -> str:
    """Глоссарий в формате переводчика."""
    fmt = (fmt or "txt").lower().lstrip(".")
    rows = _rows(registry, types)

    if fmt == "json":
        return json.dumps({name: value for name, value in rows},
                          ensure_ascii=False, indent=2)
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(["имя", "перевод"])
        writer.writerows(rows)
        return out.getvalue()
    if fmt == "md":
        lines = ["| имя | перевод |", "|---|---|"]
        lines += [f"| {name} | {value} |" for name, value in rows]
        return "\n".join(lines) + "\n"

    return "".join(f"{name} = {value}\n" for name, value in rows)


def cards(registry: Registry, kind: str = "персонаж") -> list[dict]:
    """Карточки: имя, варианты, тип, атрибуты, связи, где появляется."""
    made = []
    for entity in sorted(registry.of_type(kind), key=lambda e: e.name.lower()):
        links = []
        for link in registry.links_of(entity.id):
            other = link.target if link.source == entity.id else link.source
            name = registry.entities[other].name if other in registry.entities else other
            direction = "→" if link.source == entity.id else "←"
            links.append({"type": link.type, "with": name, "direction": direction,
                          "since_chapter": link.since_chapter})

        chapters = sorted({e.chapter for e in registry.events
                           if e.chapter is not None
                           and entity.id in (e.actor, e.object)})
        made.append({
            "id": entity.id, "name": entity.name, "aliases": list(entity.aliases),
            "type": entity.type, "status": entity.status,
            "attributes": dict(entity.attributes),
            "first_chapter": entity.first_chapter,
            "links": links, "chapters": chapters,
            "confirmed": entity.confirmed,
        })
    return made


def cards_text(registry: Registry, kind: str = "персонаж") -> str:
    """Карточки простым текстом — годится и для .md, и для .docx."""
    lines = []
    for card in cards(registry, kind):
        lines.append(f"# {card['name']}")
        if card["aliases"]:
            lines.append(f"Варианты имени: {', '.join(card['aliases'])}")
        lines.append(f"Тип: {card['type']} · статус: {card['status']}")
        if card["first_chapter"] is not None:
            lines.append(f"Появляется с главы {card['first_chapter']}")
        for key, value in card["attributes"].items():
            lines.append(f"{key}: {value}")
        for link in card["links"]:
            lines.append(f"{link['type']} {link['direction']} {link['with']}")
        if card["chapters"]:
            shown = ", ".join(str(n) for n in card["chapters"][:20])
            more = " …" if len(card["chapters"]) > 20 else ""
            lines.append(f"Главы: {shown}{more}")
        lines.append("")
    return "\n".join(lines)
