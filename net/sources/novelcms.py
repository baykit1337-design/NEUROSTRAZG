"""Сайты-сливы: книга целиком лежит в открытую, вставил ссылку — качаем.

Зачем. Основной путь к Фанкью упирается в закрытые главы, а посредник —
чужая машина, которая однажды просто замолчала. Эти сайты держат тот же
текст открытым: ни входа, ни оплаты, ни расшифровки шрифта.

Почему один модуль на несколько сайтов. `novel543.com` и `timotxt.com`
собраны на одном движке: у них совпадает разметка до имён классов —
список глав в `.chaplist`, текст в `#chapterWarp .chapter-content
.content`, абзацы обычными `<p>`. Различаются только адреса и вид ссылок
на главу. Поэтому правило разбора одно, а сайты — просто список хостов,
и следующий такой же добавляется одной строкой.

Про WebToEpub. Задача пришла как «встроить репозиторий WebToEpub», но
встроить его нельзя: это расширение браузера на JavaScript, оно живёт
внутри вкладки и ходит в сеть от имени открытой страницы. Библиотеки,
которую можно позвать из Python, там нет. Ценное в нём — правила разбора
для конкретных сайтов, по три десятка строк на сайт; здесь написано
такое же правило для этого движка.

Границы честности. Разметка взята из живых страниц обоих сайтов, но
сами сайты из окружения разработки недоступны, и прогнать модуль по ним
не удалось: проверять его надо на настоящей книге. Поэтому ни один адрес
здесь не собирается по догадке — ссылки берутся из самой страницы. Если
разметка окажется другой, модуль скажет «источник изменился», а не
принесёт молча половину книги.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from .base import Chapter, Novel, Source, SourceBroken, Toc

log = logging.getLogger(__name__)

#: Сайты на этом движке. Ключ — хост, значение — как зовётся на экране.
#: Список открытый: следующий такой же сайт добавляется одной строкой,
#: разбор для него уже написан.
KNOWN_HOSTS = {
    "novel543.com": "novel543",
    "timotxt.com": "timotxt",
}

#: Номер главы в её названии: «第1056章 ...».
CHAPTER_NUMBER = re.compile(r"第\s*(\d+)\s*[章节節]")

#: Пометка о том, что глава разложена по страницам: «(1/2)» в заголовке.
PAGE_OF = re.compile(r"[(（]\s*(\d+)\s*/\s*(\d+)\s*[)）]")

#: Подписи ссылки «дальше по этой же главе». У движка их несколько
#: написаний, и полагаться на адрес нельзя — только на текст ссылки.
NEXT_PAGE_WORDS = ("下一页", "下一頁", "下页", "下頁")

#: Ссылка на полный список глав. На странице книги показаны только
#: последние, а весь список — за отдельной ссылкой.
MORE_WORDS = ("查看全部", "全部章节", "全部章節", "更多", "目录", "目錄")

#: Куски внутри текста главы, которые к книге отношения не имеют.
JUNK_CLASSES = ("gadblock", "adblock", "ad", "ads", "banner")

#: Сколько страниц одной главы готовы пройти. Разложенная на части глава
#: — обычное дело, бесконечная — признак того, что мы ходим по кругу.
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


def _known(host: str) -> str:
    """Имя движка по хосту. Пусто — сайт не из списка."""
    for known, name in KNOWN_HOSTS.items():
        if host == known or host.endswith("." + known):
            return name
    return ""


def _junk(tag) -> bool:
    """Реклама и счётчики внутри текста главы."""
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
        if not _known(_host_of(text)):
            return ""
        path = [part for part in urlparse(text).path.split("/") if part]
        return path[0] if path else ""

    def find(self, client, query: str) -> Novel:
        address = (query or "").strip()
        host = _host_of(address)
        if not _known(host):
            raise SourceBroken(
                "Этот источник принимает только полный адрес книги с "
                "поддерживаемого сайта: "
                + ", ".join(sorted(KNOWN_HOSTS)) + ". "
                "Пример: https://www.novel543.com/0407653271/")

        code = self.code_of(address)
        if not code:
            raise SourceBroken(
                f"В адресе «{address}» нет кода книги. Он идёт сразу за "
                "именем сайта: https://www.novel543.com/0407653271/")

        page = _soup(client.get_text(address))
        name = self._book_name(page, code)
        rows = self._links(client, page, address)

        return Novel(
            code=self._as_number(code),
            name=name,
            #: Полный адрес книги: по нему потом строятся ссылки на главы,
            #: и терять его нельзя — код у каждого сайта свой.
            slug=address,
            total_chapters=len(rows),
            author=self._labelled(page, "作者"),
            status=self._labelled(page, "分類"),
            language="zh",
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
        for where in ("#detail h1", ".book-name", "h1"):
            found = page.select_one(where)
            if found and found.get_text(strip=True):
                return found.get_text(strip=True)
        title = page.find("title")
        if title and title.get_text(strip=True):
            # У движка заголовок вида «Название - Сайт»: берём до тире.
            return re.split(r"\s*[-|_｜]\s*", title.get_text(strip=True))[0]
        return f"book-{code}"

    @staticmethod
    def _labelled(page, label: str) -> str:
        """Значение подписи вида «作者：имя» из шапки книги."""
        text = page.get_text("\n", strip=True)
        found = re.search(rf"{label}\s*[:：]\s*(.+)", text)
        return found.group(1).strip() if found else ""

    # ------------------------------------------------------- оглавление

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        address = novel.slug
        if not address:
            raise SourceBroken("У книги не сохранён адрес — найдите её заново.")

        page = _soup(client.get_text(address))
        rows = self._links(client, page, address)
        if not rows:
            raise SourceBroken(
                "Источник изменился: на странице книги не нашлось списка "
                "глав. Скачивание невозможно, пока модуль не поправят.")

        chapters = [
            Chapter(number=number, post_id=link, ch_name=title, link=link)
            for number, title, link in rows
        ]
        upto = last or (chapters[-1].number if chapters else 0)
        wanted = [c for c in chapters if first <= c.number <= upto]
        if on_progress:
            on_progress(len(wanted), len(wanted))

        have = {c.number for c in wanted}
        missing = [n for n in range(first, upto + 1) if n not in have]
        return Toc(chapters=wanted, missing=missing)

    def _links(self, client, page, address: str):
        """Список глав: (номер, название, полный адрес).

        На странице книги показаны только последние главы, а весь список
        — за отдельной ссылкой. Её адрес не выдумываем: идём по той
        ссылке, что есть на самой странице.
        """
        rows = self._from_list(page, address)
        full = self._more_link(page, address)
        if full and full != address:
            try:
                whole = self._from_list(_soup(client.get_text(full)), full)
            except Exception as exc:  # noqa: BLE001 — частичный список лучше пустого
                log.warning("Полный список глав не открылся (%s): %s", full, exc)
            else:
                if len(whole) > len(rows):
                    rows = whole
        return rows

    @staticmethod
    def _from_list(page, address: str):
        rows = []
        seen = set()
        for link in page.select(".chaplist a[href], #chaplist a[href], "
                                ".chapter-list a[href]"):
            href = (link.get("href") or "").strip()
            title = link.get_text(strip=True)
            if not href or not title or href.startswith("#"):
                continue
            full = urljoin(address, href)
            if full in seen:
                continue
            seen.add(full)
            rows.append([None, title, full])

        # Номер берём из названия главы. Его там может не быть — тогда
        # нумеруем по порядку: без номера качалка не соберёт диапазон.
        for order, row in enumerate(rows, 1):
            found = CHAPTER_NUMBER.search(row[1])
            row[0] = int(found.group(1)) if found else order
        rows.sort(key=lambda row: row[0])
        return [tuple(row) for row in rows]

    @staticmethod
    def _more_link(page, address: str) -> str:
        for link in page.select("a[href]"):
            words = link.get_text(strip=True)
            if any(mark in words for mark in MORE_WORDS):
                return urljoin(address, link["href"])
        return ""

    # ------------------------------------------------------------ глава

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        address = chapter.link or str(chapter.post_id or "")
        if not address:
            raise SourceBroken(f"У главы {chapter.number} нет адреса.")

        title = ""
        pieces: list[str] = []
        seen = set()

        # Глава может быть разложена по страницам — «(1/2)» в заголовке.
        # Ходим по ссылке «дальше», а не по придуманному адресу: у
        # движка он не выводится из первого.
        for _ in range(MAX_PAGES):
            if address in seen:
                break
            seen.add(address)

            page = _soup(client.get_text(address))
            head, text = self._one_page(page, chapter)
            title = title or head
            pieces.extend(text)

            following = self._next_page(page, address)
            if not following:
                break
            address = following

        if not pieces:
            raise SourceBroken(
                f"Источник изменился: в главе {chapter.number} не нашлось "
                "текста. Скачивание невозможно, пока модуль не поправят.")

        return (title or chapter.title), "\n\n".join(pieces)

    def _one_page(self, page, chapter: Chapter):
        body = page.select_one("#chapterWarp .content, .chapter-content .content,"
                               " #content, .content")
        if body is None:
            raise SourceBroken(
                f"Источник изменился: в главе {chapter.number} не нашлось "
                "блока с текстом.")

        head = page.select_one(".chapter-content h1, #chapterWarp h1, h1")
        title = head.get_text(strip=True) if head else ""
        # Номер страницы в заголовке — служебная пометка, в книге ей не
        # место: «Глава 1056 (1/2)» и «(2/2)» это одна глава.
        title = PAGE_OF.sub("", title).strip()

        rows = []
        for para in body.find_all("p"):
            if para.find_parent(_junk) is not None or _junk(para):
                continue
            words = para.get_text(" ", strip=True)
            if words:
                rows.append(words)

        if not rows:
            # Разметка без `<p>`: берём текст блока, выкинув мусор.
            for bad in body.find_all(_junk):
                bad.decompose()
            rows = [line.strip() for line in
                    body.get_text("\n", strip=True).splitlines() if line.strip()]

        return title, rows

    @staticmethod
    def _next_page(page, address: str) -> str:
        """Ссылка «дальше по этой же главе». Пусто — глава кончилась.

        Именно по этой же: «следующая глава» рядом выглядит так же, но
        уводит на другую главу, и книга собралась бы с дырами.
        """
        for link in page.select("a[href]"):
            words = link.get_text(strip=True)
            if any(mark in words for mark in NEXT_PAGE_WORDS):
                return urljoin(address, link["href"])
        return ""


__all__ = ["NovelCmsSource", "KNOWN_HOSTS"]
