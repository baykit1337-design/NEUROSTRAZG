"""Перевод названий из рейтинга (5.3 ТЗ NEUROSTRAZH).

Список на китайском бесполезен: по нему не понять, о чём книга, а значит
и незачем смотреть рейтинг. Перевод делает модуль из части 2.

Кэш по `book_id`, а не по тексту названия: идентификатор у книги один и
навсегда, а название на сайте иногда правят — и перевод из-за одной
поправленной запятой запрашивался бы заново.
"""

from __future__ import annotations

import json
import logging
import threading

from .history import DATA_DIR

log = logging.getLogger(__name__)

TITLES_FILE = DATA_DIR / "titles.json"

#: Сколько названий отдавать модели за раз. Полсотни коротких строк —
#: один дешёвый запрос вместо полусотни дорогих.
BATCH = 25

PROMPT = """Ниже список названий книг на китайском, по одному в строке, с
номерами.

Переведи каждое на русский. Верни СТРОГО JSON: объект, где ключ — номер
строки, значение — перевод. Без пояснений и без текста вокруг.

Названия художественные: переводи по смыслу, а не пословно. Имена
собственные передавай так, как их принято передавать по-русски.

{lines}"""

_LOCK = threading.Lock()


def _load() -> dict:
    if not TITLES_FILE.is_file():
        return {}
    try:
        data = json.loads(TITLES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Битый кэш переводов названий — начинаем заново")
        return {}
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    TITLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TITLES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(TITLES_FILE)


def known() -> dict:
    """Что уже переведено: book_id → перевод."""
    with _LOCK:
        return dict(_load())


def remember(pairs: dict) -> dict:
    with _LOCK:
        data = _load()
        data.update({str(k): str(v) for k, v in pairs.items() if str(v).strip()})
        _write(data)
        return dict(data)


def forget() -> None:
    with _LOCK:
        _write({})


def translate(rows, client, model: str = "", force: bool = False) -> dict:
    """Переводит названия строк рейтинга. Переведённые не перезапрашивает."""
    from llm.cache import parse_json

    have = known()
    todo = [row for row in rows
            if row.book_id and (force or row.book_id not in have)]

    added = {}
    broken = 0
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        lines = "\n".join(f"{i}. {row.name}" for i, row in enumerate(batch, 1))
        answer = client.generate(PROMPT.format(lines=lines), model=model)

        try:
            found = parse_json(answer)
        except ValueError:
            # Перевод — удобство, а не работа программы. Испорченный ответ
            # на одну пачку не должен ронять весь запрос и терять уже
            # переведённое: пропускаем пачку и говорим сколько.
            log.warning("Модель вернула не JSON — пачка названий пропущена")
            broken += len(batch)
            continue

        for index, row in enumerate(batch, 1):
            text = str(found.get(str(index)) or found.get(index) or "").strip()
            if text:
                added[row.book_id] = text

    if added:
        have = remember(added)
    return {"titles": {row.book_id: have.get(row.book_id, "") for row in rows},
            "translated": len(added), "broken": broken,
            "cached": len(rows) - len(added) - broken}
