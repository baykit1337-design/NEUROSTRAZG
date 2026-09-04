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
    from .dreamy import DreamySource
    from .fanqie import FanqieSource
    from .fanqiemirror import FanqieMirrorSource
    from .mvlempyr import MvlempyrSource
    from .novelcms import NovelCmsSource
    from .ranobelib import RanobeLibSource
    from .webnovel import WebnovelSource

    # Посредник идёт последним и по умолчанию не выбран намеренно: он
    # забирает закрытые главы, но ценой чужого сервера без шифрования.
    # Такой размен человек делает сам, а не получает молча.
    #
    # Сайт-слив — запасной путь на случай, когда молчат и Фанкью, и
    # посредник: там книга лежит открыто, но сайт сторонний и живёт
    # своей жизнью, поэтому тоже выбирается руками.
    #
    # Webnovel стоит последним не по важности, а потому что берёт не
    # каждую книгу: часть глав там платная, и такие остаются пропусками.
    # Выбирать его должен человек, знающий про этот размен.
    #
    # RanobeLIB стоит особняком: оттуда книга приходит уже по-русски, и
    # переводить её после скачивания не нужно вовсе. Это другой размен —
    # не «текст подешевле», а «чужой перевод вместо своего».
    # Dreamy стоит рядом с RanobeLIB и по той же причине: оттуда книга
    # приходит уже переведённой, только на английский. Это тоже размен
    # «чужой перевод вместо своего», и делает его человек сам.
    return [MvlempyrSource(), FanqieSource(), FanqieMirrorSource(),
            NovelCmsSource(), WebnovelSource(), RanobeLibSource(),
            DreamySource()]


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
