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

Почему один модуль на несколько сайтов. Движок у них общий: текст главы
в `.chapter-content`, полный список — по адресу `/{код}/dir`. Отличаются
мелочи, и они вынесены в таблицу правил: следующий такой же сайт
добавляется одной записью, а не новым модулем.

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
        toc_lists=("ul.all",),
        content=(".chapter-content",),
        title=("h1",),
        author=("#detail span.author",),
        cover=("#detail img",),
        paged=False,
    ),
)

#: Полный список глав — отдельная страница у обоих сайтов.
TOC_PAGE = "dir"

#: Номер главы в её названии: «第1056章 ...».
CHAPTER_NUMBER = re.compile(r"第\s*(\d+)\s*[章节節]")

#: Пометка «страница такая-то из стольких-то» в заголовке: «(1/2)».
PAGE_OF = re.compile(r"[(（]\s*\d+\s*/\s*\d+\s*[)）]")

#: Адрес главы: «8096_1062.html», продолжение — «8096_1062_2.html».
#: Первые два числа — это и есть глава; хвост «_2» означает вторую
#: страницу той же главы, а не следующую главу.
CHAPTER_FILE = re.compile(r"/(\d+_\d+)(?:_\d+)?\.html")

#: Ссылки «дальше» стоят в подвале главы. Последняя из них ведёт либо на
#: следующую страницу той же главы, либо уже на следующую главу.
FOOT_NAV = ".foot-nav a"

#: Куски внутри текста главы, которые к книге отношения не имеют.
JUNK_CLASSES = ("gadblock", "adblock", "banner", "foot-nav", "header")

#: Сколько страниц одной главы готовы пройти. Разложенная на части глава
#: — обычное дело, бесконечная — признак хождения по кругу.
MAX_PAGES = 20


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:  # noqa: BLE001 — lxml необязателен, разбор важнее
        return BeautifulSoup(html or "", "html.parser")


def _host_of(url: str) -> str:
    """Хост без `www.`; пустая строка — адрес не разобрать."""
    try:
        host = (urlparse(url).netloc or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def rule_for(url: str) -> SiteRule | None:
    """Правило разбора по адресу. None — сайт не из списка."""
    host = _host_of(url)
    if not host:
        return None
    for rule in SITES:
        for known in rule.hosts:
            if host == known or host.endswith("." + known):
                return rule
    return None


def _pick(page, selectors, extra=()):
    """Первый подошедший селектор из списка, потом из запасных."""
    for where in tuple(selectors) + tuple(extra):
        found = page.select_one(where)
        if found is not None:
            return found
    return None


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
    hint = ("Запасной путь, когда Фанкью и посредник молчат. Вставьте "
            "адрес книги целиком — например "
            "https://www.novel543.com/0407653271/ или "
            "https://www.timotxt.com/2005553271/. Текст там лежит "
            "открыто: ни входа, ни оплаты, ни шифрования шрифтом.")
    needs_proxy = False

    # ----------------------------------------------------------- книга

    def code_of(self, query: str) -> str:
        """Код книги из адреса. Пусто — адрес не от этих сайтов."""
        text = (query or "").strip()
        if rule_for(text) is None:
            return ""
        path = [part for part in urlparse(text).path.split("/") if part]
        return path[0] if path else ""

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
        return rule, code, f"{parts.scheme}://{parts.netloc}/{code}/"

    def find(self, client, query: str) -> Novel:
        rule, code, book = self._book_url(query)
        page = _soup(client.get_text(book))
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
        if on_progress:
            on_progress(len(wanted), len(wanted))

        have = {c.number for c in wanted}
        missing = [n for n in range(first, upto + 1) if n not in have]
        return Toc(chapters=wanted, missing=missing)

    def _links(self, client, rule: SiteRule, book: str):
        """Все главы: (номер, название, полный адрес).

        Страница книги показывает только последние главы; весь список
        лежит по отдельному адресу `/{код}/dir` — это не догадка, так
        устроены оба сайта.
        """
        listing = urljoin(book, TOC_PAGE)
        page = _soup(client.get_text(listing))
        menu = _pick(page, rule.toc_lists, FALLBACK_TOC)
        if menu is None:
            return []

        rows = []
        seen = set()
        for link in menu.select("a[href]"):
            href = (link.get("href") or "").strip()
            title = link.get_text(strip=True)
            if not href or not title or href.startswith("#"):
                continue
            full = urljoin(listing, href)
            if full in seen:
                continue
            seen.add(full)
            rows.append([None, title, full])

        # Номер берём из названия главы. Есть у всех — считаем его
        # настоящим и сортируем по нему. Нет хотя бы у одной — нумеруем
        # по порядку списка и порядок не трогаем: на странице `/dir`
        # главы и так идут подряд.
        numbers = [CHAPTER_NUMBER.search(row[1]) for row in rows]
        if rows and all(numbers):
            for row, found in zip(rows, numbers):
                row[0] = int(found.group(1))
            rows.sort(key=lambda row: row[0])
        else:
            for order, row in enumerate(rows, 1):
                row[0] = order

        return [tuple(row) for row in rows]

    # ------------------------------------------------------------ глава

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        address = chapter.link or str(chapter.post_id or "")
        if not address:
            raise SourceBroken(f"У главы {chapter.number} нет адреса.")

        rule = rule_for(address)
        if rule is None:
            raise SourceBroken(f"Адрес главы {chapter.number} не с того сайта.")

        title = ""
        pieces: list[str] = []
        seen: set[str] = set()

        for _ in range(MAX_PAGES):
            if address in seen:
                break
            seen.add(address)

            page = _soup(client.get_text(address))
            head, text = self._one_page(page, rule, chapter)
            title = title or head
            pieces.extend(text)

            following = self._next_page(page, address) if rule.paged else ""
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

        # Заголовок нередко повторён первой строкой текста — в книге он
        # окажется дважды, и «убрать название» этого уже не поправит.
        if rows and title and rows[0].strip() == title:
            rows = rows[1:]

        return title, rows

    @staticmethod
    def _next_page(page, address: str) -> str:
        """Следующая страница той же главы. Пусто — глава кончилась.

        В подвале стоят ссылки «назад / оглавление / вперёд», и
        последняя ведёт либо на продолжение этой главы, либо уже на
        следующую. Отличаем по адресу: продолжение начинается с того же
        «8096_1062», к нему лишь дописан номер страницы. Без этой
        проверки главы склеились бы, а книга собралась с дырами.
        """
        here = CHAPTER_FILE.search(address)
        if not here:
            return ""

        links = page.select(FOOT_NAV)
        if not links:
            return ""
        href = (links[-1].get("href") or "").strip()
        if not href:
            return ""

        following = urljoin(address, href)
        return following if f"/{here.group(1)}_" in following else ""


__all__ = ["NovelCmsSource", "SiteRule", "SITES", "rule_for"]
