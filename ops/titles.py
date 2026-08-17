"""Перевод названий и описаний из рейтинга (5.3, 3.1 ТЗ NEUROSTRAZH).

Список на китайском бесполезен: по нему не понять, о чём книга, а значит
и незачем смотреть рейтинг. Перевод делает модуль из части 2.

Кэш по `book_id`, а не по тексту: идентификатор у книги один и навсегда, а
название и описание на сайте иногда правят — и перевод из-за одной
поправленной запятой запрашивался бы заново.

Описания живут в своём файле: названий полсотни на срез и они короткие, а
описание — абзац, и переводится оно по одному, по кнопке.
"""

from __future__ import annotations

import json
import logging
import threading

from .history import DATA_DIR

log = logging.getLogger(__name__)

TITLES_FILE = DATA_DIR / "titles.json"
ABSTRACTS_FILE = DATA_DIR / "abstracts.json"

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

ABSTRACT_PROMPT = """Ниже описание книги с китайского сайта.

Переведи его на русский. Верни только перевод: ни пояснений, ни исходного
текста, ни кавычек вокруг. Разбиение на абзацы сохрани.

{text}"""

_LOCK = threading.Lock()


def _load(path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Битый кэш переводов (%s) — начинаем заново", path.name)
        return {}
    return data if isinstance(data, dict) else {}


def _write(path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def known() -> dict:
    """Что уже переведено: book_id → перевод названия."""
    with _LOCK:
        return dict(_load(TITLES_FILE))


def remember(pairs: dict) -> dict:
    with _LOCK:
        data = _load(TITLES_FILE)
        data.update({str(k): str(v) for k, v in pairs.items() if str(v).strip()})
        _write(TITLES_FILE, data)
        return dict(data)


def forget() -> None:
    with _LOCK:
        _write(TITLES_FILE, {})


def abstracts() -> dict:
    """Переводы описаний: book_id → перевод."""
    with _LOCK:
        return dict(_load(ABSTRACTS_FILE))


def abstract_of(book_id) -> str:
    """Перевод описания одной книги. Пусто — ещё не переводили."""
    return abstracts().get(str(book_id), "")


def remember_abstract(book_id, text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    with _LOCK:
        data = _load(ABSTRACTS_FILE)
        data[str(book_id)] = text
        _write(ABSTRACTS_FILE, data)
    return text


def forget_abstracts() -> None:
    with _LOCK:
        _write(ABSTRACTS_FILE, {})


def translate_abstract(book_id, text: str, client, model: str = "",
                       force: bool = False) -> str:
    """Перевод описания книги. Переведённое не перезапрашивает (3.1 ТЗ).

    Описание переводится по одному и по кнопке: их полсотни на срез, а
    читают из них два-три. Гнать все в модель ради «вдруг откроют» — это
    полсотни лишних запросов на каждый снятый рейтинг.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Описания у книги нет — переводить нечего.")

    if not force:
        have = abstract_of(book_id)
        if have:
            return have

    answer = (client.generate(ABSTRACT_PROMPT.format(text=text),
                              json_only=False, model=model) or "").strip()
    if not answer:
        raise ValueError("Модель вернула пустой ответ.")
    return remember_abstract(book_id, answer)


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
