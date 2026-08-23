"""Рейтинг Цидяня (起点中文网).

Цидянь — старейшая платная площадка китайского интернета: подписку она
ввела в 2003 году, остальные подхватили. Скачивать оттуда программа не
умеет и не собирается: у книги открыты первые главы, дальше VIP. Здесь
только рейтинг — чтобы увидеть, что читают, найти книгу по названию на
сайте-сливе и качать уже оттуда.

Досок у сайта пятнадцать, и живут они в двух измерениях сразу: **доска**
(по чему считают — месячные билеты, продажи, добавления в библиотеку) и
**раздел** (жанр: 玄幻, 都市, 仙侠 и так далее). Пятнадцать разделов на
пятнадцать досок — это две сотни страниц, списком их выводить незачем.
Поэтому здесь два выпадающих списка, а адрес складывается по правилу
самого сайта: `/rank/{доска}/chn{раздел}/`.

Строка рейтинга у Цидяня непривычно щедрая: кроме места и названия на
странице сразу лежат автор, жанр и поджанр, статус, описание, последняя
глава и время её выхода. Поэтому раскрытая карточка книги не требует
второго запроса — всё уже пришло с рейтингом.

Число, по которому доска считает, на странице **не написано**. Вместо
цифр стоят знаки из неназначенной области Unicode, а рисует их свой
шрифт, который сайт меняет от страницы к странице. Его расшифровка — в
`qidianfont`. Не вышло расшифровать — число не показывается вовсе:
неверное число в рейтинге выглядит достоверно и потому хуже пустоты.

Просто так сайт страницу не отдаёт. Защита Tencent встречает всякого без
куки `w_tsfp` заглушкой на две сотни байт с кодом 202 «принято»: в
браузере она запускает скрипт, тот считает пропуск и перезагружает
страницу. Пропуск мы считаем сами — как именно, написано в `qidianpass`.
Заглушка приходит **всем** без пропуска, поэтому ни смена прокси, ни
заголовки от неё не спасали.

Откуда взяты правила. Из исходников живых страниц: рейтинга
`/rank/yuepiao/`, главной, разделов `/xianxia/`, `/2cy/`, `/xianshi/`,
`/kehuan/` и страницы книги. Числа разделов — из скрипта самого сайта,
который переводит `/xuanhuan/` в мобильный `m.qidian.com/category/
catid21/`; гадать не пришлось.

Чего живьём никто не видел: файла шрифта с цифрами и страницы доски в
разрезе раздела. Про раздел известно, что сам сайт ссылается на
`/rank/yuepiao/chn22/` со страницы 仙侠, — этой формой и пользуемся.
"""

from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from mvl.client import HttpError

from . import qidianfont, qidianpass
from .base import SourceBroken
from .rank import RankRow

log = logging.getLogger(__name__)

#: Ключ сайта. Он же попадает в имя файла среза.
SITE_KEY = "qidian"

SITE = "https://www.qidian.com"

#: Мобильный вид того же сайта. Стоит за той же защитой, но встречает
#: гостей иначе, и когда полный сайт отвечает проверкой, этот бывает
#: сговорчивее.
MOBILE = "https://m.qidian.com"

#: Какие доски у мобильного вида вообще есть.
#:
#: Не догадка: скрипт `getMUrl()` на каждой странице Цидяня переводит
#: адрес полного сайта в мобильный, и для рейтинга он знает ровно этот
#: список — `/rank/(yuepiao|readindex|hotsales|newfans|recom|newauthor)`.
#: Остальные доски он в мобильный вид не переводит, значит, их там нет,
#: и стучаться туда незачем.
MOBILE_BOARDS = ("yuepiao", "readindex", "hotsales", "newfans", "recom",
                 "newauthor")

#: Обложки лежат на отдельном хосте и называются по коду книги. Число
#: 349573 — постоянная сайта, оно одно во всех адресах на всех снятых
#: страницах.
COVER = "https://bookcover.yuewen.com/qdbimg/349573/{code}/600.webp"

#: Ссылка на книгу внутри блока рейтинга.
BOOK_LINK = re.compile(r"/book/(\d{4,20})/?$")

#: Сколько строк оставлять в срезе и сколько страниц ради этого листать.
#: Страница отдаёт двадцать книг, всего их пятьсот. Сотня — то, что ещё
#: имеет смысл просматривать; пять запросов ради неё — терпимо.
TOP = 100
PAGES = 5

#: Доски сайта: ключ адреса → подпись. Порядок — как в левом столбце
#: самого рейтинга: сначала популярное, потом новинки.
BOARDS = {
    "yuepiao": "Месячные билеты",
    "hotsales": "Продажи",
    "retention": "Удержание читателей",
    "readindex": "Индекс чтения",
    "newfans": "Книжные друзья",
    "recom": "Рекомендации",
    "followReading": "Дочитывают",
    "collect": "В библиотеках",
    "vipup": "Обновления",
    "vipcollect": "В библиотеках у VIP",
    "signnewbook": "Новинки авторов по договору",
    "pubnewbook": "Новинки свободных авторов",
    "newsign": "Новинки новичков по договору",
    "newauthor": "Новинки авторов-новичков",
}

#: Раньше здесь была отдельная таблица «ключ → кусок адреса». Она
#: повторяла ключи слово в слово и оставалась только поводом разойтись,
#: поэтому адрес берётся прямо из ключа.
PATHS = {key: key for key in BOARDS}

#: Как подписать число. Подпись сайт печатает рядом с числом сам —
#: 月票, 收藏, 人气, — и берём мы её оттуда, а не отсюда: так подпись
#: остаётся верной и на доске, которой в этом списке нет. Здесь только
#: перевод того, что сайт написал.
UNITS = {
    "月票": "билетов за месяц",
    "收藏": "в библиотеках",
    "推荐": "рекомендаций",
    "人气": "популярность",
    "字": "знаков",
    "在追": "дочитывают",
}

#: Чем доска считает, если на странице подписи не оказалось.
METRICS = {
    "yuepiao": "билетов за месяц",
    "collect": "в библиотеках",
    "vipcollect": "в библиотеках",
    "recom": "рекомендаций",
}

#: Разделы сайта: ключ → (номер раздела, название).
#:
#: Номера взяты не на глаз: скрипт самого сайта переводит `/xuanhuan/` в
#: `m.qidian.com/category/catid21/`, `/dushi/` в `catid4` и так далее.
#: Пустой ключ — «все разделы», адрес тогда без хвоста.
CHANNELS = {
    "": ("", "Все разделы"),
    "xuanhuan": ("21", "Сюаньхуань"),
    "qihuan": ("1", "Фэнтези"),
    "wuxia": ("2", "Уся"),
    "xianxia": ("22", "Сянься"),
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


#: С чем приходить на страницу.
#:
#: Цидянь сидит за защитой Tencent: в шапке любой его страницы висит
#: `probev3.js` и капча `turing.captcha.qcloud.com`. Запрос без единого
#: заголовка такая защита считает роботом и отдаёт вместо рейтинга
#: проверку. Referer и китайский язык — то, с чем на страницу рейтинга
#: приходит живой читатель. Панацеей это не является: если под
#: подозрением сам адрес прокси, заголовки не помогут. И главного они не
#: решают: без пропуска (`qidianpass`) заглушку получает любой запрос,
#: хоть с заголовками, хоть без.
VISIT = {
    "Referer": f"{SITE}/rank/",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

#: Слова, которые говорит **сама** проверка на робота.
#:
#: Скрипт капчи (`turing.captcha.qcloud.com`) и зонд защиты
#: (`probev3.js`) в признаки не годятся: они висят в шапке любой
#: страницы Цидяня, включая совершенно рабочую. Отличает проверку не
#: наличие капчи, а то, что кроме неё на странице ничего нет.
GUARD = ("请输入验证码", "安全验证", "访问验证", "滑动验证",
         "拖动滑块", "身份验证")

#: По чему видно, что сайт сам говорит «такой страницы нет».
MISSING = ("页面不存在", "页面找不到", "该页面不存在", "/error/404")

#: Обвязка настоящей страницы рейтинга: левый столбец досок и рамка
#: вокруг него. Если это есть, а книг нет — сайт цел и ответил нам
#: рейтингом, просто разбирать его стало нечем.
SHELL = ("rank-nav-list", "rank-box", "rank-body")


def _guarded(page) -> bool:
    """Похоже ли, что вместо страницы пришла проверка на робота.

    Признак не в капче: её скрипт висит и на рабочей странице. Признак в
    том, что кроме проверки на странице нет ничего — ни книг, ни рамки
    рейтинга вокруг них, и весит она пару сотен байт вместо сотен тысяч.
    """
    said = str(page or "")
    if any(mark in said for mark in MISSING):
        return False
    if any(mark in said for mark in SHELL):
        return False
    return any(mark in said for mark in GUARD) or len(said) < 20_000


def _diagnose(page: str, address: str) -> str:
    """Почему на странице не нашлось книг — по самой странице.

    «Не разобралось» без подробностей не отличает проверку на робота от
    съехавшей вёрстки и от несуществующей доски, а чинить по такому
    сообщению нечего. Порядок такой: сначала то, что страница говорит о
    себе сама, потом — есть ли на ней обвязка рейтинга, и только под
    конец размер с заголовком.
    """
    said = str(page or "")

    head = ""
    found = re.search(r"<title[^>]*>(.*?)</title>", said, re.S | re.I)
    if found:
        head = re.sub(r"\s+", " ", found.group(1)).strip()[:80]
    tail = f", заголовок «{head}»" if head else ""

    if any(mark in said for mark in MISSING):
        return (f"Цидянь говорит, что такой страницы нет ({address}). "
                "Похоже, у этой доски нет отдельного списка для выбранного "
                "раздела: попробуйте «Все разделы» или другую доску.")

    if any(mark in said for mark in SHELL):
        return (f"Рейтинг Цидяня не разобрался: страница {address} пришла "
                f"целой — рамка рейтинга на месте, — но книг в ней нет. "
                f"Значит, сайт переделал вёрстку списка, и чинить надо "
                f"разбор. Страница {len(said)} байт{tail}.")

    if _guarded(said):
        return (f"Цидянь ответил не рейтингом, а проверкой на робота "
                f"({address}): на странице нет ни списка книг, ни даже рамки "
                f"вокруг него. Пропуск (куку `w_tsfp`) мы посчитали и "
                f"отправили обеими известными формами подписи — защита не "
                f"приняла ни одну. Значит, либо она сменила правило, либо "
                f"под подозрением сам адрес выхода: стоит попробовать другой "
                f"прокси, лучше китайский или хотя бы азиатский. "
                f"Страница {len(said)} байт{tail}.")

    return (f"Рейтинг Цидяня не разобрался: на странице {address} не нашлось "
            f"ни одной книги, и ни на проверку, ни на рейтинг она не похожа. "
            f"Страница {len(said)} байт{tail}.")


def url_of(board: str, channel: str = "") -> str:
    """Адрес доски. Раздел добавляется хвостом, как у самого сайта."""
    if board not in PATHS:
        raise ValueError(f"Неизвестная доска рейтинга Цидяня: {board}")
    if channel and channel not in CHANNELS:
        raise ValueError(f"Неизвестный раздел Цидяня: {channel}")
    tail = CHANNELS.get(channel, ("", ""))[0]
    address = f"{SITE}/rank/{PATHS[board]}/"
    return f"{address}chn{tail}/" if tail else address


def _full(link: str) -> str:
    """Полный адрес из того, что написано в `href`.

    Сайт пишет ссылки без протокола — `//www.qidian.com/…`. Отдать такую
    наружу нельзя: в браузере она подставит протокол страницы, а у нас
    страница своя.
    """
    said = str(link or "").strip()
    if said.startswith("//"):
        return "https:" + said
    if said.startswith("/"):
        return SITE + said
    return said


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


# ------------------------------------------------------------- цифры доски

def _hidden_number(item, table: dict | None):
    """Число доски и его подпись из правой колонки строки.

    Возвращает `(число или None, подпись)`. None — цифры на странице
    спрятаны шрифтом, а расшифровать его не вышло. Ноль тут не годится:
    ноль билетов и «мы не смогли прочитать» — разные вещи, и в рейтинге
    их нельзя показывать одинаково.
    """
    where = item.select_one(".book-right-info .total p, .total p")
    if where is None:
        return 0, ""

    # Подпись — весь текст, кроме самих цифр: «月票», «收藏».
    digits = where.select_one("span[class]")
    said = where.get_text(" ", strip=True)
    shown = digits.get_text("", strip=True) if digits is not None else ""
    # Число бывает написано и без подмены — тогда цифры лежат прямо в
    # тексте, и подпись остаётся, если их вычеркнуть. Считать в этом
    # случае, что подписи нет, значило бы показать «★ 1234» там, где на
    # сайте написано «1234 месячных билета».
    left = said.replace(shown, "") if shown else said
    unit = re.sub(r"[\d,.\s]", "", left).strip()

    if not shown:
        return _number(said), UNITS.get(unit, unit)

    if shown.isdigit():
        return int(shown), UNITS.get(unit, unit)

    value = qidianfont.number_of(shown, table)
    return value, UNITS.get(unit, unit)


def _font_of_page(client, soup, fonts: dict | None = None,
                  keeper=None) -> dict | None:
    """Таблица подстановки цифр для **этой** страницы.

    Внутри страницы шрифт один: сайт повторяет одно и то же объявление
    `@font-face` в каждой строке, и качать его на каждую из сотни книг
    незачем. А вот между страницами он разный — и коды, и имя семейства
    сайт перебирает заново. Поэтому таблица берётся на страницу, а не на
    весь срез, и по имени семейства не ищется: имя сайт может повторить,
    подменив сам файл, и тогда числа второй страницы молча оказались бы
    прочитаны таблицей первой. Повторно разбирать один и тот же файл всё
    равно не придётся: кэш внутри `qidianfont` считает по хешу.
    """
    css = ""
    for tag in soup.find_all("style"):
        text = tag.string or tag.get_text() or ""
        if "@font-face" in text and "font-family" in text:
            css = text
            break
    if not css:
        return None

    family, address = qidianfont.font_of(css)
    if not address:
        return None

    # Один и тот же файл на две страницы сайт кладёт редко, но кладёт.
    # Запоминаем по адресу: качать одно и то же дважды незачем, а взять
    # чужую таблицу по такому ключу невозможно — адрес и есть файл.
    fonts = fonts if fonts is not None else {}
    if address in fonts:
        return fonts[address]

    try:
        pass_by = keeper.cookies(address) if keeper is not None else None
        data = client.get(address, cookies=pass_by).content
    except Exception as exc:  # noqa: BLE001 — без чисел рейтинг всё равно жив
        log.info("Шрифт цифр Цидяня не скачался (%s): %s", address, exc)
        return None

    try:
        table = qidianfont.table_for(family, data, address)
    except qidianfont.FontUnavailable as exc:
        log.info("Цифры Цидяня не расшифровались: %s", exc)
        return None
    fonts[address] = table
    return table


# -------------------------------------------------------------- одна строка

def _big_row(item, place: int, table: dict | None) -> RankRow | None:
    """Строка со страницы рейтинга — той, где у книги есть описание.

    На самой доске сайт печатает книгу целиком: обложка, название, автор,
    жанр с поджанром, статус, аннотация, последняя глава и время. Берём
    всё — иначе за тем же самым пришлось бы лезть на страницу книги,
    сотню раз на сотню строк.
    """
    head = item.select_one(".book-mid-info h2 a[href]")
    if head is None:
        return None
    code = _code_of(head)
    if not code:
        return None

    name = _clean(head.get_text(" ", strip=True)) or _clean(head.get("title"))
    if not name:
        return None

    shown = 0
    said = str(item.get("data-rid") or "").strip()
    if said.isdigit():
        shown = int(said)

    author = ""
    writer = item.select_one(".book-mid-info p.author a.name")
    if writer is not None:
        author = writer.get_text(" ", strip=True)

    # Жанр и поджанр — соседние ссылки в той же строке: 都市 · 异术超能.
    kinds = []
    for tag in item.select(".book-mid-info p.author a"):
        if "name" in (tag.get("class") or []):
            continue
        word = tag.get_text(" ", strip=True)
        if word and word not in kinds:
            kinds.append(word)

    status = ""
    mark = item.select_one(".book-mid-info p.author span")
    if mark is not None:
        status = mark.get_text(" ", strip=True)

    about = ""
    intro = item.select_one(".book-mid-info p.intro")
    if intro is not None:
        about = intro.get_text(" ", strip=True)

    # «最新更新 第七百二十三章 阴家天才！» — сайт приписывает к названию
    # главы слова «последнее обновление». В строке они лишние.
    last, updated = "", ""
    fresh = item.select_one(".book-mid-info p.update")
    if fresh is not None:
        link = fresh.find("a")
        if link is not None:
            last = re.sub(r"^最新更新\s*", "",
                          link.get_text(" ", strip=True)).strip()
        when = fresh.find("span")
        if when is not None:
            updated = when.get_text(" ", strip=True)

    value, unit = _hidden_number(item, table)

    row = RankRow(
        place=shown or place,
        book_id=code,
        name=name,
        author=author,
        category=" · ".join(kinds),
        readers=0,
        score=value if value else None,
        metric=unit if value else "",
        status=status,
        last_chapter=last,
        cover=COVER.format(code=code),
        site=SITE_KEY,
        link=f"{SITE}/book/{code}/",
    )
    # Описание и дата в строке рейтинга не предусмотрены — у остальных
    # сайтов их там нет. Кладём рядом: раскрытая карточка возьмёт их
    # отсюда и не пойдёт за ними второй раз на сайт.
    row.about = about
    row.updated = updated
    return row


def _short_row(item, place: int, table: dict | None) -> RankRow | None:
    """Строка из бокового блока рейтинга на главной или в разделе.

    Там доска ужата до десяти книг: у первой обложка, автор и число,
    у остальных только место, название и число. Эти блоки — не главная
    цель, но по ним разбор писался изначально, и на страницах разделов
    они по-прежнему единственный рейтинг.
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

    unit = ""
    digital = item.select_one("p.digital")
    if digital is not None:
        word = re.sub(r"[\d,.\s]", "", digital.get_text(" ", strip=True))
        unit = UNITS.get(word, "")

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
        metric=unit if value else "",
        cover=COVER.format(code=code),
        site=SITE_KEY,
        link=f"{SITE}/book/{code}/",
    )


def _rows_of(soup, table: dict | None, start: int) -> list[RankRow]:
    """Строки одной страницы.

    Сначала — доска целиком (`#rank-view-list`), она есть только на самой
    странице рейтинга. Нет её — боковые блоки главной и раздела.
    """
    rows: list[RankRow] = []
    board = soup.select_one("#rank-view-list") or soup.select_one(
        "div.book-img-text")
    if board is not None:
        for item in board.select("li[data-rid]"):
            row = _big_row(item, start + len(rows) + 1, table)
            if row is not None:
                rows.append(row)
        if rows:
            return rows

    # Боковые блоки скоплены нарочно: на главной книжных ссылок под сотню,
    # и половина из них — реклама, «редакция советует» и «недавно
    # обновлённые». Взять их все значило бы выдать за рейтинг то, что
    # рейтингом не является.
    for block in (soup.select("div.rank-list") or soup.select("div.book-list")):
        for item in block.find_all("li"):
            row = _short_row(item, start + len(rows) + 1, table)
            if row is not None:
                rows.append(row)
    return rows


def _next_page(soup) -> str:
    """Адрес следующей страницы доски. Пусто — она последняя.

    Адрес берётся со страницы, а не складывается по правилу: у Цидяня в
    нём сидят год и месяц (`year2026-month08-page2`), и собирать это
    самим значило бы гадать, какой месяц сайт считает текущим.
    """
    link = soup.select_one("a.lbf-pagination-next[href]")
    if link is None:
        return ""
    address = _full(link.get("href"))
    return "" if address.rstrip("/").endswith("javascript:") else address


def _walk(client, address: str, keeper=None) -> tuple[list[RankRow], int, str]:
    """Пролистать доску с одного адреса. Возвращает строки, сколько из
    них с расшифрованным числом, и первую страницу целиком.

    Первую страницу держим ради разбора полётов: без неё «не
    разобралось» остаётся словами, по которым нечего чинить.

    Пропуск — один на весь обход: он же и есть «гость», а гость, у
    которого отпечаток меняется от страницы к странице, защите как раз
    и подозрителен. Подпись при этом пересчитывается на каждый адрес.
    """
    keeper = keeper if keeper is not None else qidianpass.Pass()
    rows: list[RankRow] = []
    seen: set[str] = set()
    fonts: dict[str, dict] = {}
    decoded = 0
    page_address = address
    first = ""

    for _ in range(PAGES):
        try:
            page = client.get_text(page_address, headers=VISIT,
                                   cookies=keeper.cookies(page_address))
        except HttpError as exc:
            if not rows:
                raise
            # Первая страница уже в руках: половина рейтинга лучше, чем
            # ничего, а листать дальше явно не выйдет.
            log.warning("Цидянь оборвал листание на %s: %s", page_address, exc)
            break

        if not first:
            first = page
        log.info("Цидянь: %s — страница %s байт", page_address, len(page or ""))

        soup = BeautifulSoup(page, "lxml")
        table = _font_of_page(client, soup, fonts, keeper)

        found = _rows_of(soup, table, len(rows))
        for row in found:
            if row.book_id in seen:
                continue
            seen.add(row.book_id)
            rows.append(row)
            if row.score:
                decoded += 1
            if len(rows) >= TOP:
                break
        log.info("Цидянь: %s — книг на странице %s, всего набрано %s",
                 page_address, len(found), len(rows))

        if len(rows) >= TOP:
            break
        page_address = _next_page(soup)
        if not page_address:
            break

    # Места на странице печатаются вперемешку: в боковых блоках у первой
    # книги «NO.1», дальше цифрами, и в каждом блоке нумерация начинается
    # заново. На самой доске такого нет, но и сюда мы приходим не только
    # с неё.
    if len({row.place for row in rows}) != len(rows):
        for number, row in enumerate(rows, 1):
            row.place = number

    return rows, decoded, first


def _reach(client, address: str) -> tuple[list[RankRow], int, str]:
    """Пройти доску, перебрав формы пропуска.

    Что защита кладёт в подпись — адрес целиком или один путь — мы знаем
    не наверняка (см. `qidianpass`). Проверить это отсюда нечем: сайт из
    песочницы недоступен. Поэтому не пустила первая форма — идём второй,
    прежде чем объявлять сайт закрытым. Второй заход делается только на
    заглушку защиты: если пришла настоящая страница, пропуск приняли, и
    беда в чём-то другом — менять форму подписи бессмысленно.
    """
    keeper = qidianpass.Pass()
    rows, decoded, first = _walk(client, address, keeper)
    if rows or not _guarded(first):
        return rows, decoded, first

    log.info("Цидянь: %s — пропуск не приняли, пробуем вторую форму подписи",
             address)
    return _walk(client, address, keeper.other())


def _mirrors(board: str, channel: str) -> list[str]:
    """Адреса, по которым стоит попробовать эту доску.

    Первый — полный сайт. Второй, мобильный, добавляется не всегда:
    скрипт самого Цидяня переводит в мобильный вид только шесть досок и
    ничего не знает про разделы. Просить у мобильного сайта раздел,
    которого у него нет, значило бы получить список «по всем разделам» и
    подписать его выбранным жанром — то есть соврать. Поэтому мобильный
    адрес идёт в дело только там, где он равнозначен.
    """
    found = [url_of(board, channel)]
    if not channel and board in MOBILE_BOARDS:
        found.append(f"{MOBILE}/rank/{PATHS[board]}/")
    return found


def fetch(client, board: str = "yuepiao", channel: str = "") -> dict:
    """Срез одной доски одного раздела.

    Адресов пробуем несколько: если полный сайт встретил проверкой на
    робота, у мобильного она своя и бывает мягче. Каждая попытка
    записывается в лог и, если не вышло ни одна, попадает в сообщение —
    гадать, что именно не открылось, не приходится.
    """
    tries: list[str] = []

    for address in _mirrors(board, channel):
        try:
            rows, decoded, first = _reach(client, address)
        except HttpError as exc:
            # Без «сайт не ответил»: при HTTP 202 он как раз ответил, и
            # эта приписка сбивала с толку сильнее, чем помогала. Текст
            # беды и так говорит, что случилось.
            said = f"{address} — {exc}"
            log.warning("Цидянь: %s", said)
            tries.append(said)
            continue

        if rows:
            log.info("Цидянь: %s — снято книг %s, с числом %s",
                     address, len(rows), decoded)
            return {
                "rows": rows,
                "board": board,
                "category": channel,
                "version": _version(rows),
                "stats_date": "",
                # «Расшифровано» здесь — про числа доски, а не про
                # названия: названия у Цидяня открыты, шрифтом спрятаны
                # только цифры.
                "decoded": decoded,
                "total": len(rows),
                "address": address,
            }

        said = _diagnose(first, address)
        log.warning("Цидянь: %s. Начало ответа: %s", said,
                    re.sub(r"\s+", " ", str(first or ""))[:400])
        tries.append(said)

    raise SourceBroken(" | ".join(tries) if tries else
                       f"Рейтинг Цидяня: пробовать было нечего, доска {board}")


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
    keeper = qidianpass.Pass()
    try:
        page = client.get_text(address, headers=VISIT,
                               cookies=keeper.cookies(address))
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
           "TOP", "UNITS", "book", "fetch", "url_of"]
