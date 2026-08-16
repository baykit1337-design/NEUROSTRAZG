"""Подробности книги из рейтинга и их кэш (2.4 ТЗ NEUROSTRAZH).

Строка рейтинга разворачивается по клику, и данные для неё подтягиваются
лениво — по первому раскрытию. Ходить на сайт за каждым раскрытием
незачем: описание, жанр и объём у книги меняются раз в месяц, а строк в
срезе полсотни.

Поэтому карточка кладётся в `data/books/{bookId}.json` и дальше берётся
оттуда. Срок жизни у кэша есть, но щедрый: устаревшее описание — не беда,
а лишний запрос к сайту при каждом клике — беда.
"""

from __future__ import annotations

import json
import logging
import time

from .history import DATA_DIR

log = logging.getLogger(__name__)

BOOK_DIR = DATA_DIR / "books"

#: Сколько держать карточку свежей. Описание и жанр у книги постоянны, а
#: число глав растёт — сутки тут разумный размен.
FRESH_HOURS = 24


def path_for(book_id):
    """Куда ляжет карточка. None — код книги никуда не годится."""
    from .covers import safe_id

    ident = safe_id(book_id)
    return (BOOK_DIR / f"{ident}.json") if ident else None


def load(book_id, max_age_hours: int = FRESH_HOURS) -> dict | None:
    """Карточка из кэша. None — её нет или она уже несвежая."""
    path = path_for(book_id)
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.info("Битая карточка книги %s (%s) — перечитаем с сайта",
                 book_id, exc)
        return None
    if not isinstance(data, dict):
        return None

    saved = data.get("saved_at")
    if max_age_hours and isinstance(saved, (int, float)):
        if time.time() - saved > max_age_hours * 3600:
            return None
    return data


def save(book_id, found: dict) -> dict:
    """Кладёт карточку в кэш. Возвращает то, что сохранено."""
    path = path_for(book_id)
    data = dict(found or {})
    data["saved_at"] = time.time()
    if path is None:
        return data

    try:
        BOOK_DIR.mkdir(parents=True, exist_ok=True)
        # Через временный файл: половина JSON на диске читается как битая
        # карточка и чинится только руками.
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.info("Карточку книги %s не записать: %s", book_id, exc)
    return data


def forget(book_id) -> bool:
    """Убирает карточку из кэша — чтобы перечитать её с сайта."""
    path = path_for(book_id)
    if path is None or not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def state() -> dict:
    """Сколько карточек накопилось."""
    if not BOOK_DIR.exists():
        return {"dir": str(BOOK_DIR), "count": 0}
    return {"dir": str(BOOK_DIR),
            "count": sum(1 for p in BOOK_DIR.iterdir()
                         if p.is_file() and p.suffix == ".json")}
