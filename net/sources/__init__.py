"""Источники книг.

Раньше качалка знала ровно один сайт, и его адреса были вписаны прямо в
неё. Второй источник так уже не добавить: пришлось бы либо копировать
качалку целиком, либо разводить условия по всему коду.

Поэтому источник — отдельный модуль с тремя обязанностями: найти книгу,
вернуть оглавление, вернуть текст главы. Всё остальное — папки, имена,
прогресс, докачка, прокси, автопроба — общее и живёт в качалке.
"""

from __future__ import annotations

from .base import Source, SourceBroken

#: Порядок здесь же и порядок в списке на экране.
def all_sources() -> list:
    from .fanqie import FanqieSource
    from .mvlempyr import MvlempyrSource

    return [MvlempyrSource(), FanqieSource()]


def get(name: str) -> Source:
    """Источник по ключу. Пустой ключ — первый в списке."""
    wanted = (name or "").strip().lower()
    found = all_sources()
    if not wanted:
        return found[0]
    for source in found:
        if source.key == wanted:
            return source
    raise SourceBroken(f"Неизвестный источник: {name}")


__all__ = ["Source", "SourceBroken", "all_sources", "get"]
