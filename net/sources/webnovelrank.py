"""Рейтинг Webnovel.

В отличие от двух других сайтов, этот отдаёт рейтинг готовой страницей:
ни токена, ни входа, ни скрипта — обычная вёрстка, которую видит и
поисковик. Поэтому здесь разбирается именно она.

Досок у сайта много: три вида книг (романы, фанфики, комиксы) на четыре
срока и на семь показателей — под сотню сочетаний. Выводить их все
списком бессмысленно: человек выбирает из десятка, а не из сотни.
Поэтому здесь отобраны те, ради которых на рейтинг и заходят, а адрес
складывается по общему правилу — добавить доску значит дописать строку.

Число рядом с книгой на каждой доске своё: где-то это голоса, где-то
покупки, где-то добавления в библиотеку. Оно уезжает в строку вместе с
подписью — подписать всё «баллом» значило бы соврать про число, которое
человек будет читать как оценку.

Живой проверки в песочнице не было: `www.webnovel.com` из неё недоступен
— шлюз отвечает 403 на любой хост вне разрешённого списка. Разбор написан
по исходнику страницы `/ranking/hot` и покрыт тестами на разметке той же
формы; первый живой запуск — на машине человека.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from .base import SourceBroken
from .rank import RankRow
from .webnovel import SITE

log = logging.getLogger(__name__)

#: Ключ сайта. Он же попадает в имя файла среза.
SITE_KEY = "webnovel"

#: Обложки лежат отдельно и называются по коду книги.
COVER = "https://book-pic.webnovel.com/bookcover/{code}?imageMogr2/thumbnail/300"

#: Сколько строк оставлять. Сайт показывает сотню на страницу.
TOP = 100

#: Ссылка на книгу: код — число после последнего подчёркивания.
BOOK_LINK = re.compile(r"^/book/(?:[^/]*?_)?(\d{8,25})/?$")

#: Доски: ключ → (адрес после /ranking/, подпись числа).
#:
#: Пустой адрес у первой — это `/ranking/hot`, отдельная страница «что
#: читают прямо сейчас». Остальные складываются по общему правилу
#: `{вид}/{срок}/{показатель}`.
BOARDS = {
    "hot": "Читают сейчас",
    "novel-power": "Романы · сила за сезон",
    "novel-sellers": "Романы · покупки за сезон",
    "novel-collection": "Романы · добавления в библиотеку",
    "novel-alltime": "Романы · сила за всё время",
    "fanfic-power": "Фанфики · сила за сезон",
    "comic-power": "Комиксы · сила за сезон",
}

PATHS = {
    "hot": "hot",
    "novel-power": "novel/season/power_rank",
    "novel-sellers": "novel/season/best_sellers",
    "novel-collection": "novel/season/collection_rank",
    "novel-alltime": "novel/all_time/power_rank",
    "fanfic-power": "fanfic/season/power_rank",
    "comic-power": "comic/season/comic_power_rank",
}

#: Как называется число на этой доске.
METRICS = {
    "hot": "вес в рейтинге",
    "novel-power": "голосов",
    "novel-sellers": "покупок",
    "novel-collection": "в библиотеках",
    "novel-alltime": "голосов",
    "fanfic-power": "голосов",
    "comic-power": "голосов",
}


def url_of(board: str) -> str:
    if board not in PATHS:
        raise ValueError(f"Неизвестная доска рейтинга Webnovel: {board}")
    return f"{SITE}/ranking/{PATHS[board]}"


def _number(text) -> int:
    """Число из подписи вида «132.4K» или «12,300»."""
    said = str(text or "").strip().replace(",", "").replace("\xa0", "")
    found = re.match(r"([\d.]+)\s*([KkMm]?)", said)
    if not found:
        return 0
    try:
        value = float(found.group(1))
    except ValueError:
        return 0
    return int(value * {"k": 1_000, "K": 1_000,
                        "m": 1_000_000, "M": 1_000_000}.get(found.group(2), 1))


def _book_link(item):
    """Ссылка на книгу внутри строки и код книги из неё."""
    for link in item.find_all("a", href=True):
        found = BOOK_LINK.match(link["href"].split("?")[0])
        if found:
            return link, found.group(1)
    return None, ""


def _row(item, place: int, metric: str) -> RankRow | None:
    """Строка рейтинга из одного элемента списка.

    Классы не проверяются нарочно. У сайта они служебные и меняются с
    каждой правкой вида (`df pt8 pb8 pr _thumb_hover`), а держится
    другое: у строки рейтинга есть заголовок и ссылка на книгу. По ним и
    опознаём — так разбор переживёт смену оформления.
    """
    link, code = _book_link(item)
    if not code:
        return None

    title = item.find(["h3", "h2", "h4"])
    name = title.get_text(" ", strip=True) if title else \
        link.get_text(" ", strip=True)
    if not name:
        return None

    # Место сайт печатает своим шрифтом для цифр. Если разметка его не
    # отдала, считаем по порядку — список и так идёт сверху вниз.
    shown = 0
    for mark in item.find_all(["i", "span"]):
        digits = mark.get_text(strip=True)
        if digits.isdigit() and len(digits) <= 3:
            shown = int(digits)
            break

    # Число доски: сайт печатает его тем же шрифтом для цифр, внутри
    # выделения. Берём самое крупное — мелкие рядом это подписи.
    value = 0
    for mark in item.find_all("strong"):
        value = max(value, _number(mark.get_text(" ", strip=True)))

    # Раздел — ссылка на подборку.
    category = ""
    for other in item.find_all("a", href=True):
        if other["href"].startswith("/stories/"):
            category = other.get_text(" ", strip=True)
            break

    return RankRow(
        place=shown or place,
        book_id=code,
        name=name,
        category=category,
        readers=0,
        score=value or None,
        metric=metric if value else "",
        cover=COVER.format(code=code),
        site=SITE_KEY,
        link=f"{SITE}{link['href'].split('?')[0]}",
    )


def fetch(client, board: str = "hot") -> dict:
    """Срез одной доски."""
    address = url_of(board)
    page = client.get_text(address)
    soup = BeautifulSoup(page, "lxml")
    metric = METRICS.get(board, "")

    rows = []
    seen = set()
    for item in soup.find_all("li"):
        row = _row(item, len(rows) + 1, metric)
        if row is None or row.book_id in seen:
            continue
        seen.add(row.book_id)
        rows.append(row)
        if len(rows) >= TOP:
            break

    if not rows:
        raise SourceBroken(
            f"Рейтинг Webnovel не разобрался: на странице {address} не нашлось "
            "ни одной книги. Раньше он приходил обычной вёрсткой; если сайт "
            "переделал его на подгрузку скриптом, чинить надо разбор, а не "
            "повторять запрос.")

    # Места печатаются с ведущим нулём и иногда только у первой десятки.
    # Приводим к порядку: у соседних строк не должно быть одного места.
    if len({row.place for row in rows}) != len(rows):
        for number, row in enumerate(rows, 1):
            row.place = number

    return {
        "rows": rows,
        "board": board,
        "category": "",
        "version": _version(rows),
        "stats_date": "",
        "decoded": len(rows),
        "total": len(rows),
    }


def _version(rows) -> str:
    """Отпечаток среза: пересчитался ли рейтинг с прошлого раза.

    Дата запроса на этот вопрос не отвечает — кнопку можно нажать дважды
    за день и получить тот же самый список.
    """
    head = "-".join(row.book_id for row in rows[:10])
    return f"{len(rows)}:{head}" if head else ""


__all__ = ["BOARDS", "METRICS", "PATHS", "SITE_KEY", "TOP", "fetch", "url_of"]
