"""Что обязан уметь источник и на каком языке он говорит с качалкой.

Внутреннее представление книги и главы взято из `mvl/api.py` — то самое,
на котором уже работают докачка, имена файлов и отчёты. Заводить второе
ради второго источника было бы ошибкой: разошлись бы они на первой же
правке.
"""

from __future__ import annotations

from mvl.api import Chapter, Novel, Toc


class SourceBroken(Exception):
    """Источник изменился и разобрать его больше нельзя.

    Отдельно от сетевых ошибок: «сайт не ответил» лечится повтором, а
    «структура ответа другая» — только правкой модуля. Смешивать их значит
    предлагать человеку жать «повторить» до бесконечности.
    """


class Source:
    """Интерфейс источника.

    Три метода. Всё остальное — папки, имена, прогресс, докачка, прокси —
    общее и живёт в качалке.
    """

    #: Ключ для настроек и запросов.
    key = ""
    #: Как называется на экране.
    name = ""
    #: Что писать в самом поле, серым. У источников оно разное: у одного
    #: слаг, у другого числовой код, и общий заполнитель сбивал бы с толку.
    placeholder = ""
    #: Пояснение под полем.
    hint = ""
    #: Нужен ли этому источнику прокси-пул.
    needs_proxy = False

    def find(self, client, query: str) -> Novel:
        """Книга по ссылке, слагу или коду."""
        raise NotImplementedError

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        """Оглавление в заданном диапазоне."""
        raise NotImplementedError

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        """Заголовок и текст одной главы."""
        raise NotImplementedError

    def as_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "hint": self.hint,
                "placeholder": self.placeholder or self.hint,
                "needs_proxy": self.needs_proxy}


__all__ = ["Chapter", "Novel", "Source", "SourceBroken", "Toc"]
