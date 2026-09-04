"""Источник Dreamy Translations — книга целиком лежит в потоке Next.js.

Сайт собран на Next.js с серверными компонентами, и это меняет всё. Ни
одного запроса к API у него нет: страница книги приходит одним куском, а
внутри неё, в тегах `<script>self.__next_f.push(...)`, лежит поток
серверных данных — так называемый flight. В нём и книга, и **всё**
оглавление разом: идентификаторы, названия, номера и метка «бесплатна ли
глава».

Из этого следует главное удобство: оглавление на девяносто семь глав
стоит **одного** запроса, а не девяноста семи.

Поток режется на куски по границам скриптов, и одна логическая запись
может оказаться разорванной между двумя `push`. Поэтому куски сперва
склеиваются в одну строку и только потом разбираются: иначе на длинной
книге оглавление обрывалось бы ровно там, где Next решил перенести.

**Про вёрстку — уточнение, купленное ошибкой.** Сперва здесь было
написано, что списка глав в разметке нет вовсе. Это неправда: строки
`<a data-chapter-index=… href=…/chapter/N>` в HTML есть, просто лежат
внутри скрытого блока, который React потом подставляет на место
заглушек. Видимая часть страницы и правда набита пустыми полосками, но
из этого не следует, что данных в ней нет.

Поэтому путей к оглавлению два, и оба рабочие. Поток идёт первым: в нём
есть то, чего в разметке нет, — идентификаторы и метка «бесплатна ли
глава». Разметка идёт вторым номером, на случай если сайт перестанет
класть поток на страницу книги.

Адрес главы строится по её **номеру**, а не по идентификатору:
`/novel/<слаг>/chapter/<номер>`. Идентификатор в ссылках не участвует
вовсе, хотя в потоке и лежит.

Откуда взяты приметы главы. Из расширения `dteviot/WebToEpub` (GPL-3.0):
у него на этот сайт заведён свой разборщик, и там записано то, что
снаружи не угадать, — что текст главы лежит в `.chapter-content`, а
примечания переводчика в `sup.tl-note` и в книгу их брать не надо. Взяты
именно правила: селекторы. Как и для сайтов-сливов, см. README.

**Живьём не проверено.** Сайт закрыт для среды, в которой писался модуль
(прокси отвечает 403), поэтому разбор проверен на настоящей странице
книги, сохранённой человеком, а не на живом запросе. Разбор устроен так,
чтобы молчаливой полукниги не вышло: не нашлось ни потока, ни разметки —
модуль говорит «источник изменился» и прикладывает страницу, а не отдаёт
пустоту.
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from .base import Chapter, Novel, Source, SourceBroken, Toc

log = logging.getLogger(__name__)

#: Витрина. Она же `Referer` для запросов глав.
SITE = "https://dreamy-translations.com"

#: Слаг книги. Ловится и из адреса книги, и из адреса главы: человек
#: приносит то, что у него открыто, а открыта у него чаще глава.
BOOK_PATH = re.compile(r"(?:^|/)novel/([^/?#]+)", re.IGNORECASE)

#: Начало куска потока. Номер внутри — служебный счётчик Next, и
#: привязываться к конкретному нельзя: он меняется от сборки к сборке.
PUSH = re.compile(r'self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*"', re.DOTALL)

#: Обложка лежит отдельным полем рядом с книгой.
COVER = re.compile(r'"coverUrl":"([^"]*)"')

#: Где в потоке искать текст главы. Порядок — от точного к общему:
#: первым берётся то поле, которое сайт для текста и завёл.
CHAPTER_KEYS = ("content", "body", "html", "text")

#: Заголовки обычного перехода по ссылке, а не голого запроса. Сайт
#: закрывается от того, что на браузер не похоже: у человека он рвал
#: соединение на середине ответа («Connection was reset»), хотя то же
#: расширение в его же браузере страницу забирало. Отпечаток TLS клиент
#: подделывает и сам (`curl_cffi` с `impersonate`), а вот заголовки
#: навигации до сих пор были куцые.
HEADERS = {
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Referer": f"{SITE}/",
}

#: Приметы главы и оглавления в разметке. Из WebToEpub, см. заголовок.
CONTENT_AT = ".chapter-content"
TITLE_AT = "button.text-2xl span > span"
#: Примечания переводчика: в книге они не нужны.
NOTES_AT = "sup.tl-note"
#: Строка оглавления. Номер главы стоит атрибутом — гадать по тексту
#: ссылки не нужно.
ROW_AT = "a[data-chapter-index]"

#: Разметка внутри текста главы. Абзацы и переносы рвут строку, остальные
#: теги — обёртки вокруг слов, и рвать на них нельзя: фраза распалась бы
#: на куски по каждому выделенному слову.
BREAKS = re.compile(r"(?i)</p\s*>|<br\s*/?>|</div\s*>|</h[1-6]\s*>")
TAGS = re.compile(r"<[^>]+>")

#: Пустые абзацы подряд — обычное дело в чужой вёрстке.
BLANKS = re.compile(r"\n{3,}")


def flight(page: str) -> str:
    """Склеенный поток серверных данных Next.

    Куски идут отдельными скриптами, и одна запись может быть разорвана
    между ними. Склеиваем всё в одну строку: разбирать по кускам значит
    однажды потерять хвост оглавления и не заметить.
    """
    out = []
    for found in PUSH.finditer(page):
        start = found.end()
        # Конец строкового литерала: первая кавычка, перед которой нет
        # обратной косой. Через регулярное выражение это не выразить —
        # экранированных кавычек внутри тысячи.
        i, size = start, len(page)
        while i < size:
            if page[i] == "\\":
                i += 2
                continue
            if page[i] == '"':
                break
            i += 1
        try:
            out.append(json.loads('"' + page[start:i] + '"'))
        except ValueError:
            # Кусок, который не разобрался, пропускаем: соседние целы, а
            # ронять из-за одного всю книгу незачем.
            log.debug("Кусок потока Next не разобрался")
    return "".join(out)


def carve(text: str, key: str, opener: str = "{"):
    """Значение по ключу, вырезанное по балансу скобок.

    Поток — не JSON целиком: в нём перемешаны служебные строки Next и
    ссылки вида `$L24`. Разобрать его как документ нельзя, а вот вырезать
    из него один объект по скобкам — можно.
    """
    closer = "]" if opener == "[" else "}"
    # Пробелы после двоеточия Next не ставит, но закладываться на это —
    # значит однажды молча не найти книгу из-за оформления.
    found = re.search(r'"%s"\s*:\s*\%s' % (re.escape(key), opener), text)
    if not found:
        return None

    start = found.end() - 1
    depth, i, size, quoted = 0, start, len(text), False
    while i < size:
        one = text[i]
        if quoted:
            if one == "\\":
                i += 2
                continue
            if one == '"':
                quoted = False
        elif one == '"':
            quoted = True
        elif one == opener:
            depth += 1
        elif one == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
        i += 1
    return None


def slug_of(raw: str) -> str:
    """Слаг книги из того, что человек принёс.

    Принимает адрес книги, адрес главы и голый слаг. Числового кода у
    этого сайта нет вовсе, и выдумывать его нечем.
    """
    text = str(raw or "").strip()
    if not text:
        raise SourceBroken("Не указана книга: нужна ссылка или слаг")

    found = BOOK_PATH.search(text)
    if found:
        return found.group(1)
    if "/" in text or "://" in text:
        raise SourceBroken(
            f"В ссылке нет адреса книги: ждём {SITE}/novel/<слаг>")
    return text


def paragraphs_of(html: str) -> str:
    """Абзацы из куска разметки. Качалке нужен текст, а не вёрстка."""
    if not html:
        return ""
    body = BREAKS.sub("\n", str(html))
    body = TAGS.sub("", body)
    body = (body.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#x27;", "'")
            .replace("&#39;", "'"))
    lines = [one.strip() for one in body.split("\n")]
    return BLANKS.sub("\n\n", "\n\n".join(one for one in lines if one)).strip()


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception as exc:  # noqa: BLE001 — lxml необязателен, разбор важнее
        log.debug("lxml не подошёл (%s) — разбираем встроенным", exc)
        return BeautifulSoup(html or "", "html.parser")


def rows_from_markup(page: str) -> list:
    """Оглавление из разметки — запасной путь, если поток пропал.

    Строки лежат в скрытом блоке, который React подставляет на место
    заглушек. Номер главы стоит атрибутом, поэтому гадать по тексту
    ссылки («Ch. 12») не нужно.

    Метки «платная» здесь нет: она есть только в потоке. Возвращаем то,
    что видно, и не выдумываем недостающее.
    """
    out = []
    for link in _soup(page).select(ROW_AT):
        try:
            number = int(str(link.get("data-chapter-index") or "").strip())
        except ValueError:
            continue
        if number <= 0:
            continue
        # Название главы — вторая строка в карточке; первая это «Ch. 12».
        name = link.select_one("p")
        out.append({"index": number,
                    "title": name.get_text(" ", strip=True) if name else "",
                    "href": str(link.get("href") or "")})
    return out


def content_from_markup(page: str) -> str:
    """Текст главы из разметки.

    Примечания переводчика выкидываем: в книге они не нужны, а внутри
    абзаца выглядят случайной цифрой посреди фразы.
    """
    block = _soup(page).select_one(CONTENT_AT)
    if block is None:
        return ""
    for note in block.select(NOTES_AT):
        note.decompose()
    return paragraphs_of(str(block))


def title_from_markup(page: str) -> str:
    """Заголовок главы из разметки. Не нашёлся — берём из оглавления."""
    found = _soup(page).select_one(TITLE_AT)
    return found.get_text(" ", strip=True) if found else ""


class DreamySource(Source):
    """Dreamy Translations: английские переводы, отданные открыто."""

    key = "dreamy"
    name = "Dreamy Translations"
    placeholder = "https://dreamy-translations.com/novel/… или слаг"
    hint = ("Английские переводы. Всё оглавление приходит одной страницей, "
            "поэтому список глав строится за один запрос.")
    needs_proxy = False

    def _page(self, client, url: str) -> tuple[str, str]:
        """Страница и её поток. Пустой поток — уже поломка разбора."""
        page = client.get_text(url, headers=HEADERS)
        data = flight(page)
        if not data:
            raise SourceBroken(
                "На странице нет данных Next — сайт перестроили или "
                "ответила заглушка", page)
        return page, data

    def find(self, client, query: str) -> Novel:
        slug = slug_of(query)
        page, data = self._page(client, f"{SITE}/novel/{slug}")

        book = carve(data, "project")
        if not isinstance(book, dict) or not book.get("title"):
            raise SourceBroken(
                f"Книга {slug} не разобралась: в данных страницы нет "
                "карточки", page)

        found = COVER.search(data)
        return Novel(
            # Кода у сайта нет, а число нужно: берём его же id книги.
            code=int(book.get("id") or 0),
            name=str(book.get("title") or "").strip(),
            slug=str(book.get("slug") or slug),
            total_chapters=int(book.get("total_chapters") or 0),
            author=str(book.get("author") or "").strip(),
            status="завершена" if book.get("completed") else "выходит",
            language="en",
            cover=found.group(1) if found else "",
        )

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        """Оглавление целиком — одним запросом.

        Диапазон отрезаем уже здесь, у себя: ходить за ним на сайт
        незачем, он всё равно отдаёт весь список разом.
        """
        slug = novel.slug or str(novel.code)
        page, data = self._page(client, f"{SITE}/novel/{slug}")

        rows = carve(data, "chapters", "[")
        if not isinstance(rows, list) or not rows:
            # Поток пропал — берём то же из разметки. Метки «платная» там
            # нет, и это честнее, чем выдумать её отсутствие.
            rows = rows_from_markup(page)
            if rows:
                log.info("Оглавление %s собрано по разметке: потока не было",
                         slug)
        if not rows:
            raise SourceBroken(
                f"У книги {slug} не нашлось списка глав — сайт перестроили",
                page)

        chapters = []
        for one in rows:
            if not isinstance(one, dict):
                continue
            number = int(one.get("index") or 0)
            if number <= 0 or number < first:
                continue
            if last is not None and number > last:
                continue
            chapters.append(Chapter(
                number=number,
                post_id=str(one.get("id") or number),
                ch_name=str(one.get("title") or "").strip(),
                link=f"{SITE}/novel/{slug}/chapter/{number}",
                # Платную главу видно уже здесь, и это экономит прогон:
                # ходить за ней, чтобы получить отказ, незачем.
                locked=one.get("free") is False,
            ))

        chapters.sort(key=lambda one: one.number)
        if on_progress:
            on_progress(len(chapters), len(chapters))

        have = {one.number for one in chapters}
        edge = last if last is not None else (max(have) if have else 0)
        missing = [n for n in range(first, edge + 1) if n not in have]
        return Toc(chapters=chapters, missing=missing)

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        url = chapter.link
        if not url:
            raise SourceBroken(
                f"Глава {chapter.number} без адреса — оглавление читалось "
                "другой версией программы, соберите его заново")

        page, data = self._page(client, url)

        # Разметка идёт первой: примета `.chapter-content` снята с
        # расширения, которое разбирает этот сайт на живых книгах, а
        # имя поля в потоке пришлось бы угадывать.
        body = content_from_markup(page)
        title = title_from_markup(page)

        if not body:
            # Запасной путь: тот же текст в потоке серверных данных.
            block = carve(data, "chapter")
            if isinstance(block, dict):
                for name in CHAPTER_KEYS:
                    body = paragraphs_of(block.get(name) or "")
                    if body:
                        break
                title = title or str(block.get("title") or "").strip()

        if not body:
            raise SourceBroken(
                f"Глава {chapter.number}: на странице не нашлось текста "
                f"(ни в {CONTENT_AT}, ни в данных Next) — сайт перестроили",
                page)

        return title or chapter.ch_name, body


def novel_link(slug: str) -> str:
    """Адрес книги на витрине."""
    return f"{SITE}/novel/{slug}"


def host_is_ours(url: str) -> bool:
    """Наш ли это сайт. Нужно тому, кто раскладывает ссылки по источникам."""
    host = (urlparse(str(url or "")).hostname or "").lower()
    return host.endswith("dreamy-translations.com")


__all__ = ["DreamySource", "carve", "flight", "host_is_ours", "novel_link",
           "paragraphs_of", "slug_of"]
