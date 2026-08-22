"""Рейтинг MVLEMPYR.

Рейтинга как отдельной страницы у сайта нет. Витрина забирает **весь**
каталог одним запросом к WordPress и сортирует его прямо в браузере: у
каждой книги лежат три готовых места — недельное, месячное и за всё
время. Поэтому и здесь никакой вёрстки не разбирается: берём каталог и
сортируем сами. Разметка страницы при этом может меняться сколько
угодно — рейтинг от неё не зависит.

Что это даёт по сравнению с Фанкью: у MVLEMPYR нет числа читающих, зато
есть средний балл, число глав и состояние книги («пишется», «закончена»,
«заморожена», «брошена»). Движение по местам считается, как и раньше,
своей историей — сайт хранит только сегодняшний срез.

Живой проверки этого модуля в песочнице не было: `chap.heliosarchive.online`
из неё недоступен (шлюз отвечает 403 на любой хост вне списка). Разбор
написан по исходнику страницы рейтинга и покрыт тестами на настоящих
ответах; первый живой запуск — на машине человека.
"""

from __future__ import annotations

import logging

from mvl.client import HttpError

from .base import SourceBroken
from .rank import RankRow

log = logging.getLogger(__name__)

#: Ключ сайта. Он же попадает в имя файла среза и отличает историю
#: MVLEMPYR от фанкьюшной.
SITE_KEY = "mvlempyr"

#: Витрина.
SITE = "https://www.mvlempyr.app"

#: Каталог. Это обычный WordPress REST: тип записи `mvl-novels`.
CATALOGUE = "https://chap.heliosarchive.online/wp-json/wp/v2/mvl-novels"

#: Обложки лежат отдельно и называются по коду книги.
COVER = "https://assets.mvlempyr.app/images/{size}/{code}.webp"
COVER_SIZE = 600

#: Сколько записей просить за раз. Столько же просит сама витрина.
PAGE = 1000

#: Предохранитель от бесконечного листания, если сайт перестанет отдавать
#: заголовок с общим числом страниц.
MAX_PAGES = 40

#: Сколько строк оставлять в срезе. Витрина показывает двести, и это
#: разумно: дальше рейтинг всё равно не смотрят, а файл среза растёт.
TOP = 200

#: Три доски и поле, по которому каждая сортируется.
BOARDS = {
    "weekly": "За неделю",
    "monthly": "За месяц",
    "alltime": "За всё время",
}
PLACE_FIELD = {
    "weekly": "weekly-rank",
    "monthly": "monthly-rank",
    "alltime": "rank",
}

#: Состояние книги. Сайт пишет его по-английски и с опечаткой в
#: «haitus» — повторяем как есть, иначе не совпадёт.
STATUS = {
    "ongoing": "пишется",
    "completed": "закончена",
    "haitus": "заморожена",
    "hiatus": "заморожена",
    "dropped": "брошена",
}

#: Язык оригинала — сайт помечает им книгу в списке.
LANGUAGE = {"CN": "китайский", "EN": "английский", "JP": "японский",
            "KR": "корейский", "VN": "вьетнамский"}


def _field(item: dict, name: str, default=None):
    """Поле книги, где бы WordPress его ни положил.

    Свои поля WordPress отдаёт то на верхнем уровне, то в `acf`, то в
    `meta` — зависит от того, как настроен тип записи. Гадать нельзя:
    ошибись — и вместо рейтинга получится список пустых строк.
    """
    for where in (item, item.get("acf"), item.get("meta")):
        if isinstance(where, dict) and where.get(name) not in (None, ""):
            return where[name]
    return default


def _text(value) -> str:
    """Текст из того, что отдал WordPress.

    Заголовок приходит объектом `{"rendered": "..."}`, остальное —
    строкой или числом. Списки сайт кладёт как список названий.
    """
    if isinstance(value, dict):
        value = value.get("rendered", "")
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v)
    return str(value or "").strip()


def _number(value, default=0):
    """Число из поля, которое может прийти строкой или прийти пустым."""
    if value in (None, "", []):
        return default
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return default


def _score(value):
    """Средний балл. Ноль и пустое — это «оценок нет», а не «ноль баллов»."""
    if value in (None, "", []):
        return None
    try:
        found = round(float(str(value).replace(",", "").strip()), 2)
    except (TypeError, ValueError):
        return None
    return found or None


def _total_pages(resp) -> int:
    """Сколько всего страниц каталога, по словам самого WordPress."""
    headers = getattr(resp, "headers", None) or {}
    for name in ("X-WP-TotalPages", "x-wp-totalpages"):
        try:
            found = _number(headers.get(name), 0)
        except AttributeError:
            return 0
        if found:
            return found
    return 0


def catalogue(client, on_progress=None) -> list:
    """Весь каталог книг, страница за страницей.

    Тысяча записей на запрос — столько же просит сама витрина. Меньше
    значило бы полтора десятка запросов вместо трёх.
    """
    found: list = []
    pages = 0
    page = 1
    while page <= MAX_PAGES:
        try:
            resp = client.get(CATALOGUE, params={"per_page": PAGE, "page": page})
        except HttpError as exc:
            # Первая страница не пришла — рейтинга не будет вовсе, и это
            # ошибка. Последующая — отдаём, что собрали: неполный список
            # полезнее пустого.
            if page == 1:
                raise
            log.warning("Каталог MVLEMPYR оборвался на странице %s: %s", page, exc)
            break

        try:
            batch = resp.json()
        except Exception as exc:
            raise SourceBroken(
                f"Каталог MVLEMPYR ответил не JSON: {exc}") from exc
        if not isinstance(batch, list):
            raise SourceBroken(
                "Каталог MVLEMPYR ответил не списком книг — "
                "похоже, эндпойнт сменился")
        if not batch:
            break

        found.extend(batch)
        pages = pages or _total_pages(resp)
        if on_progress:
            on_progress(len(found), pages * PAGE if pages else 0)
        # Страниц меньше, чем запрошено записей — каталог кончился.
        if len(batch) < PAGE or (pages and page >= pages):
            break
        page += 1

    if not found:
        raise SourceBroken("Каталог MVLEMPYR пуст — разбирать нечего")
    return found


def _row(item: dict, place: int) -> RankRow:
    """Одна книга каталога в общем виде строки рейтинга."""
    code = _text(_field(item, "novel-code"))
    slug = _text(_field(item, "slug")) or _text(item.get("slug"))
    name = _text(_field(item, "name")) or _text(item.get("title"))
    status = _text(_field(item, "status")).lower()
    language = _text(_field(item, "language")).upper()

    genre = _field(item, "genre") or []
    if isinstance(genre, (list, tuple)):
        category = _text(genre[0]) if genre else ""
    else:
        category = _text(genre)

    return RankRow(
        place=place,
        # Качалка MVLEMPYR ищет книгу по коду — по нему же строка
        # рейтинга и скачивается. Слаг у сайта тоже есть, но он длиннее
        # и меняется при переименовании книги.
        book_id=code or slug,
        name=name,
        author=_text(_field(item, "author-name")),
        # Числа читающих у сайта нет вовсе. Врать нулём честнее, чем
        # подставлять сюда балл: колонка называется «читающих».
        readers=0,
        category=category,
        chapters=_number(_field(item, "total-chapters")),
        score=_score(_field(item, "average-review")),
        status=STATUS.get(status, status),
        last_chapter=LANGUAGE.get(language, language.lower()),
        cover=COVER.format(size=COVER_SIZE, code=code) if code else "",
        site=SITE_KEY,
        link=f"{SITE}/novel/{slug}" if slug else f"{SITE}/novel/{code}",
    )


def fetch(client, board: str = "weekly", on_progress=None) -> dict:
    """Срез рейтинга по одной из трёх досок.

    Сортируем сами: сайт отдаёт каталог в произвольном порядке, а места
    лежат полями внутри книг. Книги без места в этой доске выкидываем —
    ноль в поле `weekly-rank` значит «в недельный рейтинг не попала», а
    не «первое место».
    """
    if board not in PLACE_FIELD:
        raise ValueError(f"Неизвестная доска рейтинга MVLEMPYR: {board}")
    field = PLACE_FIELD[board]

    items = catalogue(client, on_progress=on_progress)
    ranked = []
    for item in items:
        place = _number(_field(item, field), 0)
        if place > 0:
            ranked.append((place, item))
    if not ranked:
        raise SourceBroken(
            f"Ни у одной книги нет поля «{field}» — "
            "похоже, сайт переименовал места в рейтинге")

    ranked.sort(key=lambda pair: pair[0])
    rows = [_row(item, place) for place, item in ranked[:TOP]]

    return {
        "rows": rows,
        "board": board,
        "category": "",
        # Метки версии у каталога нет: WordPress её не отдаёт. Считаем
        # своей — по числу книг и первой десятке мест. Если рейтинг не
        # пересчитывался, она совпадёт, и повторный срез это покажет.
        "version": _version(rows, len(items)),
        "stats_date": "",
        "decoded": len(rows),
        "total": len(items),
    }


def _version(rows, total: int) -> str:
    """Отпечаток среза: по нему видно, пересчитался ли рейтинг.

    Дата запроса на этот вопрос не отвечает — можно нажать кнопку дважды
    за день и получить один и тот же рейтинг.
    """
    head = "-".join(row.book_id for row in rows[:10])
    return f"{total}:{len(rows)}:{head}" if head else ""


__all__ = ["BOARDS", "CATALOGUE", "PLACE_FIELD", "SITE", "SITE_KEY", "TOP",
           "catalogue", "fetch"]
