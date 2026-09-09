"""Сайты-сливы: книга целиком лежит в открытую, вставил ссылку — качаем.

Зачем. Основной путь к Фанкью упирается в закрытые главы, а посредник —
чужая машина, которая однажды просто замолчала. Эти сайты держат тот же
текст открытым: ни входа, ни оплаты, ни расшифровки шрифта.

Откуда правила разбора. Из расширения `dteviot/WebToEpub` (GPL-3.0): у
него на каждый сайт заведён свой разборщик, и там записано то, что
снаружи не угадать — где лежит полный список глав и как отличить
продолжение той же главы от следующей. Само расширение встроить нельзя:
это JavaScript, живущий внутри вкладки браузера, библиотеки для Python
там нет. Взяты именно правила: адреса и селекторы. См. README.

Почему один модуль на дюжину сайтов. Устроены они одинаково: страница
книги, где-то рядом полный список глав, у главы блок с текстом. Разными
оказываются не приёмы, а мелочи — где именно лежит список, как называется
блок с текстом, в какой кодировке страница, разложена ли глава на
страницы. Всё это вынесено в таблицу правил: следующий сайт добавляется
одной записью, а не новым модулем.

Как выбирается разбор. По хосту вставленного адреса — `rule_for`. Никаких
«попробуем этот, потом тот»: правило либо есть, либо источник честно
говорит, что сайт незнаком, и перечисляет знакомые.

Границы честности. Сайты из окружения разработки недоступны, прогнать
модуль по живой книге не удалось. Поэтому разбор устроен так, чтобы
молчаливой полукниги не вышло: не нашлось списка глав или текста —
модуль говорит «источник изменился», а не отдаёт пустоту.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .base import Chapter, Novel, Source, SourceBroken, Toc

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TocApi:
    """Оглавление, которое приходит отдельным запросом, а не в вёрстке.

    Так устроен ixdzs8: на странице книги висят только последние восемь
    глав, а весь список отдаётся по `POST /novel/clist/` в виде JSON.
    Разобрать такую страницу вёрсткой можно — и получить восьмиглавую
    книгу молча, с бодрым отчётом об успехе. Поэтому список берётся
    оттуда, откуда его берёт сам сайт.

    Имена полей вынесены сюда, а не зашиты в разбор: движок этот стоит не
    на одном сайте, а поля у соседей называются по-своему.
    """

    #: Куда стучаться — относительно адреса книги.
    path: str
    #: Как в запросе называется код книги.
    code_field: str
    #: Шаблон адреса главы: `{code}` — книга, `{order}` — номер по списку.
    #: Номер по списку это НЕ номер главы: у 异度旅社 402 главы, а последняя
    #: лежит по `p399.html` — тома в нумерации не участвуют.
    chapter: str
    #: Где в ответе лежит список и как называются его поля.
    rows: str = "data"
    title: str = "title"
    order: str = "ordernum"
    #: Поле, которым помечен заголовок тома: у него нет своей страницы.
    volume: str = "ctype"


@dataclass(frozen=True)
class Archive:
    """Книга целиком одним файлом — кнопкой «скачать TXT».

    Восемьсот запросов против одного: разница между сорока минутами и
    десятью секундами. Ради этого стоит сходить за архивом.

    Но заменить им оглавление нельзя, и вот почему. Внутри главы
    подписаны **авторской** нумерацией, а она начинается заново в каждом
    томе: «第18章 烈火烹油» — это восемьсот пятнадцатая глава по счёту
    сайта, а вовсе не восемнадцатая. Номер в архиве не уникален, и
    раскладывать главы по нему — верный способ собрать кашу.

    Поэтому архив здесь только ускоритель текста. Оглавление, номера и
    названия по-прежнему берутся у сайта, а глава из архива берётся по
    **порядку** — и лишь тогда, когда её заголовок совпал с тем, что
    сказал сайт. Не совпал — идём за ней в сеть, как раньше. Так
    несовпадение архива с сайтом (вышла новая глава, архив собран вчера)
    даёт лишний запрос, а не сдвинутую на главу книгу.
    """

    #: Где лежит. `{code}` — код книги.
    url: str
    #: Чем записан. Тот же gb18030, что и у страниц.
    encoding: str = "gb18030"


#: Заголовок главы внутри архива: с начала строки и без отступа. Абзацы
#: текста начинаются с двух идеографических пробелов, заголовки — нет,
#: и это единственное, чем они надёжно отличаются.
WHOLE_HEAD = re.compile(r"^第\s*(\d+)\s*[章节節話话]\s*(.*)$")

#: С каких размеров прогона архив выгоднее поглавной качки. Три главы
#: из шестимегабайтного архива — это хуже трёх запросов.
WHOLE_WORTH = 20


@dataclass(frozen=True)
class SiteRule:
    """Где у сайта что лежит.

    Списки селекторов — по порядку: первый подошедший и работает.
    Запасные держим намеренно: разметку правят, и лучше найти текст
    вторым способом, чем остановить книгу целиком.
    """

    name: str
    hosts: tuple[str, ...]
    #: Список глав целиком. Страница книги показывает только последние.
    toc_lists: tuple[str, ...]
    content: tuple[str, ...]
    title: tuple[str, ...]
    author: tuple[str, ...] = ()
    cover: tuple[str, ...] = ()
    #: Глава может быть разложена по страницам.
    paged: bool = False

    #: Где в адресе лежит код книги — выражением с одной скобкой. Пусто —
    #: код это последний кусок пути.
    #:
    #: Последний кусок годится, пока книга лежит папкой: `/book/45540/`.
    #: Но у части сайтов она лежит файлом — `/book/45540.htm`, — и общее
    #: правило отбрасывает файл вместе с кодом, оставляя слово «book».
    #: Дальше по такому «коду» собирается адрес, который ведёт в никуда.
    code_re: str = ""
    #: Как из кода собрать адрес страницы книги. Пусто — берём тот, что
    #: вставил человек, обрезав до папки.
    #:
    #: Нужно там же, где и `code_re`: вставленный адрес главы обрезается
    #: до `/txt/45540/`, а книга лежит по `/book/45540.htm`. Собрать её
    #: адрес из кода — единственный способ прийти на страницу книги, с
    #: какой бы страницы сайта человек ни копировал ссылку.
    book_url: str = ""

    #: Где лежит полный список глав относительно страницы книги.
    #: Пусто — прямо на ней. У части сайтов это отдельная страница
    #: `/{код}/dir`, у части — своя, на которую ведёт ссылка (см. ниже).
    toc_page: str = ""
    #: Готовый адрес списка глав по коду книги — сильнее всего
    #: остального. У части сайтов страница оглавления показывает первую
    #: сотню и кнопку «ещё», а весь список лежит отдельным куском
    #: вёрстки, за которым сайт ходит сам.
    toc_url: str = ""
    #: Список идёт от новых к старым. Разворачиваем до нумерации: если
    #: номер главы стоит в её названии, порядок задаст он, но стоит он
    #: не у каждой — «新年快乐！» номера не имеет вовсе. Одна такая глава,
    #: и книга сохранится задом наперёд.
    toc_reverse: bool = False
    #: Что выкинуть из блока с текстом у этого сайта. Общий список
    #: `JUNK_CLASSES` знает рекламу и навигацию; сюда идёт то, что назвал
    #: сам сайт, — вроде строки с числом прочтений над главой.
    junk: tuple[str, ...] = ()
    #: Ссылка на страницу оглавления, если её адрес не угадать. Сильнее
    #: `toc_page`: раз сайт сам сказал, куда идти, гадать незачем.
    toc_link: tuple[str, ...] = ()
    #: Оглавление разложено по страницам: селектор их перечня и слова,
    #: которыми подписана последняя. Дальше страницы нумеруются подряд.
    #: Без этого от книги достаётся первая сотня глав, и это худший из
    #: возможных исходов — полукнига, о которой никто не предупредил.
    toc_more: tuple[str, ...] = ()
    toc_last: tuple[str, ...] = ("尾页", "尾頁", "末页", "Last page")
    #: Оглавление смотреть на мобильной версии: у части сайтов десктопная
    #: отдаёт только последние главы, а полный список есть на `m.`.
    toc_mobile: bool = False
    #: Кодировка страниц. Пусто — как решит сервер (обычно utf-8).
    #: Часть китайских сайтов до сих пор отдаёт gb2312 или gbk, и без
    #: явного указания текст выходит набором вопросительных знаков.
    encoding: str = ""
    #: Ссылка на продолжение той же главы. Пусто — берём общую.
    next_page: tuple[str, ...] = ()
    #: Оглавление приходит отдельным запросом. Заполнено — вёрстку
    #: страницы книги под список глав не смотрим вовсе.
    toc_api: TocApi | None = None
    #: Книга целиком одним файлом. Заполнено — текст глав берём оттуда,
    #: а в сеть ходим только за теми, которых в архиве не нашлось.
    archive: Archive | None = None


#: Общие запасные селекторы: если сайт перерисуют, разбор не встанет
#: намертво. В начале всегда идут точные, из правил сайта.
FALLBACK_CONTENT = ("#chapterWarp .chapter-content", ".chapter-content",
                    "#chapterWarp .content", "#content")
FALLBACK_TITLE = (".chapter-content h1", "#chapterWarp h1", "h1")
FALLBACK_TOC = ("div.chaplist ul", "#chaplist ul", ".chapter-list")

SITES: tuple[SiteRule, ...] = (
    SiteRule(
        name="novel543",
        # Тот же движок обслуживает и второй адрес — так у WebToEpub.
        hosts=("novel543.com", "twbook.cc"),
        # На странице `/dir` два списка: первый — последние главы,
        # второй — все. Нужен именно второй.
        toc_page="dir",
        toc_lists=("div.chaplist ul:nth-of-type(2)", "ul.all"),
        content=("div.chapter-content",),
        title=("h1.title",),
        author=("span.author",),
        cover=("div.cover img",),
        paged=True,
    ),
    SiteRule(
        name="timotxt",
        hosts=("timotxt.com",),
        toc_page="dir",
        toc_lists=("ul.all",),
        content=(".chapter-content",),
        title=("h1",),
        author=("#detail span.author",),
        cover=("#detail img",),
        paged=False,
    ),
    SiteRule(
        # Один движок на семь адресов: они и правда близнецы, отличаются
        # только доменом. Добавить восьмой — дописать сюда строку.
        name="88xiaoshuo",
        hosts=("88xiaoshuo.net", "ilwxs.com", "ttshu8.com", "xpaoshuba.com",
               "shuhaige.net", "qbxsw.com"),
        # Оглавление на мобильной версии и разложено по страницам:
        # десктопная отдаёт только последние главы.
        toc_mobile=True,
        toc_lists=(".read",),
        toc_more=(".caption > span > a",),
        content=("div.content",),
        title=(".headline",),
        author=("#maininfo a[href*=author]", ".author a"),
        cover=(".box_con img", ".detail > img"),
        paged=True,
        next_page=(".pager a",),
    ),
    SiteRule(
        name="230book",
        # `38xs.com` — тот же движок; мобильная версия у него другая, но
        # адрес книги человек копирует из адресной строки, а там десктоп.
        hosts=("230book.net", "38xs.com"),
        toc_lists=("#list",),
        content=("#content",),
        title=(".bookname h1",),
        cover=("#fmimg img", "#picture img"),
        encoding="gbk",
        paged=True,
        next_page=("a#pager_next",),
    ),
    SiteRule(
        name="ddxs",
        hosts=("ddxs.com",),
        # Список лежит во второй таблице страницы: первая — служебная.
        toc_lists=("table:nth-of-type(2)",),
        content=("#contents",),
        title=("dd h1",),
        cover=(".pic img",),
    ),
    SiteRule(
        name="ffxs8",
        hosts=("ffxs8.com",),
        toc_lists=("div.catalog",),
        content=("div.content",),
        title=("div.article h1",),
        cover=("div.cover img",),
        encoding="gb2312",
    ),
    SiteRule(
        name="biquge-tw",
        hosts=("biquge.tw",),
        # Адрес оглавления не угадать — сайт сам даёт на него ссылку.
        toc_link=("a.chapterlist",),
        toc_lists=("div.booklist ul",),
        content=("#chaptercontent",),
        title=(".book h1", "h1"),
        author=(".book .right h2 a",),
        cover=(".cover img",),
        paged=True,
        next_page=("a#next_url",),
    ),
    SiteRule(
        name="shw5",
        hosts=("shw5.cc", "bqka.cc"),
        toc_lists=("div.listmain",),
        content=("#chaptercontent",),
        title=("h1",),
        cover=(".cover img", "#fmimg img"),
    ),
    SiteRule(
        name="ixdzs",
        # Три адреса одного сайта: упрощённый, гонконгский и тайваньский.
        # Перечисляет их сам сайт — `<link rel="alternate">` на каждой
        # странице, — так что гадать не пришлось.
        hosts=("ixdzs8.com", "ixdzs.hk", "ixdzs.tw"),
        toc_api=TocApi(path="/novel/clist/", code_field="bid",
                       chapter="/read/{code}/p{order}.html"),
        # На странице книги есть кнопка «скачать TXT»: та же книга одним
        # файлом. Восемьсот запросов против одного.
        archive=Archive(url="https://down7.ixdzs8.com/{code}.zip"),
        # В вёрстке книги лежат только последние восемь глав. Оставлять
        # их запасным путём нельзя: восьмиглавая книга — худший исход,
        # потому что выглядит она как удача.
        toc_lists=(),
        content=("article.page-content section",),
        title=("h1.page-d-name", "article.page-content h3"),
        author=("a.bauthor",),
        cover=(".n-img img",),
    ),
    SiteRule(
        name="69shu",
        # У WebToEpub правило записано по куску имени: любой хост, где
        # встречается «69shu». Так здесь не сделано намеренно — под ту же
        # мерку попадает `69shuba.tw`, а он свёрстан иначе, и разбор взял
        # бы не те селекторы молча. Названо то, что видели своими
        # глазами; соседний адрес добавится строкой, когда будет с чем
        # сверить.
        hosts=("69shuba.com",),
        # Книга лежит файлом, а не папкой: `/book/45540.htm`.
        code_re=r"/(?:book|txt)/(\d+)",
        book_url="/book/{code}.htm",
        # Полный список — по ссылке «完整目录» со страницы книги: в самой
        # странице висят только последние пять глав.
        toc_link=("a.more-btn",),
        toc_lists=("#catalog ul",),
        # Список идёт от новой главы к первой.
        toc_reverse=True,
        content=("div.txtnav",),
        title=(".txtnav h1",),
        author=(".booknav2 a[href*=author]",),
        cover=(".bookimg2 img",),
        junk=(".txtinfo", "#txtright", ".bottom-ad"),
        # Сайт объявляет gbk, но пишет в gb18030 — это надмножество, и
        # редкие знаки в gbk не помещаются. Так же у WebToEpub.
        encoding="gb18030",
    ),
    SiteRule(
        name="twkan",
        hosts=("twkan.com",),
        code_re=r"/(?:book|txt)/(\d+)",
        book_url="/book/{code}.html",
        # Страница оглавления показывает начало списка и кнопку «ещё».
        # Весь список сайт берёт вот отсюда — и мы оттуда же, иначе от
        # книги досталась бы сотня глав с бодрым отчётом об успехе.
        toc_url="/ajax_novels/chapterlist/{code}.html",
        toc_lists=("ul",),
        content=("#txtcontent0",),
        title=(".txtnav h1",),
        author=(".booknav2 p a[href*='/author/']",),
        cover=(".bookimg2 img",),
        junk=(".txtinfo", "#txtright", ".bottom-ad", ".txtcenter"),
    ),
    SiteRule(
        name="sjks88",
        hosts=("sjks88.com",),
        toc_lists=("div.list",),
        content=(".content",),
        title=("h1",),
        encoding="gb2312",
    ),
)

#: Слова, которыми подписана ссылка на продолжение той же главы.
NEXT_WORDS = ("下一页", "下一頁", "下页", "next page")

#: Номер главы в её названии: «第1056章 ...».
CHAPTER_NUMBER = re.compile(r"第\s*(\d+)\s*[章节節]")

#: Пометка «страница такая-то из стольких-то» в заголовке: «(1/2)».
PAGE_OF = re.compile(r"[(（]\s*\d+\s*/\s*\d+\s*[)）]")

#: Ссылки «дальше» стоят в подвале главы. Последняя из них ведёт либо на
#: следующую страницу той же главы, либо уже на следующую главу.
FOOT_NAV = ".foot-nav a"

#: Куски внутри текста главы, которые к книге отношения не имеют.
JUNK_CLASSES = ("gadblock", "adblock", "banner", "foot-nav", "header")

#: Чем сайт подписывает конец главы. Это пометка вёрстки, а не текст
#: книги, и в файле она смотрится строкой из ниоткуда.
TAIL_MARKS = ("(本章完)", "（本章完）", "（本章結束）", "(本章结束)",
              "(全书完)", "（全書完）")

#: Сколько страниц одной главы готовы пройти. Разложенная на части глава
#: — обычное дело, бесконечная — признак хождения по кругу.
MAX_PAGES = 20


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception as exc:  # noqa: BLE001 — lxml необязателен, разбор важнее
        log.debug("lxml не подошёл (%s) — разбираем встроенным", exc)
        return BeautifulSoup(html or "", "html.parser")


def _host_of(url: str) -> str:
    """Хост без `www.`; пустая строка — адрес не разобрать."""
    try:
        host = (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


#: Расширение имени файла — его отбрасываем, сравниваем сами имена.
SUFFIX = re.compile(r"\.s?html?$", re.I)


def _bare(url: str) -> str:
    """Имя файла без расширения: `8096_1062_2.html` → `8096_1062_2`."""
    try:
        tail = (urlparse(url).path or "").rsplit("/", 1)[-1]
    except ValueError:
        return ""
    return SUFFIX.sub("", tail)


def _continues(origin: str, candidate: str) -> bool:
    """Продолжение ли `candidate` главы, начатой по адресу `origin`.

    Сравниваем с первым адресом главы, а не с текущей страницей, и это
    важнее, чем кажется. У части сайтов имя файла само состоит из двух
    чисел — `8096_1000.html`, где 8096 книга, а 1000 глава. Сравнивая
    страницу с предыдущей, легко принять `8096_1001` — следующую главу —
    за третью страницу текущей: у обеих «всё, кроме последнего числа»
    совпадает. Главы склеились бы попарно, а книга собралась бы вдвое
    короче.

    От первого адреса такой ошибки нет: продолжение — это он же с
    приписанным номером страницы, и ничто другое.
    """
    start = _bare(origin)
    if not start:
        return False
    return re.fullmatch(re.escape(start) + r"_\d+", _bare(candidate)) is not None


def _mobile(url: str) -> str:
    """Тот же адрес на мобильной версии.

    У части сайтов полный список глав есть только там: десктопная
    страница книги показывает последние двадцать и кнопку «дальше».
    """
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    host = parts.netloc
    if host.startswith("m."):
        return url
    host = host[4:] if host.startswith("www.") else host
    return f"{parts.scheme}://m.{host}{parts.path or '/'}"


def rule_for(url: str) -> SiteRule | None:
    """Правило разбора по адресу. None — сайт не из списка.

    Точное совпадение сильнее совпадения по хвосту. Иначе `m.38xs.com`
    достался бы правилу, записанному на `38xs.com`, — а у части сайтов
    мобильная версия свёрстана иначе, и разбор молча взял бы не те
    селекторы.
    """
    host = _host_of(url)
    if not host:
        return None
    for rule in SITES:
        if host in rule.hosts:
            return rule
    for rule in SITES:
        for known in rule.hosts:
            if host.endswith("." + known):
                return rule
    return None


def _fetch(client, url: str, rule: SiteRule) -> str:
    """Страница текстом, с оглядкой на кодировку сайта.

    Часть китайских сайтов до сих пор отдаёт gb2312 или gbk. Угадывать
    это по содержимому нельзя: ошибись — и вместо книги в файл ляжет
    строка из вопросительных знаков, причём молча.
    """
    if not rule.encoding:
        return client.get_text(url)
    raw = client.get(url).content
    if not isinstance(raw, (bytes, bytearray)):
        return str(raw or "")
    return bytes(raw).decode(rule.encoding, "replace")


def _pick(page, selectors, extra=()):
    """Первый подошедший селектор из списка, потом из запасных."""
    for where in tuple(selectors) + tuple(extra):
        found = page.select_one(where)
        if found is not None:
            return found
    return None


def _squeezed(text: str) -> str:
    """Строка без пробелов — для сравнения заголовка с первой строкой."""
    return re.sub(r"\s+", "", text or "")


def read_whole(text: str) -> list:
    """Главы из архива — по порядку, как они в нём лежат.

    Возвращаем список, а не словарь по номеру, и это не мелочь: номер в
    заголовке авторский и повторяется от тома к тому. Порядок — то
    единственное, что в архиве уникально.

    Всё до первого заголовка — шапка архива: название, автор, описание и
    строка с адресом сайта. В книгу ей нельзя.
    """
    found: list = []
    rows: list = []
    for line in (text or "").splitlines():
        # Отступ у абзаца — два идеографических пробела; у заголовка его
        # нет. Больше их ничем не различить: «第18章 ...» встречается и
        # в тексте.
        if line[:1].strip() and WHOLE_HEAD.match(line):
            rows = []
            found.append((line.strip(), rows))
            continue
        words = line.strip()
        if words and found:
            rows.append(words)
    return [(title, tuple(body)) for title, body in found]


def _junk(tag) -> bool:
    """Реклама, счётчики и навигация внутри блока с текстом."""
    if tag.name in ("script", "style", "ins", "iframe", "noscript"):
        return True
    if tag.get("data-ad") is not None:
        return True
    classes = " ".join(tag.get("class") or []).lower()
    return any(mark in classes for mark in JUNK_CLASSES)


class NovelCmsSource(Source):
    """Книга с сайта-слива по прямой ссылке."""

    key = "novelcms"
    name = "Сайт-слив по ссылке"
    placeholder = "https://www.novel543.com/0407653271/"
    #: Список сайтов складывается из таблицы правил, а не переписан
    #: сюда руками: иначе добавленный сайт остался бы неизвестным
    #: человеку, который как раз и должен вставить с него ссылку.
    hint = ("Запасной путь, когда Фанкью и посредник молчат. Вставьте "
            "адрес книги целиком — например "
            "https://www.novel543.com/0407653271/. Текст там лежит "
            "открыто: ни входа, ни оплаты, ни шифрования шрифтом. "
            "Разбор подбирается по самому адресу; сейчас известны "
            + ", ".join(sorted(h for r in SITES for h in r.hosts)) + ".")
    needs_proxy = False

    def __init__(self):
        #: Разобранный архив книги: (код книги, список глав по порядку).
        #: Держим на источнике, а не в глобальной памяти: прогон один,
        #: книга в нём одна, и после закрытия шесть мегабайт уходят.
        self._whole: tuple[str, list] | None = None
        #: Сколько глав просят у этого прогона. Ради трёх глав качать
        #: архив дороже, чем сходить за ними по одной.
        self._asked = 0

    def close(self) -> None:
        self._whole = None

    # ----------------------------------------------------------- книга

    def code_of(self, query: str) -> str:
        """Код книги из адреса. Пусто — адрес не от этих сайтов.

        Берётся последний кусок пути, а не первый. У одних сайтов книга
        лежит в корне (`/0407653271/`), у других в подпапке
        (`/book/12345/`), и «первый кусок» во втором случае давал слово
        «book» вместо кода.

        Но и последний кусок годится не везде: там, где книга лежит
        файлом (`/book/45540.htm`), общее правило отбрасывает файл
        вместе с кодом. Такие сайты называют код выражением сами.
        """
        text = (query or "").strip()
        rule = rule_for(text)
        if rule is None:
            return ""
        if rule.code_re:
            try:
                path = urlparse(text).path or ""
            except ValueError:
                return ""
            found = re.search(rule.code_re, path)
            return found.group(1) if found else ""
        path = [part for part in self._book_path(text).split("/") if part]
        return path[-1] if path else ""

    @staticmethod
    def _book_path(address: str) -> str:
        """Путь до книги: без файла главы и всегда со слешем на конце."""
        try:
            path = urlparse(address).path or "/"
        except ValueError:
            return "/"
        # Вставили адрес главы, а не книги — отбрасываем файл.
        if re.search(r"\.s?html?$", path, re.I):
            path = path.rsplit("/", 1)[0] + "/"
        return path if path.endswith("/") else path + "/"

    def _book_url(self, query: str) -> tuple[SiteRule, str, str]:
        """Правило, код книги и адрес её страницы."""
        address = (query or "").strip()
        rule = rule_for(address)
        if rule is None:
            known = ", ".join(sorted(h for r in SITES for h in r.hosts))
            raise SourceBroken(
                "Этот источник принимает только полный адрес книги с "
                f"поддерживаемого сайта: {known}. "
                "Пример: https://www.novel543.com/0407653271/")

        code = self.code_of(address)
        if not code:
            raise SourceBroken(
                f"В адресе «{address}» нет кода книги. Он идёт сразу за "
                "именем сайта: https://www.novel543.com/0407653271/")

        parts = urlparse(address)
        # Адрес книги берём из того, что вставили, а не собираем из кода:
        # у части сайтов книга лежит в подпапке, и собранный адрес вёл бы
        # в никуда.
        #
        # Кроме тех, кто сам сказал, как её адрес устроен. Там наоборот:
        # обрезать вставленное нельзя — книга лежит файлом, и от неё
        # осталась бы одна папка `/book/`. Заодно это принимает и ссылку
        # на главу: код в ней тот же, а страница книги соберётся.
        path = (rule.book_url.format(code=code) if rule.book_url
                else self._book_path(address))
        return rule, code, f"{parts.scheme}://{parts.netloc}{path}"

    def find(self, client, query: str) -> Novel:
        rule, code, book = self._book_url(query)
        page = _soup(_fetch(client, book, rule))
        rows = self._links(client, rule, book)

        return Novel(
            code=self._as_number(code),
            name=self._book_name(page, code),
            #: Полный адрес книги: по нему строятся все остальные, и
            #: терять его нельзя — код у каждого сайта свой.
            slug=book,
            total_chapters=len(rows),
            author=self._text(page, rule.author),
            status="",
            language="zh",
            cover=self._cover(page, rule, book),
        )

    @staticmethod
    def _as_number(code: str) -> int:
        """Код числом — для общих частей качалки.

        Ведущий ноль здесь теряется (`0407653271`), поэтому все адреса
        строятся от `slug`, а не от этого числа.
        """
        digits = re.sub(r"\D", "", code)
        return int(digits) if digits else 0

    def _book_name(self, page, code: str) -> str:
        for where in ("#detail h1", "h1.title", ".book-name", "h1"):
            found = page.select_one(where)
            if found and found.get_text(strip=True):
                return found.get_text(strip=True)
        title = page.find("title")
        if title and title.get_text(strip=True):
            # Заголовок вида «Название - Сайт»: берём до разделителя.
            return re.split(r"\s*[-|_｜]\s*", title.get_text(strip=True))[0]
        return f"book-{code}"

    @staticmethod
    def _text(page, selectors) -> str:
        found = _pick(page, selectors)
        return found.get_text(strip=True) if found else ""

    @staticmethod
    def _cover(page, rule: SiteRule, book: str) -> str:
        found = _pick(page, rule.cover)
        src = (found.get("src") or found.get("data-src") or "") if found else ""
        return urljoin(book, src) if src else ""

    # ------------------------------------------------------- оглавление

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        book = novel.slug
        rule = rule_for(book) if book else None
        if rule is None:
            raise SourceBroken(
                "У книги не сохранён адрес сайта — найдите её заново.")

        rows = self._links(client, rule, book)
        if not rows:
            raise SourceBroken(
                "Источник изменился: список глав не нашёлся. Скачивание "
                "невозможно, пока модуль не поправят.")

        chapters = [Chapter(number=number, post_id=link, ch_name=title,
                            link=link)
                    for number, title, link in rows]
        upto = last or chapters[-1].number
        wanted = [c for c in chapters if first <= c.number <= upto]
        self._asked = len(wanted)
        if on_progress:
            on_progress(len(wanted), len(wanted))

        have = {c.number for c in wanted}
        missing = [n for n in range(first, upto + 1) if n not in have]
        return Toc(chapters=wanted, missing=missing)

    def _listing(self, client, rule: SiteRule, book: str) -> tuple[str, object]:
        """Адрес страницы с полным списком глав и она сама.

        У сайтов это устроено тремя разными способами, и все три здесь:
        список прямо на странице книги, список по известной приписке
        (`/dir`) и список по ссылке, которую сайт даёт сам. Гадать между
        ними нельзя — не тот адрес молча даёт «последние двадцать глав»
        вместо тысячи.
        """
        listing = book
        if rule.toc_url:
            # Готовый адрес сильнее всего остального: сайт сам ходит
            # именно туда, а страница оглавления показывает начало
            # списка и кнопку «ещё».
            listing = urljoin(listing, rule.toc_url.format(
                code=self.code_of(book)))
            return listing, _soup(_fetch(client, listing, rule))
        if rule.toc_mobile:
            listing = _mobile(listing)
        elif rule.toc_page:
            listing = urljoin(listing, rule.toc_page)

        page = _soup(_fetch(client, listing, rule))

        if rule.toc_link:
            found = _pick(page, rule.toc_link)
            href = (found.get("href") or "").strip() if found else ""
            if href:
                listing = urljoin(listing, href)
                page = _soup(_fetch(client, listing, rule))
        return listing, page

    @staticmethod
    def _more_pages(page, listing: str, rule: SiteRule) -> list:
        """Остальные страницы оглавления.

        Ссылка «в конец» знает номер последней страницы; между второй и
        ею адреса идут подряд. Без этого от книги досталась бы первая
        сотня глав — полукнига, о которой никто не предупредил.
        """
        if not rule.toc_more:
            return []
        for link in page.select(", ".join(rule.toc_more)):
            words = link.get_text(strip=True)
            if words not in rule.toc_last:
                continue
            href = (link.get("href") or "").strip()
            found = re.search(r"_(\d+)/?$", href)
            if not found:
                return []
            last = int(found.group(1))
            base = re.sub(r"_\d+/?$", "", urljoin(listing, href)).rstrip("/")
            return [f"{base}_{number}" for number in range(2, last + 1)]
        return []

    @staticmethod
    def _numbered(rows: list) -> list:
        """Проставить номера главам и упорядочить их.

        Номер берём из названия главы. Есть у всех — считаем его
        настоящим и сортируем по нему. Нет хотя бы у одной — нумеруем по
        порядку списка и порядок не трогаем: сайт и так отдаёт главы
        подряд, а сортировка по половинчатым номерам их перемешала бы.
        """
        numbers = [CHAPTER_NUMBER.search(row[1]) for row in rows]
        if rows and all(numbers):
            for row, found in zip(rows, numbers):
                row[0] = int(found.group(1))
            rows.sort(key=lambda row: row[0])
        else:
            for order, row in enumerate(rows, 1):
                row[0] = order
        return [tuple(row) for row in rows]

    def _from_api(self, client, rule: SiteRule, book: str):
        """Оглавление отдельным запросом — там, где сайт делает так же.

        Запасного пути тут нет намеренно. На странице книги висят
        последние восемь глав, и разобрать её вёрсткой значило бы отдать
        восьмиглавую книгу — молча и с отчётом об успехе.
        """
        api = rule.toc_api
        code = self.code_of(book)
        where = urljoin(book, api.path)
        try:
            answer = client.post(where, data={api.code_field: code}).json()
        except Exception as exc:  # noqa: BLE001 — беда одна, причин много
            raise SourceBroken(
                f"Список глав не пришёл ({where}): {exc}. У этого сайта "
                "он приходит отдельным запросом, и без него скачивать "
                "нечего.") from exc

        found = answer.get(api.rows) if isinstance(answer, dict) else None
        if not isinstance(found, list) or not found:
            raise SourceBroken(
                f"Источник изменился: в ответе со списком глав ({where}) "
                "самого списка нет. Скачивание невозможно, пока модуль не "
                "поправят.")

        rows = []
        for item in found:
            if not isinstance(item, dict):
                continue
            if str(item.get(api.volume) or "").strip() == "1":
                # Заголовок тома, а не глава: своей страницы у него нет.
                continue
            title = str(item.get(api.title) or "").strip()
            order = str(item.get(api.order) or "").strip()
            if not title or not order:
                continue
            rows.append([None, title, urljoin(
                book, api.chapter.format(code=code, order=order))])
        return self._numbered(rows)

    def _links(self, client, rule: SiteRule, book: str):
        """Все главы: (номер, название, полный адрес)."""
        if rule.toc_api is not None:
            return self._from_api(client, rule, book)

        listing, page = self._listing(client, rule, book)

        rows = []
        seen = set()

        def collect(where, page_url: str) -> None:
            menu = _pick(where, rule.toc_lists, FALLBACK_TOC)
            if menu is None:
                return
            for link in menu.select("a[href]"):
                href = (link.get("href") or "").strip()
                title = link.get_text(strip=True)
                if not href or not title or href.startswith("#"):
                    continue
                full = urljoin(page_url, href)
                if full in seen:
                    continue
                seen.add(full)
                rows.append([None, title, full])

        collect(page, listing)
        for address in self._more_pages(page, listing, rule):
            collect(_soup(_fetch(client, address, rule)), address)

        if rule.toc_reverse:
            # Разворачиваем до нумерации, а не после: там, где номер
            # стоит в названии каждой главы, порядок задаст он и
            # разворот ничего не изменит. Но стоит он не у каждой — и
            # тогда порядок остаётся тот, что дал сайт.
            rows.reverse()
        return self._numbered(rows)

    # ------------------------------------------------------------ глава

    def _archive(self, client, rule: SiteRule, code: str) -> list:
        """Книга целиком, разобранная на главы. Пусто — не вышло.

        Неудача здесь ничего не ломает: не скачался архив, не открылся,
        оказался не тем — качаем по главам, как раньше. Поэтому и молчим
        в журнал, а не отказом: сама книга не пострадала.
        """
        if self._whole is not None and self._whole[0] == code:
            return self._whole[1]

        import io
        import zipfile

        where = rule.archive.url.format(code=code)
        found: list = []
        try:
            raw = client.get(where).content
            with zipfile.ZipFile(io.BytesIO(bytes(raw))) as box:
                # Имя файла внутри не угадываем: берём самый большой из
                # текстовых. Книга в архиве одна, и она же самая тяжёлая.
                inside = [one for one in box.infolist()
                          if not one.is_dir() and one.file_size]
                inside.sort(key=lambda one: one.file_size, reverse=True)
                if inside:
                    text = box.read(inside[0]).decode(
                        rule.archive.encoding, "replace")
                    found = read_whole(text)
        except Exception as exc:  # noqa: BLE001 — архив это ускорение, не книга
            log.info("Архив книги не забрать (%s): %s — качаем по главам",
                     where, exc)

        self._whole = (code, found)
        if found:
            log.info("Архив книги забран одним запросом (%s): глав в нём %d",
                     where, len(found))
        return found

    def _from_whole(self, client, rule: SiteRule, chapter: Chapter,
                    address: str):
        """Глава из архива. `None` — берём её из сети, как раньше.

        Сверяемся по заголовку, а не по номеру. Номер в архиве
        авторский и повторяется от тома к тому, а по порядку архив может
        разойтись с сайтом: вышла новая глава, архив собран вчера. Не
        сошлось — лишний запрос, а не сдвинутая на главу книга.
        """
        if rule.archive is None or self._asked < WHOLE_WORTH:
            return None
        rows = self._archive(client, rule, self.code_of(address))
        if not 0 < chapter.number <= len(rows):
            return None

        title, body = rows[chapter.number - 1]
        said = chapter.ch_name or ""
        if not said or _squeezed(said) != _squeezed(title):
            log.info("Глава %d в архиве подписана иначе (%r против %r) — "
                     "берём её из сети", chapter.number, title, said)
            return None
        if not body:
            return None
        return title, "\n\n".join(body)

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        address = chapter.link or str(chapter.post_id or "")
        if not address:
            raise SourceBroken(f"У главы {chapter.number} нет адреса.")

        rule = rule_for(address)
        if rule is None:
            raise SourceBroken(f"Адрес главы {chapter.number} не с того сайта.")

        ready = self._from_whole(client, rule, chapter, address)
        if ready is not None:
            return ready

        title = ""
        pieces: list[str] = []
        seen: set[str] = set()
        #: Первый адрес главы. С ним сверяются все следующие страницы —
        #: сравнение с предыдущей путает следующую главу с продолжением.
        origin = address

        for _ in range(MAX_PAGES):
            if address in seen:
                break
            seen.add(address)

            page = _soup(_fetch(client, address, rule))
            head, text = self._one_page(page, rule, chapter)
            title = title or head
            pieces.extend(text)

            following = (self._next_page(page, address, origin, rule)
                         if rule.paged else "")
            if not following:
                break
            address = following

        if not pieces:
            raise SourceBroken(
                f"Источник изменился: в главе {chapter.number} не нашлось "
                "текста. Скачивание невозможно, пока модуль не поправят.")

        return (title or chapter.title), "\n\n".join(pieces)

    def _one_page(self, page, rule: SiteRule, chapter: Chapter):
        body = _pick(page, rule.content, FALLBACK_CONTENT)
        if body is None:
            raise SourceBroken(
                f"Источник изменился: в главе {chapter.number} не нашлось "
                "блока с текстом.")

        # То, что назвал сам сайт: строка с числом прочтений над главой,
        # столбец сбоку, реклама под текстом. Выкидываем до разбора —
        # иначе абзацы из них уедут в книгу наравне с текстом.
        for where in rule.junk:
            for bad in body.select(where):
                bad.decompose()

        head = _pick(page, rule.title, FALLBACK_TITLE)
        # Номер страницы в заголовке — служебная пометка: «(1/2)» и
        # «(2/2)» это одна глава, а не две.
        title = PAGE_OF.sub("", head.get_text(strip=True)).strip() if head else ""

        rows = []
        for para in body.find_all("p"):
            if _junk(para) or para.find_parent(_junk) is not None:
                continue
            words = para.get_text(" ", strip=True)
            if words:
                rows.append(words)

        if not rows:
            # Разметка без `<p>`: берём текст блока, выкинув мусор.
            for bad in body.find_all(_junk):
                bad.decompose()
            rows = [line.strip() for line
                    in body.get_text("\n", strip=True).splitlines()
                    if line.strip()]

        # Пометка конца главы — вёрстка, а не текст: в файле она выглядит
        # строкой из ниоткуда.
        while rows and rows[-1].strip() in TAIL_MARKS:
            rows.pop()

        # Заголовок нередко повторён первой строкой текста — в книге он
        # окажется дважды, и «убрать название» этого уже не поправит.
        #
        # Сравниваем без пробелов: ixdzs8 печатает его в шапке как
        # «第397章 意外的敌人», а первой строкой — как «第397章意外的敌人».
        # Различие в одном пробеле, и из-за него заголовок оставался.
        if rows and title and _squeezed(rows[0]) == _squeezed(title):
            rows = rows[1:]

        return title, rows

    @staticmethod
    def _next_page(page, address: str, origin: str, rule: SiteRule) -> str:
        """Следующая страница той же главы. Пусто — глава кончилась.

        Рядом с текстом стоят ссылки «назад / оглавление / вперёд», и
        последняя ведёт либо на продолжение этой главы, либо уже на
        следующую. Спутать их нельзя: в первом случае книга собралась бы
        с дырами, во втором — главы склеились бы попарно.

        Отличаем по имени файла, и сверяем его с первым адресом главы —
        почему именно с ним, написано у `_continues`. Если сайт вдобавок
        подписывает ссылку словом «下一页», предпочитаем её.
        """
        links = page.select(", ".join(rule.next_page or (FOOT_NAV,)))
        if not links:
            return ""

        named = [link for link in links
                 if link.get_text(strip=True) in NEXT_WORDS]
        chosen = named[-1] if named else links[-1]
        href = (chosen.get("href") or "").strip()
        if not href or href.startswith("#"):
            return ""

        following = urljoin(address, href)
        if following == address:
            return ""
        return following if _continues(origin, following) else ""


__all__ = ["Archive", "NovelCmsSource", "SiteRule", "SITES",
           "read_whole", "rule_for"]
