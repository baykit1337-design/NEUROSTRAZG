"""Рейтинг Цидяня (起点中文网).

Цидянь — старейшая платная площадка китайского интернета: подписку она
ввела в 2003 году, остальные подхватили. Скачивать оттуда программа не
умеет и не собирается: у книги открыты первые главы, дальше VIP. Здесь
только рейтинг — чтобы увидеть, что читают, найти книгу по названию на
сайте-сливе и качать уже оттуда.

Досок у сайта много, и живут они в двух измерениях сразу: **доска** (по
чему считают — месячные билеты, продажи, добавления в библиотеку) и
**раздел** (жанр:玄幻, 都市, 仙侠 и так далее). Пятнадцать разделов на
семь досок — это сотня страниц, и списком их выводить бессмысленно.
Поэтому здесь два выпадающих списка, а адрес складывается по общему
правилу `/rank/{доска}/chn{раздел}/`.

Откуда взяты правила. Из исходников трёх страниц, снятых с живого сайта:
главной, раздела `/xuanhuan/` и страницы книги. Числа разделов — из
скрипта самого сайта, который переводит адрес вида `/xuanhuan/` в
мобильный `m.qidian.com/category/catid21/`; гадать не пришлось.

Чего в исходниках **не было**: страницы `/rank/…` самой по себе. Блоки
рейтинга на главной и в разделе устроены одинаково, разбор написан по
ним, и на отдельной странице рейтинга он, скорее всего, тоже сработает —
но это «скорее всего», а не проверено. Не сработает — источник скажет об
этом прямо, а не покажет пустой список.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from mvl.client import HttpError

from .base import SourceBroken
from .rank import RankRow

log = logging.getLogger(__name__)

#: Ключ сайта. Он же попадает в имя файла среза.
SITE_KEY = "qidian"

SITE = "https://www.qidian.com"

#: Обложки лежат на отдельном хосте и называются по коду книги. Число
#: 349573 — постоянная сайта, оно одно во всех адресах на всех трёх
#: снятых страницах.
COVER = "https://bookcover.yuewen.com/qdbimg/349573/{code}/600.webp"

#: Ссылка на книгу внутри блока рейтинга.
BOOK_LINK = re.compile(r"/book/(\d{4,20})/?$")

#: Сколько строк оставлять в срезе.
TOP = 100

#: Доски: ключ → (кусок адреса, подпись доски, подпись числа).
#:
#: «Месячные билеты» у Цидяня — не голоса и не оценки: билет покупается
#: подпиской и отдаётся книге, поэтому это ближе к деньгам, чем к мнению.
#: Подписываем число честно, а не общим словом «баллы».
BOARDS = {
    "yuepiao": "Месячные билеты",
    "hotsales": "Продажи",
    "newfans": "Прирост читателей",
    "readindex": "Индекс чтения",
    "collect": "В библиотеках",
    "signnewbook": "Новинки авторов по договору",
    "newsign": "Новинки новичков",
}

PATHS = {
    "yuepiao": "yuepiao",
    "hotsales": "hotsales",
    "newfans": "newfans",
    "readindex": "readindex",
    "collect": "collect",
    "signnewbook": "signnewbook",
    "newsign": "newsign",
}

#: Как называется число на этой доске. Пусто — числа у доски нет вовсе:
#: на некоторых сайт печатает только порядок.
METRICS = {
    "yuepiao": "билетов за месяц",
    "hotsales": "",
    "newfans": "",
    "readindex": "",
    "collect": "в библиотеках",
    "signnewbook": "",
    "newsign": "",
}

#: Разделы сайта: ключ → (номер раздела, название).
#:
#: Номера взяты не на глаз: скрипт самого сайта переводит `/xuanhuan/` в
#: `m.qidian.com/category/catid21/`, `/dushi/` в `catid4` и так далее.
#: Пустой ключ — «все разделы», адрес тогда без хвоста.
CHANNELS = {
    "": ("", "Все разделы"),
    "xuanhuan": ("21", "Сянься·сюаньхуань"),
    "qihuan": ("1", "Фэнтези"),
    "wuxia": ("2", "Уся"),
    "xianxia": ("22", "Сяньдо"),
    "dushi": ("4", "Городское"),
    "xianshi": ("15", "Реализм"),
    "junshi": ("6", "Военное"),
    "lishi": ("5", "Историческое"),
    "youxi": ("7", "Игровое"),
    "tiyu": ("8", "Спорт"),
    "kehuan": ("9", "Фантастика"),
    "zhutianwuxian": ("20109", "Мультивселенные"),
    "lingyi": ("10", "Мистика"),
    "2cy": ("12", "Ранобэ"),
    "duanpian": ("20076", "Короткая проза"),
}


def url_of(board: str, channel: str = "") -> str:
    """Адрес доски. Раздел добавляется хвостом, как у самого сайта."""
    if board not in PATHS:
        raise ValueError(f"Неизвестная доска рейтинга Цидяня: {board}")
    if channel and channel not in CHANNELS:
        raise ValueError(f"Неизвестный раздел Цидяня: {channel}")
    tail = CHANNELS.get(channel, ("", ""))[0]
    address = f"{SITE}/rank/{PATHS[board]}/"
    return f"{address}chn{tail}/" if tail else address


def _number(text) -> int:
    """Число из подписи.

    Сайт пишет их и цифрами (`16536`), и по-китайски (`13.33万` —
    тринадцать с третью десятков тысяч). Второе встречается на странице
    книги, первое в рейтинге; разбираем оба, иначе половина чисел
    превратится в ноль.
    """
    said = str(text or "").strip().replace(",", "").replace("\xa0", "")
    found = re.match(r"([\d.]+)\s*([万亿]?)", said)
    if not found:
        return 0
    try:
        value = float(found.group(1))
    except ValueError:
        return 0
    return int(value * {"万": 10_000, "亿": 100_000_000}.get(found.group(2), 1))


#: Что сайт дописывает к названию в подсказках и заголовках: «читать
#: онлайн», «последние главы», «роман». Хвосты идут подряд, поэтому
#: снимаются по кругу, а не один раз.
TAILS = re.compile(r"(在线阅读|最新章节|全本|小说)$")


def _clean(value) -> str:
    """Название без приписок сайта."""
    said = str(value or "").strip()
    while True:
        cut = TAILS.sub("", said).strip()
        if cut == said:
            return said
        said = cut


def _code_of(link) -> str:
    """Код книги из ссылки. У сайта он же лежит в `data-bid`."""
    said = str(link.get("data-bid") or "").strip()
    if said.isdigit():
        return said
    found = BOOK_LINK.search((link.get("href") or "").split("?")[0])
    return found.group(1) if found else ""


def _row(item, place: int, metric: str) -> RankRow | None:
    """Строка рейтинга из одного элемента списка.

    Первая книга доски свёрстана иначе остальных: у неё обложка, автор,
    жанр и число крупно (`li.unfold`). Со второй идут короткие строки:
    место, название, число. Разбираем оба вида одним проходом — по тому,
    что есть, а не по классам обёртки.
    """
    link = None
    for candidate in item.find_all("a", href=True):
        if _code_of(candidate):
            link = candidate
            break
    if link is None:
        return None

    code = _code_of(link)
    # Видимый текст ссылки, а не `title`: в `title` сайт дописывает свой
    # хвост — «夜无疆最新章节在线阅读» вместо «夜无疆». `title` остаётся
    # запасным на случай, если внутри ссылки одна картинка.
    name = _clean(link.get_text(" ", strip=True)) or _clean(link.get("title"))
    if not name:
        return None

    # Место сайт печатает по-разному: у первой книги «NO.1», у прочих —
    # цифрой в своём блоке. Порядковый номер строки лежит в `data-rid` и
    # верен в обоих случаях.
    shown = 0
    said = str(item.get("data-rid") or "").strip()
    if said.isdigit():
        shown = int(said)

    # Число доски. У первой книги оно в `p.digital em`, у остальных — в
    # `i.total`. На досках без числа нет ни того, ни другого.
    value = 0
    for where in (item.find("i", class_="total"),
                  item.select_one("p.digital em")):
        if where is not None:
            value = max(value, _number(where.get_text(" ", strip=True)))

    # Автор и жанр есть только у первой книги доски — у остальных строк
    # для них нет места. Пусто честнее, чем подставленное наугад.
    author = ""
    writer = item.find("a", class_="writer")
    if writer is not None:
        author = writer.get_text(" ", strip=True)

    category = ""
    kind = item.find("a", class_="type")
    if kind is not None:
        category = kind.get_text(" ", strip=True)

    return RankRow(
        place=shown or place,
        book_id=code,
        name=name,
        author=author,
        category=category,
        readers=0,
        score=value or None,
        metric=metric if value else "",
        cover=COVER.format(code=code),
        site=SITE_KEY,
        link=f"{SITE}/book/{code}/",
    )


def _blocks(soup):
    """Блоки рейтинга на странице.

    Скоплены нарочно: на главной книжных ссылок под сотню, и половина из
    них — реклама, «редакция советует» и «недавно обновлённые». Взять их
    все значило бы выдать за рейтинг то, что рейтингом не является.
    """
    return soup.select("div.rank-list") or soup.select("div.book-list")


def fetch(client, board: str = "yuepiao", channel: str = "") -> dict:
    """Срез одной доски одного раздела."""
    address = url_of(board, channel)
    try:
        page = client.get_text(address)
    except HttpError as exc:
        raise SourceBroken(
            f"Цидянь не ответил на {address}: {exc}") from exc

    soup = BeautifulSoup(page, "lxml")
    metric = METRICS.get(board, "")

    rows: list[RankRow] = []
    seen: set[str] = set()
    for block in _blocks(soup):
        for item in block.find_all("li"):
            row = _row(item, len(rows) + 1, metric)
            if row is None or row.book_id in seen:
                continue
            seen.add(row.book_id)
            rows.append(row)
            if len(rows) >= TOP:
                break
        if len(rows) >= TOP:
            break

    if not rows:
        raise SourceBroken(
            f"Рейтинг Цидяня не разобрался: на странице {address} не нашлось "
            "ни одной книги. Разбор написан по блокам `div.rank-list` с "
            "главной страницы и со страницы раздела; если на самой странице "
            "рейтинга вёрстка другая, чинить надо разбор, а не повторять "
            "запрос.")

    # Места на странице печатаются вперемешку: у первой книги «NO.1»,
    # дальше цифрами, и в разных блоках нумерация начинается заново.
    if len({row.place for row in rows}) != len(rows):
        for number, row in enumerate(rows, 1):
            row.place = number

    return {
        "rows": rows,
        "board": board,
        "category": channel,
        "version": _version(rows),
        "stats_date": "",
        "decoded": len(rows),
        "total": len(rows),
    }


def _version(rows) -> str:
    """Отпечаток среза: пересчитался ли рейтинг с прошлого раза."""
    head = "-".join(row.book_id for row in rows[:10])
    return f"{len(rows)}:{head}" if head else ""


# --------------------------------------------------------- страница книги

def _ld_book(soup) -> dict:
    """Данные книги из блока `application/ld+json`.

    Сайт кладёт туда то же, что показывает: название, автора, жанр,
    описание, даты. Это разметка для поисковиков — её меняют куда реже
    вёрстки, и разбирать её надёжнее, чем считать `div`-ы.
    """
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "{}")
        except (ValueError, TypeError):
            continue
        for node in data.get("@graph", [data]):
            if isinstance(node, dict) and node.get("@type") == "Book":
                return node
    return {}


def _meta(soup, name: str) -> str:
    tag = soup.find("meta", property=name)
    return str(tag.get("content") or "").strip() if tag else ""


def book(client, code: str, slug: str = "") -> dict:
    """Подробности книги для раскрытой строки рейтинга."""
    code = str(code or "").strip()
    address = f"{SITE}/book/{code}/"
    try:
        page = client.get_text(address)
    except HttpError as exc:
        raise SourceBroken(
            f"Страница книги {code} на Цидяне не открылась: {exc}") from exc

    soup = BeautifulSoup(page, "lxml")
    data = _ld_book(soup)

    about = str(data.get("description") or "") or _meta(soup, "og:description")
    if not about:
        block = soup.select_one("#book-intro-detail")
        if block is not None:
            for br in block.find_all("br"):
                br.replace_with("\n")
            about = block.get_text("\n", strip=True)

    author = ""
    if isinstance(data.get("author"), dict):
        author = str(data["author"].get("name") or "")
    author = author or _meta(soup, "og:novel:author")

    # Число глав сайт пишет словами: «连载共51章» — «выходит, всего 51
    # глава». Берём число, а не строку целиком.
    chapters = 0
    desc = soup.select_one(".catalog-header-desc")
    if desc is not None:
        found = re.search(r"(\d+)\s*章", desc.get_text(" ", strip=True))
        if found:
            chapters = int(found.group(1))

    # Объём в знаках стоит первым в строке чисел под названием.
    words = 0
    count = soup.select_one("p.count em")
    if count is not None:
        words = _number(count.get_text(" ", strip=True))

    tags = [str(data.get("genre") or "") or _meta(soup, "og:novel:category")]
    for extra in soup.select("p.book-attribute a"):
        said = extra.get_text(" ", strip=True)
        if said and said not in tags:
            tags.append(said)

    return {
        "name": str(data.get("name") or "") or _meta(soup, "og:novel:book_name"),
        "abstract": about,
        "tags": [tag for tag in tags if tag],
        "author": author,
        "chapters": chapters,
        "words": words,
        "status": _meta(soup, "og:novel:status"),
        "updated": (str(data.get("dateModified") or "")
                    or _meta(soup, "og:novel:update_time")),
        "last_chapter": _meta(soup, "og:novel:latest_chapter_name"),
        "cover": COVER.format(code=code),
        "link": address,
    }


__all__ = ["BOARDS", "CHANNELS", "METRICS", "PATHS", "SITE", "SITE_KEY",
           "TOP", "book", "fetch", "url_of"]
