"""Источник RanobeLIB — русские переводы, отданные открытым API.

Сам сайт разбирать не нужно вовсе: витрина живёт на `ranobelib.me`, а вся
книга — карточка, оглавление и текст глав — лежит в API соседнего домена
`api.cdnlibs.org`. Ни входа, ни токена для открытых глав не требуется,
нужны только заголовки `Origin` и `Referer` со стороны витрины.

Три запроса на всю книгу:

| Что | Запрос |
|---|---|
| карточка | `GET /api/manga/{слаг}?fields[]=summary&…` |
| оглавление | `GET /api/manga/{слаг}/chapters` |
| глава | `GET /api/manga/{слаг}/chapter?volume=&number=&branch_id=` |

Текст главы приходит не готовым HTML, а деревом узлов: абзацы, переносы,
списки, вставленные картинки. Собираем из него простые абзацы — качалке
нужен текст, а не разметка.

**Живьём не проверено.** Сайт закрыт для среды, в которой писался этот
модуль, поэтому разбор проверен только на макете, отвечающем как API. С
живым сайтом первым сломается разбор ответа, а не сеть: смотреть надо на
`SourceBroken` с именем поля.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from mvl.client import HttpError

from .base import Chapter, Novel, Source, SourceBroken, Toc

#: Витрина. Она же `Referer`: без него API отвечает отказом.
SITE = "https://ranobelib.me"

#: Где лежит сама книга. Домен другой, и это не опечатка.
API = "https://api.cdnlibs.org/api/manga"

#: Что просить в карточке книги: API отдаёт только запрошенные поля.
FIELDS = ("summary", "authors", "status_id", "teams")

HEADERS = {
    "Accept": "application/json",
    "Origin": SITE,
    "Referer": f"{SITE}/",
}

#: Ссылка на книгу: `/ru/book/<слаг>`. Язык в адресе меняется, а на слаг
#: не влияет, поэтому в разборе он не участвует.
BOOK_PATH = re.compile(r"(?:^|/)book/([^/?#]+)", re.IGNORECASE)

#: Узлы дерева, после которых начинается новый абзац. Остальные (жирный,
#: курсив, ссылка) — обёртки вокруг текста, и рвать на них нельзя: фраза
#: распалась бы на куски по каждому выделенному слову.
BREAKS = frozenset({"paragraph", "heading", "listItem", "blockquote",
                    "horizontalRule", "hardBreak"})


def slug_of(query: str) -> str:
    """Слаг из ссылки или из голого слага.

    У книг RanobeLIB слаг составной — `12345--nazvanie`. Числовую часть
    не отрезаем: API принимает его целиком и по обрезанному отвечает
    отказом.
    """
    text = (query or "").strip()
    if not text:
        raise SourceBroken("Пустая ссылка на книгу")
    if "://" in text or text.startswith("//"):
        found = BOOK_PATH.search(urlparse(text).path)
        if not found:
            raise SourceBroken(
                "В ссылке нет книги. Ждём адрес вида "
                "https://ranobelib.me/ru/book/12345--nazvanie")
        return found.group(1)
    found = BOOK_PATH.search(text)
    return found.group(1) if found else text


def _data(answer) -> dict | list:
    """Полезная часть ответа. У API она всегда под ключом `data`."""
    try:
        body = answer.json()
    except ValueError as exc:
        raise SourceBroken(f"RanobeLIB ответил не JSON: {exc}") from exc
    if not isinstance(body, dict) or "data" not in body:
        raise SourceBroken("В ответе RanobeLIB нет поля data — "
                           "похоже, API изменился")
    return body["data"]


def _text_of(node, out: list[str], line: list[str]) -> None:
    """Собирает абзацы из дерева узлов.

    Рекурсивно: текст лежит в листьях, а разметка — в узлах над ними.
    Абзац закрывается на узлах из `BREAKS`; всё остальное просто
    разворачивается.
    """
    if isinstance(node, list):
        for item in node:
            _text_of(item, out, line)
        return
    if not isinstance(node, dict):
        return

    kind = str(node.get("type") or "")
    if kind == "text":
        line.append(str(node.get("text") or ""))
        return

    _text_of(node.get("content"), out, line)

    if kind in BREAKS:
        made = "".join(line).strip()
        line.clear()
        if made:
            out.append(made)


def paragraphs_of(content) -> list[str]:
    """Абзацы главы. Принимает и дерево узлов, и готовый HTML.

    API отдаёт дерево, но на части старых глав в том же поле лежит
    строка с разметкой. Разбирать её здесь незачем — этим уже занимается
    общий разбор страницы.
    """
    if isinstance(content, str):
        from mvl.api import parse_chapter_page

        _, text = parse_chapter_page(content)
        return [line for line in text.split("\n\n") if line.strip()]

    if isinstance(content, dict):
        content = content.get("content")

    out: list[str] = []
    line: list[str] = []
    _text_of(content, out, line)
    # Хвост без закрывающего узла: глава из одной строки без абзаца.
    tail = "".join(line).strip()
    if tail:
        out.append(tail)
    return out


def _branch(entry) -> str:
    """Какой перевод брать. Ветка одна — берём её, иначе первую живую.

    У книги бывает несколько команд перевода, и глава есть у каждой.
    Спрашивать человека на каждой главе нельзя, а брать все подряд —
    значит скачать книгу трижды.
    """
    for branch in entry.get("branches") or []:
        if not isinstance(branch, dict):
            continue
        # Ветка на модерации — это ещё не выложенный перевод.
        if (branch.get("moderation") or {}).get("id") == 0:
            continue
        found = branch.get("branch_id")
        if found:
            return str(found)
    return ""


class RanobeLibSource(Source):
    key = "ranobelib"
    name = "RanobeLIB"
    placeholder = "https://ranobelib.me/ru/book/12345--nazvanie"
    hint = ("Ссылка на книгу или её слаг. Книга уже по-русски: "
            "переводить после скачивания не нужно.")
    #: API открыт и отвечает напрямую. Прокси не мешает, но и не нужен.
    needs_proxy = False

    def find(self, client, query: str) -> Novel:
        slug = slug_of(query)
        params = [("fields[]", field) for field in FIELDS]
        try:
            answer = client.get(f"{API}/{slug}", params=params, headers=HEADERS)
        except HttpError as exc:
            if exc.status == 404:
                raise SourceBroken(f"Книги «{slug}» на RanobeLIB нет") from exc
            raise

        book = _data(answer)
        if not isinstance(book, dict):
            raise SourceBroken("Карточка книги пришла не объектом")

        name = (book.get("rus_name") or book.get("name")
                or book.get("eng_name") or slug)
        authors = [str(one.get("name") or "") for one in book.get("authors") or []
                   if isinstance(one, dict)]

        return Novel(
            # Кода у книги нет, а число нужно: берём id, он у API целый.
            code=int(book.get("id") or 0),
            name=str(name),
            slug=str(book.get("slug_url") or slug),
            # Сколько глав — узнаем из оглавления, отдельного поля нет.
            total_chapters=0,
            author=", ".join(one for one in authors if one),
            status=str((book.get("status") or {}).get("label") or ""),
            language="ru",
            cover=str((book.get("cover") or {}).get("default") or ""),
        )

    def toc(self, client, novel: Novel, first: int = 1, last: int | None = None,
            on_progress=None) -> Toc:
        slug = novel.slug or str(novel.code)
        answer = client.get(f"{API}/{slug}/chapters", headers=HEADERS)
        entries = _data(answer)
        if not isinstance(entries, list):
            raise SourceBroken("Оглавление пришло не списком")

        chapters: list[Chapter] = []
        for index, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                continue
            if index < first or (last is not None and index > last):
                continue
            volume = str(entry.get("volume") or "")
            number = str(entry.get("number") or "")
            chapters.append(Chapter(
                number=index,
                # Своего номера у главы нет: том и номер внутри тома —
                # вот по чему API её отдаёт. Складываем их в один ключ,
                # чтобы качалка носила его как обычный идентификатор.
                post_id=f"{slug}|{volume}|{number}|{_branch(entry)}",
                ch_name=str(entry.get("name") or "").strip(),
                link=f"{SITE}/ru/book/{slug}/read/v{volume}/c{number}",
            ))
            if on_progress:
                on_progress(len(chapters), len(entries))

        return Toc(chapters=chapters, missing=[])

    def chapter(self, client, chapter: Chapter) -> tuple[str, str]:
        parts = str(chapter.post_id or "").split("|")
        if len(parts) != 4:
            raise SourceBroken(
                f"Глава {chapter.number} без адреса — оглавление читалось "
                "другой версией программы, соберите его заново")
        slug, volume, number, branch = parts

        params = {"volume": volume, "number": number}
        if branch:
            params["branch_id"] = branch
        answer = client.get(f"{API}/{slug}/chapter", params=params,
                            headers=HEADERS)

        body = _data(answer)
        if not isinstance(body, dict):
            raise SourceBroken(f"Глава {chapter.number} пришла не объектом")

        lines = paragraphs_of(body.get("content"))
        title = chapter.ch_name or str(body.get("name") or "").strip()
        return title, "\n\n".join(lines)
