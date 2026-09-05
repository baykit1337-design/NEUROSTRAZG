"""Ответ WordPress REST: где у книги лежат её слова.

Каталог MVLEMPYR — обычный WordPress, и оба, кто с ним работает, читают
одну и ту же запись: рейтинг — чтобы нарисовать раскрытую строку,
качалка — чтобы завести книгу. Читали они её по-разному, и это стоило
дорого: рейтинг умел доставать описание, жанры и метки, а качалка с того
же самого ответа брала только имя, автора и число глав. В библиотеке
из-за этого раскрывать было нечего — данные лежали в том же JSON, просто
никто их оттуда не доставал.

Поэтому разбор один и живёт внизу: `net/` и `mvl/` оба смотрят сюда, и
разойтись им больше негде.

Сети тут нет — только разбор уже полученного словаря.
"""

from __future__ import annotations

#: Где может лежать описание книги. Перебор, а не одно имя: у WordPress
#: описание кладут кто во что горазд — тема, плагин произвольных полей,
#: собственное поле типа записи. Последним стоит `content`, который есть
#: **всегда**: это тело записи, и переименуй сайт своё поле, описание всё
#: равно найдётся.
#:
#: Точные имена живьём не проверялись: каталог из песочницы недоступен.
#: Поэтому перебор — способ не гадать, а попробовать все.
ABOUT_FIELDS = ("description", "synopsis", "summary", "novel-description",
                "excerpt", "content")

#: Всё, чем сайт описывает книгу словами, кроме жанров.
TAG_FIELDS = ("tags", "novel-tags", "tag")

#: Жанры лежат отдельным полем и в карточке стоят отдельной строкой.
GENRE_FIELD = "genre"


def field(item: dict, name: str, default=None):
    """Поле книги, где бы WordPress его ни положил.

    Свои поля WordPress отдаёт то на верхнем уровне, то в `acf`, то в
    `meta` — зависит от того, как настроен тип записи. Гадать нельзя:
    ошибись — и вместо рейтинга получится список пустых строк.
    """
    for where in (item, item.get("acf"), item.get("meta")):
        if isinstance(where, dict) and where.get(name) not in (None, ""):
            return where[name]
    return default


def text(value) -> str:
    """Текст из того, что отдал WordPress.

    Заголовок приходит объектом `{"rendered": "..."}`, остальное —
    строкой или числом. Списки сайт кладёт как список названий.
    """
    if isinstance(value, dict):
        value = value.get("rendered", "")
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v)
    return str(value or "").strip()


def rows(value) -> list:
    """Список названий из того, что положил WordPress."""
    if value in (None, "", []):
        return []
    if isinstance(value, (list, tuple)):
        return [text(v) for v in value if text(v)]
    return [part.strip() for part in text(value).split(",") if part.strip()]


def plain(value) -> str:
    """Описание без разметки.

    WordPress отдаёт тело записи готовым HTML: абзацы, переносы, иногда
    ссылки. В карточке оно показывается текстом, и теги там были бы
    видны как есть.
    """
    said = text(value)
    if "<" not in said:
        return said
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(said, "lxml")
    # Абзацы разделяем пустой строкой, иначе описание слипается в
    # одну простыню без единого разрыва.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    parts = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    if parts:
        return "\n\n".join(part for part in parts if part)
    return soup.get_text("\n", strip=True)


def about_of(item: dict) -> dict:
    """Что каталог рассказывает о книге словами.

    Отдаёт три ключа: `about`, `genres`, `tags`. Жанры и метки держатся
    порознь — в карточке это разные строки, и сваливать их в одну кучу
    значит потерять, что из этого жанр.
    """
    about = ""
    for name in ABOUT_FIELDS:
        about = plain(field(item, name))
        if about:
            break

    tags: list = []
    for name in TAG_FIELDS:
        tags.extend(rows(field(item, name)))

    return {"about": about,
            "genres": rows(field(item, GENRE_FIELD)),
            "tags": tags}
