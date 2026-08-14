"""Источник Фанкью (fanqienovel.com).

Скачиваются только свободно открытые главы. Платные не трогаем: у них в
ответе вместо текста приходит заглушка, и такая глава пропускается с
понятной причиной, а не сохраняется огрызком.

У сайта нестабильный внутренний API. Поэтому весь разбор ответа проходит
через `_need`: если поля нет или оно другого вида, модуль говорит
«источник изменился», а не выдаёт мусор молча. Это важнее удобства —
книга на пятьсот глав, скачанная в тишине неправильно, обнаруживается
через неделю.

Модуль написан по описанию из ТЗ и открытых адресов сайта; за основу для
разбора взят подход проекта `ying-ck/fanqienovel-downloader` (AGPL-3.0),
см. README.
"""

from __future__ import annotations

import json
import logging
import re

from .base import Chapter, Novel, Source, SourceBroken, Toc

log = logging.getLogger(__name__)

SITE = "https://fanqienovel.com"
#: Внутренний адрес, отдающий текст главы. Меняется чаще остального.
READER_API = "https://fanqienovel.com/api/reader/full"

#: Ссылка на книгу: /page/<id>. Код — только цифры.
BOOK_LINK = re.compile(r"/page/(\d{6,25})")
CODE_ONLY = re.compile(r"^\d{6,25}$")

#: Ссылка на главу в оглавлении.
ITEM_LINK = re.compile(r"/reader/(\d{6,25})")

#: Заглушка вместо платной главы. Текста в ответе нет вовсе либо он
#: подменён приглашением заплатить.
PAID_MARKERS = ("需要付费", "购买本章", "付费章节", "本章为付费章节")


def _need(value, what: str):
    """Достаёт то, без чего дальше нельзя, либо честно сообщает о поломке."""
    if value in (None, "", [], {}):
        raise SourceBroken(
            f"Источник изменился: в ответе нет «{what}». "
            "Скачивание невозможно, пока модуль не поправят.")
    return value


def _json(text: str, what: str):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SourceBroken(
            f"Источник изменился: вместо JSON пришло что-то другое ({what}).") from exc


def _clean(html: str) -> str:
    """Текст главы из разметки.

    Абзацы у сайта размечены `<p>`, поэтому режем по ним, а не по
    переводам строк: в исходнике их нет вовсе.
    """
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    parts = re.split(r"(?i)</p\s*>", html)
    out = []
    for part in parts:
        line = re.sub(r"(?s)<[^>]+>", "", part)
        line = (line.replace("&nbsp;", " ").replace("&amp;", "&")
                    .replace("&lt;", "<").replace("&gt;", ">")
                    .replace("&quot;", '"').replace("&#39;", "'"))
        line = line.strip()
        if line:
            out.append(line)
    return "\n\n".join(out)


class PaidChapter(Exception):
    """Глава платная — её мы не трогаем."""


class FanqieSource(Source):
    key = "fanqie"
    name = "Fanqie"
    hint = "ссылка вида fanqienovel.com/page/7143038691944959011 или её код"
    #: Сайт китайский и из России открывается через раз.
    needs_proxy = True

    # ------------------------------------------------------------- поиск

    def code_of(self, query: str) -> str:
        """Код книги из ссылки или из самого кода."""
        query = (query or "").strip()
        found = BOOK_LINK.search(query)
        if found:
            return found.group(1)
        if CODE_ONLY.match(query):
            return query
        raise ValueError(
            "Нужна ссылка на книгу Фанкью или её числовой код "
            "(в ссылке это часть после /page/)")

    def find(self, client, query: str) -> Novel:
        code = self.code_of(query)
        html = client.get_text(f"{SITE}/page/{code}")
        info = self._book_info(html, code)
        return Novel(
            code=int(code),
            name=info["name"],
            slug=code,
            total_chapters=info["total"],
            author=info.get("author", ""),
            status=info.get("status", ""),
            language="zh",
        )

    def _book_info(self, html: str, code: str) -> dict:
        """Название, автор и число глав со страницы книги.

        Сайт отдаёт данные страницы отдельным блоком JSON — из него они и
        берутся: разбирать вёрстку бессмысленно, она меняется чаще.
        """
        block = re.search(
            r'(?s)<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
        if block:
            data = _json(block.group(1), "страница книги")
            found = _dig(data, "bookName") or _dig(data, "book_name")
            total = _dig(data, "serialCount") or _dig(data, "chapterCount")
            return {
                "name": str(_need(found, "название книги")),
                "author": str(_dig(data, "author") or ""),
                "status": str(_dig(data, "creationStatus") or ""),
                "total": int(total or 0),
            }

        # Запасной разбор: заголовок страницы. Хуже, но лучше пустоты.
        title = re.search(r"(?is)<title>(.*?)</title>", html)
        if not title:
            raise SourceBroken(
                "Источник изменился: страница книги больше не разбирается.")
        name = title.group(1).split("_")[0].strip()
        log.warning("Фанкью: данные книги %s взяты из заголовка страницы", code)
        return {"name": name or f"book-{code}", "author": "", "status": "",
                "total": 0}

    # -------------------------------------------------------- оглавление

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        html = client.get_text(f"{SITE}/page/{novel.code}")
        items = self._items(html)
        if not items:
            raise SourceBroken(
                "Источник изменился: список глав на странице книги не найден.")

        last = last or len(items)
        if last < first:
            raise ValueError(f"Диапазон глав пуст: {first}..{last}")

        chapters, missing = [], []
        for number in range(first, min(last, len(items)) + 1):
            item_id, title = items[number - 1]
            chapters.append(Chapter(
                number=number,
                post_id=int(item_id),
                ch_name=title,
                link=f"{SITE}/reader/{item_id}",
            ))
            if on_progress:
                on_progress(len(chapters), last - first + 1)

        # Книга короче запрошенного — это не ошибка, но сказать надо.
        missing = list(range(len(items) + 1, last + 1))
        if missing:
            log.warning("Фанкью: в книге %s глав, запрошено до %s",
                        len(items), last)
        return Toc(chapters=chapters, missing=missing)

    def _items(self, html: str) -> list[tuple[str, str]]:
        """Пары (id главы, название) в порядке чтения."""
        block = re.search(
            r'(?s)<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
        if block:
            data = _json(block.group(1), "оглавление")
            found = _dig(data, "chapterListWithVolume") or _dig(data, "allItemIds")
            items = _flatten_items(found)
            if items:
                return items

        # Запасной разбор: ссылки прямо в вёрстке.
        pairs = re.findall(
            r'(?is)<a[^>]+href="[^"]*?/reader/(\d{6,25})"[^>]*>(.*?)</a>', html)
        return [(item_id, re.sub(r"(?s)<[^>]+>", "", title).strip())
                for item_id, title in pairs]

    # -------------------------------------------------------------- глава

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        item_id = chapter.post_id
        if not item_id:
            raise SourceBroken("У главы нет идентификатора Фанкью.")

        raw = client.get_text(f"{READER_API}?itemId={item_id}")
        data = _json(raw, "текст главы")

        code = data.get("code")
        if code not in (0, "0", None):
            raise SourceBroken(
                f"Источник ответил кодом {code} — разбор невозможен.")

        item = (data.get("data") or {}).get("chapterData") or {}
        content = item.get("content")
        title = str(item.get("title") or chapter.title)

        if not content or any(mark in str(content) for mark in PAID_MARKERS):
            raise PaidChapter(
                f"Глава {chapter.number} платная — пропускаем")

        text = _clean(str(content))
        if not text.strip():
            raise SourceBroken(
                f"Источник изменился: в главе {chapter.number} нет текста.")
        return title, text


def _dig(data, key: str):
    """Первое значение по ключу на любой глубине.

    Структура ответа у сайта меняется, а имена полей держатся дольше:
    искать по ключу надёжнее, чем ходить по фиксированному пути.
    """
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


def _flatten_items(found) -> list[tuple[str, str]]:
    """Приводит любую известную форму оглавления к парам (id, название)."""
    items: list[tuple[str, str]] = []
    if not found:
        return items

    def walk(node):
        if isinstance(node, dict):
            item_id = node.get("itemId") or node.get("item_id") or node.get("id")
            title = node.get("title") or node.get("chapterTitle") or ""
            if item_id and str(item_id).isdigit():
                items.append((str(item_id), str(title).strip()))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and node.isdigit():
            items.append((node, ""))

    walk(found)
    return items
