"""Разбор рейтинга Фанкью (5.2 ТЗ NEUROSTRAZH).

Задача — находить, что набирает обороты, не листая сайт на китайском и не
копируя идентификаторы руками.

Данные берутся из объекта `window.__INITIAL_STATE__`, а не из вёрстки: там
их больше, чем видно на странице, и меняются они реже разметки. Разбирать
HTML пришлось бы заново после каждой правки дизайна.

Три поля — название, автор и описание — зашифрованы шрифтом. Всё
остальное чистое, поэтому даже без расшифровки видно позицию, движение,
число читающих и `bookId`, а этого хватает, чтобы качать книги и следить
за ростом.

Сам сайт отдаёт только суточный срез. Историю программа копит сама — см.
`ops/rank.py`.
"""

from __future__ import annotations

import json
import logging
import re

from . import categories, fanqiefont
from .base import SourceBroken
from .fanqie import SITE

log = logging.getLogger(__name__)

#: Сколько строк держать в срезе. Сайт отдаёт сотню, дальше пятидесяти
#: рейтинг всё равно не смотрят.
TOP = 50

#: Объект с данными страницы. Кавычки внутри бывают любые, поэтому режем до
#: конца тега, а разбирает уже JSON.
STATE = re.compile(
    r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*[;<]", re.S)

#: Дата, до которой собрана статистика: «统计至 08-14 24:00».
STATS_DATE = re.compile(r"(\d{1,2}-\d{1,2})\s*\d{1,2}:\d{2}")

#: Ссылки левого меню — запасной способ узнать разделы.
MENU_LINK = re.compile(r'href="(/rank/(\d)_(\d)_(\d+))"')


class RankRow:
    """Одна строка рейтинга."""

    __slots__ = ("place", "book_id", "name", "author", "readers", "category",
                 "diff", "words", "status", "last_chapter", "secret", "cover")

    def __init__(self, place=0, book_id="", name="", author="", readers=0,
                 category="", diff=None, words=0, status="", last_chapter="",
                 secret=False, cover=""):
        self.place = place
        self.book_id = str(book_id)
        self.name = name
        self.author = author
        self.readers = readers
        self.category = category
        #: Насколько сдвинулась позиция — сайт считает это сам.
        self.diff = diff
        self.words = words
        self.status = status
        self.last_chapter = last_chapter
        #: Название расшифровать не удалось.
        self.secret = secret
        #: Адрес обложки на сайте. Он подписан и живёт недолго, поэтому
        #: наружу отдаётся не он, а путь к своей копии.
        self.cover = cover

    def as_dict(self) -> dict:
        return {"place": self.place, "book_id": self.book_id, "name": self.name,
                "author": self.author, "readers": self.readers,
                "category": self.category, "diff": self.diff,
                "words": self.words, "status": self.status,
                "last_chapter": self.last_chapter, "secret": self.secret,
                "cover": self.cover,
                "link": f"{SITE}/page/{self.book_id}"}

    @classmethod
    def from_dict(cls, data: dict) -> RankRow:
        data = data or {}
        return cls(
            place=int(data.get("place") or 0),
            book_id=str(data.get("book_id") or ""),
            name=str(data.get("name") or ""),
            author=str(data.get("author") or ""),
            readers=_readers(data.get("readers")),
            category=str(data.get("category") or ""),
            diff=data.get("diff"),
            words=int(data.get("words") or 0),
            status=str(data.get("status") or ""),
            last_chapter=str(data.get("last_chapter") or ""),
            secret=bool(data.get("secret")),
            cover=str(data.get("cover") or ""),
        )

    def __eq__(self, other):
        return isinstance(other, RankRow) and self.as_dict() == other.as_dict()

    def __repr__(self):
        return f"RankRow({self.place}, {self.name!r}, {self.readers})"


#: «12.3万» — китайская запись «сто двадцать три тысячи». Без разбора этих
#: суффиксов число читателей превращается в 12 вместо 123000.
SUFFIXES = {"万": 10_000, "亿": 100_000_000, "k": 1_000, "K": 1_000,
            "w": 10_000, "W": 10_000}


def _readers(value) -> int:
    """Число читающих из чего угодно, что отдаёт сайт."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return 0

    found = re.match(r"([\d.,]+)\s*([万亿kKwW]?)", text)
    if not found:
        return 0
    try:
        number = float(found.group(1).replace(",", ""))
    except ValueError:
        return 0
    return int(number * SUFFIXES.get(found.group(2), 1))


class Diagnosis(SourceBroken):
    """Разбор не удался — с подробностями, а не общими словами.

    «Источник изменился» без деталей не отличает севший сайт от смены
    разметки, и чинить по такому сообщению нечего.
    """

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def state_of(html: str) -> dict:
    """Объект `__INITIAL_STATE__` со страницы."""
    found = STATE.search(html or "")
    if not found:
        raise Diagnosis(
            "На странице нет объекта __INITIAL_STATE__ — разбирать нечего.",
            {"page_size": len(html or ""), "state_found": False})
    try:
        return json.loads(found.group(1))
    except ValueError as exc:
        raise Diagnosis(
            "Объект __INITIAL_STATE__ найден, но не разобрался как JSON.",
            {"page_size": len(html or ""), "state_found": True,
             "json_error": str(exc)}) from exc


def category_list(html: str) -> dict:
    """Категории с сайта: `{male: [...], female: [...]}`.

    Забирается один раз и кэшируется вызывающим: перебирать номера жанров
    вслепую бессмысленно, они идут не подряд.
    """
    try:
        state = state_of(html)
    except Diagnosis:
        state = {}

    found = _dig(state, "rankCategoryTypeList") or {}
    out = {}
    for side, key in ((categories.MALE, "male"), (categories.FEMALE, "female")):
        items = found.get(key) if isinstance(found, dict) else None
        rows = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            ident = item.get("id") or item.get("category_id")
            if ident is None:
                continue
            rows.append(categories.translate(
                str(ident), str(item.get("name") or "")))
        if not rows:
            # Меню страницы — запасной источник тех же номеров.
            rows = [categories.translate(c) for c in _menu_ids(html, side)] \
                or [categories.translate(c) for c in categories.FALLBACK[side]]
        out[side] = rows
    return out


def _menu_ids(html: str, audience: str) -> list[str]:
    seen = []
    for _, side, _, ident in MENU_LINK.findall(html or ""):
        if side == audience and ident not in seen:
            seen.append(ident)
    return seen


def stats_date(html: str) -> str:
    """До какого момента собрана статистика — по шапке страницы.

    Это точнее даты запроса: рейтинг обновляется днём, и срез, снятый
    утром, относится к прошлым суткам.
    """
    found = STATS_DATE.search(html or "")
    return found.group(1) if found else ""


def parse(html: str, limit: int = TOP, table: dict | None = None) -> dict:
    """Строки рейтинга и всё, что о срезе известно."""
    state = state_of(html)
    rank = _dig(state, "rank") if isinstance(state, dict) else {}
    books = _dig(rank if isinstance(rank, dict) else state, "book_list")

    if not isinstance(books, list) or not books:
        raise Diagnosis(
            "Объект найден, но список книг в нём пуст.",
            {"page_size": len(html or ""), "state_found": True,
             "book_list": 0})

    rows = []
    for index, item in enumerate(books, 1):
        if not isinstance(item, dict):
            continue
        book_id = item.get("bookId") or item.get("book_id")
        if not book_id:
            continue

        name = fanqiefont.decode(item.get("bookName") or "", table)
        author = fanqiefont.decode(item.get("author") or "", table)
        rows.append(RankRow(
            place=int(item.get("currentPos") or index),
            book_id=str(book_id),
            name=name,
            author=author,
            readers=_readers(item.get("read_count") or item.get("readCount")),
            diff=_int_or_none(item.get("rankPosDiff")),
            words=int(item.get("wordNumber") or 0),
            status="завершена" if str(item.get("creationStatus")) == "0"
                   else "продолжается",
            # Название последней главы шрифтом не подменяется.
            last_chapter=str(item.get("lastChapterTitle") or ""),
            secret=fanqiefont.has_secret(name) or fanqiefont.has_secret(author),
            # Обложка шифром не затронута. Ссылка подписана и с сроком
            # действия — в сохранённом срезе она протухнет, поэтому
            # картинку кладут в свой кэш, а сюда попадает только адрес.
            cover=str(item.get("thumbUri") or item.get("thumb_uri") or ""),
        ))

    return {
        "rows": rows[:limit],
        "total": _int_or_none(_dig(rank, "total_num")) or len(rows),
        "version": str(_dig(rank, "rankVersion") or ""),
        "stats_date": stats_date(html),
        "page": _int_or_none(_dig(rank, "defaultPage")) or 1,
    }


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dig(data, key: str):
    """Первое значение по ключу на любой глубине."""
    if isinstance(data, dict):
        if key in data and data[key] not in (None, ""):
            return data[key]
        for value in data.values():
            found = _dig(value, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _dig(value, key)
            if found is not None:
                return found
    return None


# ------------------------------------------------------------- запросы


def _font_table(client, html: str):
    """Таблица подстановки и отчёт о разборе (2.5 ТЗ).

    Возвращает пару «таблица, отчёт». Таблица `None` — расшифровки нет, а
    отчёт объясняет, на каком шаге всё встало: не нашёлся шрифт в стилях,
    не скачался файл, не разобрался, или разобрался, но подстановок ноль.
    """
    family, _ = fanqiefont.font_of(html)
    if not family:
        return None, fanqiefont.FontReport(
            error="в стилях страницы нет шрифта с подменой знаков")

    if fanqiefont.known(family):
        return (fanqiefont.table_for(family),
                fanqiefont.report_for(family=family))

    addresses = fanqiefont.sources_of(html)
    if not addresses:
        return None, fanqiefont.FontReport(
            family=family,
            error="шрифт в стилях назван, но адрес файла не найден")

    # Один шрифт лежит в нескольких форматах, и с первым может не выйти:
    # `.woff2` сжат brotli, а без этого пакета он не откроется вовсе.
    # Поэтому перебираем адреса по порядку и сдаёмся только после всех.
    last = None
    for url in addresses:
        try:
            # Файл шрифта — двоичный, поэтому берём тело как есть.
            response = client.get(url)
            data = getattr(response, "content", None)
            if not data:
                last = fanqiefont.FontReport(
                    family=family, url=url, error="файл шрифта пришёл пустым")
                continue
            table = fanqiefont.table_for(family, data, url=url)
            return table, fanqiefont.report_for(family=family)
        except fanqiefont.FontUnavailable as exc:
            # Без имён рейтинг всё равно полезен: позиция, движение и код
            # книги приходят чистыми.
            log.warning("Шрифт %s не подошёл: %s", url, exc)
            last = fanqiefont.report_for(family=family) or fanqiefont.FontReport(
                family=family, url=url, downloaded=True, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — шрифт не главное
            log.warning("Шрифт %s не скачался: %s", url, exc)
            last = fanqiefont.FontReport(
                family=family, url=url, error=f"файл не скачался: {exc}")

    log.warning("Названия останутся зашифрованными: перебрали %s адресов",
                len(addresses))
    return None, last


def fetch(client, audience: str = categories.MALE, kind: str = categories.READING,
          category: str = "", limit: int = TOP) -> dict:
    """Срез рейтинга прямо сейчас."""
    if audience not in categories.AUDIENCES:
        raise ValueError(f"Неизвестная аудитория: {audience}")
    if kind not in categories.KINDS:
        raise ValueError(f"Неизвестный вид рейтинга: {kind}")
    category = str(category or categories.FALLBACK[audience][0])

    url = f"{SITE}{categories.path(audience, kind, category)}"
    html = client.get_text(url)

    table, font_report = _font_table(client, html)
    try:
        found = parse(html, limit=limit, table=table)
    except Diagnosis as exc:
        # Диагностика вместо общих слов: по ней видно, сел ли сайт, сменилась
        # ли разметка или дело только в шрифте.
        exc.details.setdefault("url", url)
        exc.details.setdefault("font", bool(table))
        if font_report is not None:
            exc.details.setdefault("font_details", font_report.as_dict())
        raise

    found.update(audience=audience, kind=kind, category=category,
                 board=categories.board_key(audience, kind),
                 decoded=table is not None,
                 # 2.5: «расшифровать не удалось» — не ответ. Подробности
                 # едут вместе со срезом, чтобы было понятно, что чинить.
                 font=font_report.as_dict() if font_report else {})
    return found


def fetch_categories(client, audience: str = categories.MALE) -> dict:
    """Список категорий. Забирается один раз, дальше берётся из кэша."""
    first = categories.FALLBACK[audience][0]
    url = f"{SITE}{categories.path(audience, categories.READING, first)}"
    return category_list(client.get_text(url))


# ------------------------------------------------------ страница книги


#: Что о книге известно из среза, а что — только со страницы.
def book_page(html: str, table: dict | None = None) -> dict:
    """Подробности книги со страницы `/page/{bookId}` (2.4 ТЗ).

    Берём из того же `__INITIAL_STATE__`, ветка `page`: в срезе рейтинга
    описания и жанра нет вовсе, а без них непонятно, стоит ли книгу
    вообще брать.

    Разбор нарочно нестрогий: сайт меняет имена полей, и терять из-за
    одного переименованного ключа всю карточку незачем — чего нет, того
    просто нет.
    """
    state = state_of(html)
    page = _dig(state, "page")
    data = page if isinstance(page, dict) else state
    book = _dig(data, "bookInfo")
    if not isinstance(book, dict):
        book = data if isinstance(data, dict) else {}

    def text(*names):
        for name in names:
            found = book.get(name)
            if found not in (None, "", []):
                return fanqiefont.decode(str(found), table)
        return ""

    def number(*names):
        for name in names:
            found = book.get(name)
            try:
                if found not in (None, ""):
                    return int(found)
            except (TypeError, ValueError):
                continue
        return 0

    name = text("bookName", "book_name")
    author = text("author")
    abstract = text("abstract", "bookAbstract", "description")

    return {
        "book_id": str(book.get("bookId") or book.get("book_id") or ""),
        "name": name,
        "author": author,
        "author_id": str(book.get("authorId") or book.get("author_id")
                         or book.get("uid") or ""),
        "abstract": abstract,
        # Описание тоже подменяется шрифтом: без пометки на его месте
        # будет строка из служебных квадратиков.
        "secret": (fanqiefont.has_secret(name)
                   or fanqiefont.has_secret(author)
                   or fanqiefont.has_secret(abstract)),
        "category": text("category", "categoryName"),
        "tags": _tags(book),
        "words": number("wordNumber", "word_number"),
        # `chapterTotal` — то, чем сайт считает главы сейчас. Прежние имена
        # оставлены на случай отката: без нового в карточке книги стояло
        # «глав —», хотя число лежало рядом.
        "chapters": number("chapterTotal", "serialCount", "chapterNumber",
                           "chapter_count"),
        "status": "завершена" if str(book.get("creationStatus")) == "0"
                  else "продолжается",
        "last_chapter": str(book.get("lastChapterTitle") or ""),
        "updated": str(book.get("lastChapterUpdateTime")
                       or book.get("lastPublishTime") or ""),
        "first_published": str(book.get("firstOnlineTime")
                               or book.get("createTime") or ""),
        "first_chapter_id": str(book.get("firstChapterId") or ""),
        "last_chapter_id": str(book.get("lastChapterId") or ""),
        "cover": str(book.get("thumbUri") or book.get("audioThumbUri") or ""),
        "link": f"{SITE}/page/{book.get('bookId') or book.get('book_id') or ''}",
    }


def _tags(book: dict) -> list:
    """Теги книги. Приходят то списком, то строкой через запятую."""
    for name in ("tags", "tagList", "categoryTags"):
        found = book.get(name)
        if isinstance(found, list):
            return [str(t.get("name") if isinstance(t, dict) else t).strip()
                    for t in found if str(t).strip()]
        if isinstance(found, str) and found.strip():
            return [part.strip() for part in re.split(r"[,，;]", found)
                    if part.strip()]
    return []


def fetch_book(client, book_id: str) -> dict:
    """Страница книги целиком: подробности плюс расшифровка."""
    book_id = str(book_id or "").strip()
    if not book_id:
        raise ValueError("Не указан код книги")

    url = f"{SITE}/page/{book_id}"
    html = client.get_text(url)
    table, _ = _font_table(client, html)
    found = book_page(html, table)
    found.setdefault("book_id", book_id)
    if not found["book_id"]:
        found["book_id"] = book_id
    return found
