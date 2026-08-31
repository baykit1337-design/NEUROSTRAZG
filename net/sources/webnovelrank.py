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

from mvl.client import HttpError

from .base import SourceBroken
from .rank import RankRow
from .webnovel import SITE, page_of

log = logging.getLogger(__name__)

#: Ключ сайта. Он же попадает в имя файла среза.
SITE_KEY = "webnovel"

#: Обложки лежат отдельно и называются по коду книги.
COVER = "https://book-pic.webnovel.com/bookcover/{code}?imageMogr2/thumbnail/300"

#: Сколько строк оставлять. Сайт показывает сотню на страницу.
TOP = 100

#: Разделы, в которых у сайта живёт книга.
#:
#: Здесь была причина, по которой рейтинг комиксов не разбирался вовсе.
#: Ссылок вида `/book/{код}` на той странице нет ни одной: у комиксов свой
#: раздел, и книга лежит по адресу `/comic/{имя}_{код}`. Разбор честно
#: сообщал «ссылок на книги: 0» — и был прав, просто искал не там.
BOOK_SECTIONS = ("book", "comic")

#: Ссылка на книгу: код — число после последнего подчёркивания.
#:
#: Строка обязана кончаться кодом. Ссылка «читать» ведёт на главу —
#: `/comic/{имя}_{код}/{номер главы}`, — и без этого условия номер главы
#: сошёл бы за вторую книгу в той же строке.
BOOK_LINK = re.compile(
    r"^/(?:" + "|".join(BOOK_SECTIONS) + r")/(?:[^/]*?_)?(\d{8,25})/?$")

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
    "fanfic-collection": "Фанфики · добавления в библиотеку",
    "fanfic-popular": "Фанфики · новые читатели",
    "fanfic-update": "Фанфики · дописано за неделю",
    "fanfic-active": "Фанфики · обсуждают",
    "comic-power": "Комиксы · сила за сезон",
}

PATHS = {
    "hot": "hot",
    "novel-power": "novel/season/power_rank",
    "novel-sellers": "novel/season/best_sellers",
    "novel-collection": "novel/season/collection_rank",
    "novel-alltime": "novel/all_time/power_rank",
    "fanfic-power": "fanfic/season/power_rank",
    "fanfic-collection": "fanfic/all_time/collection_rank",
    "fanfic-popular": "fanfic/all_time/popular_rank",
    "fanfic-update": "fanfic/all_time/update_rank",
    "fanfic-active": "fanfic/all_time/engagement_rank",
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
    "fanfic-collection": "в библиотеках",
    "fanfic-popular": "новых читателей",
    #: Не голоса и не читатели: доска считает написанные за срок слова.
    #: Подписать её «голосами» значило бы соврать про число, которое
    #: человек прочтёт как оценку.
    "fanfic-update": "слов дописано",
    "fanfic-active": "комментариев",
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

    # Число доски и имя автора лежат в одинаковых `<strong>`. Различает их
    # не класс — он у сайта служебный и меняется, — а устройство: у числа
    # внутри свои теги, значок и `<span>` с самим числом, а имя автора
    # лежит голым текстом. Без этого автор с именем вроде «50Cent» однажды
    # стал бы числом доски.
    value = 0
    inner = [mark for mark in item.find_all("strong") if mark.find(True)]
    for mark in inner or item.find_all("strong"):
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


#: Заголовки перехода по сайту.
#:
#: Подделку под браузер клиент делает и сам, но переход с главной он не
#: изображает: запрос выглядит как приход ниоткуда. Cloudflare у этого
#: сайта на такие смотрит косо. Панацеей это не является — если под
#: подозрением сам адрес прокси, никакие заголовки не помогут, — но
#: стоит одну строку.
VISIT = {
    "Referer": SITE + "/",
    "Accept-Language": "en-US,en;q=0.9",
}


def _book_code(link) -> str:
    """Код книги из ссылки. Пусто — ссылка не на книгу."""
    found = BOOK_LINK.match(link.get("href", "").split("?")[0])
    return found.group(1) if found else ""


def _book_links(node) -> set:
    """Коды книг, на которые ссылаются изнутри этого куска разметки."""
    return {code for link in node.find_all("a", href=True)
            if (code := _book_code(link))}


def _row_box(link):
    """Кусок разметки вокруг ссылки, описывающий одну книгу.

    Поднимаемся от ссылки вверх, пока предок говорит про одну и ту же
    книгу. Как только в него попадает вторая — это уже не строка, а
    список, и берём предыдущий.
    """
    box = link
    for parent in link.parents:
        if parent.name in (None, "body", "html", "[document]"):
            break
        if len(_book_links(parent)) > 1:
            break
        box = parent
    return box


#: Чем сайт верстает строку рейтинга. Сегодня это `<section>`; `<li>`
#: остаётся, потому что им свёрстано боковое меню досок и потому что
#: список — самая частая вёрстка рейтинга вообще. Строки без ссылки на
#: книгу отсеются сами, так что лишний тег здесь ничего не стоит.
ROW_TAGS = ("section", "li")


def _rows_from_list(soup, metric: str) -> list:
    """Разбор по строкам разметки — тем, чем рейтинг свёрстан сегодня."""
    rows, seen = [], set()
    for item in soup.find_all(ROW_TAGS):
        row = _row(item, len(rows) + 1, metric)
        if row is None or row.book_id in seen:
            continue
        seen.add(row.book_id)
        rows.append(row)
        if len(rows) >= TOP:
            break
    return rows


def _rows_from_links(soup, metric: str) -> list:
    """Запасной разбор: от ссылок на книги вверх, а не от списка вниз.

    Разбор по `<li>` держится на том, что рейтинг свёрстан списком. Стоит
    сайту переверстать его дивами — и `<li>` на странице не окажется
    вовсе, а книги никуда не денутся: ссылка на страницу книги есть в
    любой вёрстке, иначе на книгу нельзя было бы перейти.

    Порядок сохраняется: ссылки идут в том же порядке, что и на странице.
    """
    rows, seen = [], set()
    for link in soup.find_all("a", href=True):
        code = _book_code(link)
        if not code or code in seen:
            continue
        row = _row(_row_box(link), len(rows) + 1, metric)
        if row is None:
            continue
        seen.add(row.book_id)
        rows.append(row)
        if len(rows) >= TOP:
            break
    return rows


#: По чему видно, что список книг уехал в скрипт. Ни одна из меток не
#: доказательство сама по себе — они попадают в сообщение как приметы,
#: а не как приговор.
DATA_MARKS = ("g_data", "__NEXT_DATA__", "__INITIAL_STATE__", "rankList",
              "rankItems", "bookInfo")


def _what_came(page: str, soup) -> str:
    """Чем оказалась страница — фактами, а не догадкой.

    Прежнее сообщение утверждало причину («сайт переделал рейтинг на
    подгрузку скриптом»), которой знать не могло: с тем же успехом это
    могла быть страница входа, заглушка посредника или пустой ответ.
    Уверенная догадка уводит чинить не то — это ровно та ошибка, ради
    которой заведена проверка на стену.
    """
    title = soup.find("title")
    name = title.get_text(" ", strip=True)[:90] if title else ""
    books = len({code for link in soup.find_all("a", href=True)
                 if (code := _book_code(link))})
    marks = [mark for mark in DATA_MARKS if mark in page]

    return "; ".join([
        f"пришло {len(page)} байт",
        f"заголовок окна «{name}»" if name else "заголовка окна нет",
        f"списков <li>: {len(soup.find_all('li'))}",
        f"ссылок на книги: {books}",
        ("в тексте страницы есть " + ", ".join(marks)) if marks
        else "объектов с данными в тексте не видно",
    ])


def fetch(client, board: str = "hot") -> dict:
    """Срез одной доски."""
    address = url_of(board)
    page = page_of(client, address, headers=VISIT)
    soup = BeautifulSoup(page, "lxml")
    metric = METRICS.get(board, "")

    # Сначала так, как рейтинг свёрстан сегодня; не вышло — от ссылок.
    # Порядок именно такой: разбор по списку точнее, потому что знает,
    # где кончается одна книга и начинается другая.
    rows = _rows_from_list(soup, metric) or _rows_from_links(soup, metric)

    if not rows:
        # Сначала стена, потом вёрстка. Перепутав их, сообщение уверенно
        # уводит чинить разбор, которого никто не ломал: до разметки дело
        # не дошло, страница вообще не с сайта.
        #
        # Страница едет вместе с отказом: починить разбор по одному
        # «не нашлось ни одной книги» нельзя, а второго случая может не
        # быть неделю.
        raise SourceBroken(
            f"Рейтинг Webnovel не разобрался: на странице {address} не "
            f"нашлось ни одной книги. Что пришло: {_what_came(page, soup)}.",
            page=page)

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


# ------------------------------------------- подробности одной книги


#: Где на странице книги лежит описание. Имя поля у сайта одно, но
#: какое именно — снаружи не проверить: страница из песочницы не
#: открывается. Поэтому пробуем несколько подряд и берём первое
#: непустое: лишний ключ в списке ничего не стоит, а угаданный неверно
#: оставил бы карточку пустой навсегда.
ABOUT_FIELDS = ("description", "synopsis", "bookIntro", "intro")

#: Метки книги — жанр и вид. Лежат порознь, а в карточке им место рядом.
TAG_FIELDS = ("categoryName", "subCategoryName", "typeName")


def _book_page(client, code: str, slug: str, section: str):
    """Страница книги и её адрес.

    Раздел берётся из ссылки, которая стоит в строке рейтинга, а не
    выдумывается: у романов книга живёт в `/book/`, у комиксов — в
    `/comic/`, и собранный по старому правилу адрес отвечал «HTTP 404».
    Обложка при этом грузилась — она лежит отдельно и по коду, — отчего
    выходило особенно странно: картинка есть, книги нет.

    Раздела может и не быть: карточку спрашивают не только из раскрытой
    строки. Тогда — и только тогда — обходим известные разделы по
    очереди. Это не догадка: их всего два, и первый же ответивший и есть
    верный.
    """
    order = [section] if section in BOOK_SECTIONS else list(BOOK_SECTIONS)
    tried, last = [], None
    for part in order:
        where = f"{SITE}/{part}/{slug or code}"
        tried.append(where)
        try:
            return page_of(client, where), where
        except HttpError as exc:
            last = exc
    raise SourceBroken(
        f"Страница книги {code} на Webnovel не открылась: {last}. "
        f"Пробовали: {', '.join(tried)}")


def book(client, code: str, slug: str = "", section: str = "") -> dict:
    """Подробности книги — для раскрытой строки рейтинга.

    Страницу книги уже разбирает сам источник (`net/sources/webnovel`):
    он достаёт оттуда `bookInfo` ради названия, автора и числа глав.
    Здесь берётся тот же разбор — заводить второй значило бы однажды
    чинить сайт в двух местах.

    Зачем это вообще: раскрытая строка Webnovel показывала ровно то, что
    и так стоит в строке. Раскрывают, чтобы узнать больше.
    """
    from .webnovel import BOOK_MARK, WebnovelSource, _object_after, _text_of

    code = str(code or "").strip()
    if not code:
        raise SourceBroken("Не сказано, какую книгу открывать")

    page, where = _book_page(client, code, slug, section)

    info = (_object_after(page, BOOK_MARK) or {}).get("bookInfo") or {}
    if not info:
        raise SourceBroken(
            "На странице книги нет её описания — сайт сменил разметку")

    abstract = ""
    for name in ABOUT_FIELDS:
        abstract = _text_of(str(info.get(name) or "")).strip()
        if abstract:
            break

    tags = [str(info.get(name) or "").strip() for name in TAG_FIELDS]

    return {
        "name": str(info.get("bookName") or "").strip(),
        # Ключ называется как у остальных сайтов нарочно: карточку рисует
        # один и тот же код, и переключатель «原/RU» с кнопкой перевода
        # достаётся Webnovel даром.
        "abstract": abstract,
        "tags": [tag for tag in tags if tag],
        "author": str(info.get("authorName") or "").strip(),
        "chapters": int(info.get("totalChapterNum")
                        or info.get("chapterNum") or 0),
        "status": WebnovelSource._status(info),
        "language": str(info.get("languageName") or "").strip().lower(),
        "cover": WebnovelSource._cover(code, info),
        # Та ссылка, по которой страница и открылась: собранная заново
        # снова увела бы комикс в раздел романов.
        "link": where,
    }


__all__ = ["BOARDS", "BOOK_SECTIONS", "METRICS", "PATHS", "SITE_KEY", "TOP",
           "book", "fetch",
           "url_of"]
