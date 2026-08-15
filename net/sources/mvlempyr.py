"""Источник MVLEMPYR — тот, с которого качалка начиналась.

Логика разбора осталась в `mvl/api.py`: переносить её сюда значило бы
переписать половину рабочего кода ради красоты. Здесь только оболочка,
приводящая её к общему для источников виду.
"""

from __future__ import annotations

from mvl import api

from .base import Chapter, Novel, Source, Toc


class MvlempyrSource(Source):
    key = "mvlempyr"
    name = "MVLEMPYR"
    placeholder = "insect-tamers-ascension"
    hint = ("Можно вставить ссылку на книгу, слаг "
            "(insect-tamers-ascension) или числовой код (6615).")
    #: Витрину режет провайдер, без прокси текст глав не приходит.
    needs_proxy = True

    def find(self, client, query: str) -> Novel:
        return api.find_novel(client, query)

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        return api.fetch_toc(client, novel, first=first, last=last,
                             on_progress=on_progress)

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        return api.fetch_chapter(client, chapter)
