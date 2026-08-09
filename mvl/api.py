"""Работа с REST API сайта: каталог, оглавление, текст главы."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .client import API, BASE, Client, HttpError

log = logging.getLogger(__name__)

NOVEL_FIELDS = "name,slug,novel-code,total-chapters,read-link,author-name,status,language"
TOC_BATCH = 100  # per_page для posts, максимум по ТЗ — 500
CATALOG_PER_PAGE = 15000

# Рекламные блоки прячутся за обфусцированными классами: ke400008d2, rb9bdb230d.
OBFUSCATED_CLASS = re.compile(r"^[a-z]{2,3}[0-9a-f]{7,}$")


@dataclass
class Novel:
    code: int
    name: str
    slug: str
    total_chapters: int
    author: str = ""
    status: str = ""
    language: str = ""

    @property
    def read_link(self) -> str:
        return f"{BASE}/chapter/{self.code}-1"

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "slug": self.slug,
            "total_chapters": self.total_chapters,
            "author": self.author,
            "status": self.status,
            "language": self.language,
        }


@dataclass
class Chapter:
    number: int
    post_id: int | None = None
    ch_name: str = ""
    link: str = ""

    @property
    def title(self) -> str:
        return self.ch_name or f"Chapter {self.number}"


@dataclass
class Toc:
    chapters: list[Chapter] = field(default_factory=list)
    missing: list[int] = field(default_factory=list)


# ---------------------------------------------------------------- поиск книги


def parse_input(raw: str) -> tuple[str, str]:
    """Разбирает ввод пользователя.

    Возвращает ('code', '6615') либо ('slug', 'insect-tamers-ascension').
    Принимает URL витрины, URL главы, голый слаг или числовой код.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("Пустой запрос")

    if text.isdigit():
        return "code", text

    # https://chap.heliosarchive.online/chapter/6615-1 → код книги
    m = re.search(r"/chapter/(\d+)-\d+", text)
    if m:
        return "code", m.group(1)

    if "://" in text or text.startswith("www."):
        path = re.sub(r"^[a-z]+://", "", text).split("?", 1)[0].split("#", 1)[0]
        segments = [s for s in path.split("/")[1:] if s]
        if not segments:
            raise ValueError(f"Не удалось вытащить слаг из ссылки: {raw}")
        return "slug", segments[-1]

    return "slug", text.strip("/")


def slugify(value: str) -> str:
    """Название → слаг, чтобы сравнивать с вебфлоу-слагом."""
    value = value.lower().replace("&", " and ")
    value = re.sub(r"['’‘]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def _novel_from_json(item: dict) -> Novel | None:
    code = item.get("novel-code")
    try:
        code = int(str(code).strip())
    except (TypeError, ValueError):
        return None
    try:
        total = int(str(item.get("total-chapters") or 0).strip())
    except (TypeError, ValueError):
        total = 0
    return Novel(
        code=code,
        name=(item.get("name") or "").strip() or f"novel-{code}",
        slug=(item.get("slug") or "").strip(),
        total_chapters=total,
        author=(item.get("author-name") or "").strip(),
        status=(item.get("status") or "").strip(),
        language=(item.get("language") or "").strip(),
    )


def search_novels(client: Client, query: str, limit: int = 20) -> list[Novel]:
    """Поиск по каталогу через ?search=."""
    data = client.get_json(
        "/mvl-novels",
        {"search": query, "per_page": min(limit, 100), "_fields": NOVEL_FIELDS},
    )
    if not isinstance(data, list):
        return []
    novels = [n for n in (_novel_from_json(i) for i in data) if n]
    return novels[:limit]


def find_novel(client: Client, raw_input: str) -> Novel:
    """Находит книгу по ссылке, слагу или коду.

    Параметр ?slug= на этом эндпоинте не работает (внутренний WP-слаг не
    совпадает с вебфлоу-слагом), поэтому ищем через ?search= и сверяем
    слагифицированное название.
    """
    kind, value = parse_input(raw_input)

    if kind == "code":
        novel = get_novel_by_code(client, int(value))
        if novel:
            return novel
        raise LookupError(f"Книга с кодом {value} не найдена в каталоге")

    words = value.replace("-", " ").strip()
    candidates = search_novels(client, words, limit=50)

    target = slugify(value)
    for novel in candidates:
        if slugify(novel.name) == target or novel.slug == value:
            return novel

    # Иногда слаг витрины короче названия — берём лучшее частичное совпадение.
    for novel in candidates:
        name_slug = slugify(novel.name)
        if target in name_slug or name_slug in target:
            return novel

    if candidates:
        raise LookupError(
            f"Точного совпадения для '{value}' нет. Похожие: "
            + ", ".join(f"{n.name} ({n.code})" for n in candidates[:5])
        )
    raise LookupError(f"По запросу '{words}' в каталоге ничего не найдено")


def get_novel_by_code(client: Client, code: int) -> Novel | None:
    """Ищет книгу по числовому коду. Поиск по коду в ?search= работает не
    всегда, поэтому при промахе выкачиваем каталог целиком."""
    data = client.get_json(
        "/mvl-novels", {"search": str(code), "per_page": 100, "_fields": NOVEL_FIELDS}
    )
    if isinstance(data, list):
        for item in data:
            novel = _novel_from_json(item)
            if novel and novel.code == code:
                return novel

    for novel in fetch_catalog(client):
        if novel.code == code:
            return novel
    return None


def fetch_catalog(client: Client, per_page: int = CATALOG_PER_PAGE) -> list[Novel]:
    """Весь каталог одним запросом (поля обрезаны, чтобы не тянуть синопсисы)."""
    data = client.get_json("/mvl-novels", {"per_page": per_page, "_fields": NOVEL_FIELDS})
    if not isinstance(data, list):
        return []
    return [n for n in (_novel_from_json(i) for i in data) if n]


# ------------------------------------------------------------------ оглавление


def fetch_toc(
    client: Client,
    novel: Novel,
    first: int = 1,
    last: int | None = None,
    on_progress=None,
) -> Toc:
    """Собирает оглавление пачками по TOC_BATCH слагов вида {code}-{n}."""
    from .client import polite_pause

    last = last or novel.total_chapters
    if last < first:
        raise ValueError(f"Диапазон глав пуст: {first}..{last}")

    numbers = list(range(first, last + 1))
    found: dict[int, Chapter] = {}
    batches = [numbers[i : i + TOC_BATCH] for i in range(0, len(numbers), TOC_BATCH)]

    for index, batch in enumerate(batches):
        slugs = [f"{novel.code}-{n}" for n in batch]
        data = client.get_json(
            "/posts",
            [("slug[]", s) for s in slugs]
            + [("per_page", TOC_BATCH), ("_fields", "id,link,slug,acf")],
        )
        for item in data if isinstance(data, list) else []:
            chapter = _chapter_from_post(item, novel.code)
            if chapter and chapter.number in numbers:
                found[chapter.number] = chapter

        if on_progress:
            on_progress(min((index + 1) * TOC_BATCH, len(numbers)), len(numbers))
        if index < len(batches) - 1:
            polite_pause()

    chapters = [found[n] for n in numbers if n in found]
    missing = [n for n in numbers if n not in found]
    if missing:
        log.warning("Дыры в нумерации: %s глав отсутствует в каталоге", len(missing))
    return Toc(chapters=chapters, missing=missing)


def _chapter_from_post(item: dict, novel_code: int) -> Chapter | None:
    acf = item.get("acf") or {}
    number = acf.get("chapter_number")

    if number is None:
        # Запасной вариант: номер из слага {code}-{n}.
        m = re.match(rf"^{novel_code}-(\d+)$", str(item.get("slug") or ""))
        if m:
            number = m.group(1)
    try:
        number = int(str(number).strip())
    except (TypeError, ValueError):
        return None

    return Chapter(
        number=number,
        post_id=item.get("id"),
        ch_name=str(acf.get("ch_name") or "").strip(),
        link=item.get("link") or f"{BASE}/chapter/{novel_code}-{number}",
    )


# ---------------------------------------------------------------- текст главы

MODE_REST = "rest"
MODE_HTML = "html"


def probe_content_mode(client: Client, chapter: Chapter) -> str:
    """Проверяет, отдаёт ли REST тело главы.

    Если content.rendered непустой — берём текст из JSON (самый дешёвый путь
    по трафику). Иначе парсим HTML страницы главы.
    """
    if not chapter.post_id:
        return MODE_HTML
    try:
        data = client.get_json(f"/posts/{chapter.post_id}", {"_fields": "content,title"})
    except HttpError as exc:
        log.debug("Проба REST не удалась (%s), переключаемся на HTML", exc)
        return MODE_HTML

    rendered = ((data or {}).get("content") or {}).get("rendered") or ""
    if extract_paragraphs(rendered):
        return MODE_REST
    return MODE_HTML


def fetch_chapter(client: Client, chapter: Chapter, mode: str) -> tuple[str, str]:
    """Возвращает (заголовок, текст) одной главы."""
    if mode == MODE_REST and chapter.post_id:
        data = client.get_json(f"/posts/{chapter.post_id}", {"_fields": "content,title"})
        rendered = ((data or {}).get("content") or {}).get("rendered") or ""
        paragraphs = extract_paragraphs(rendered)
        if paragraphs:
            title = chapter.ch_name or _html_to_text(
                ((data or {}).get("title") or {}).get("rendered") or ""
            )
            return title or chapter.title, "\n\n".join(paragraphs)
        log.debug("Глава %s: REST отдал пусто, пробуем HTML", chapter.number)

    html = client.get_text(chapter.link or f"{BASE}/chapter/{chapter.number}")
    return parse_chapter_page(html, fallback_title=chapter.title)


# ------------------------------------------------------------------- парсинг


def _soup(html: str):
    from bs4 import BeautifulSoup

    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    return _clean_text(_soup(html).get_text(" ", strip=True))


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("​", "")
    return re.sub(r"[ \t]+", " ", text).strip()


def _is_ad(tag) -> bool:
    """Блок с обфусцированным классом (ke400008d2, rb9bdb230d) — это реклама."""
    classes = tag.get("class") or []
    return any(OBFUSCATED_CLASS.match(c) for c in classes)


def _paragraph_text(tag) -> str | None:
    """Текст абзаца, либо None если абзац выбрасывается."""
    if _is_ad(tag) or any(_is_ad(parent) for parent in tag.parents if parent.name):
        return None

    text = _clean_text(tag.get_text(" ", strip=True))
    if not text:
        return None

    # Абзацы из одних звёздочек — разделители сцен, сохраняем как есть.
    if set(text.replace(" ", "")) == {"*"}:
        return text
    return text


def extract_paragraphs(html: str) -> list[str]:
    """Достаёт абзацы из HTML-фрагмента (тело главы)."""
    if not html or not html.strip():
        return []

    root = _soup(html)
    paragraphs = []
    for tag in root.find_all("p"):
        text = _paragraph_text(tag)
        if text:
            paragraphs.append(text)

    if not paragraphs:
        # Бывает, что текст лежит без <p>, разделённый <br>.
        for br in root.find_all("br"):
            br.replace_with("\n")
        for line in root.get_text("\n").split("\n"):
            line = _clean_text(line)
            if line:
                paragraphs.append(line)
    return paragraphs


def parse_chapter_page(html: str, fallback_title: str = "") -> tuple[str, str]:
    """Парсит страницу главы (Oxygen builder, id стабильные).

    h1#novel-name — название новеллы, h2#chapter-name — название главы,
    div#chapter → дочерние p — текст. На динамические span id не завязываемся.
    """
    root = _soup(html)

    title_tag = root.find(id="chapter-name")
    title = _clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""

    body = root.find(id="chapter")
    if body is None:
        raise ValueError("На странице нет блока #chapter — разметка изменилась?")

    paragraphs = []
    for tag in body.find_all("p"):
        text = _paragraph_text(tag)
        if text:
            paragraphs.append(text)

    if not paragraphs:
        raise ValueError("Блок #chapter пуст — текст главы не найден")

    return title or fallback_title, "\n\n".join(paragraphs)


def parse_nav_links(html: str) -> tuple[str | None, str | None]:
    """Ссылки на предыдущую и следующую главу (a#prev-top / a#next-top)."""
    root = _soup(html)

    def href(node_id: str) -> str | None:
        tag = root.find(id=node_id)
        if tag is None:
            return None
        value = tag.get("href")
        return value.strip() if value else None

    return href("prev-top"), href("next-top")


def chapter_number_from_link(link: str, novel_code: int) -> int | None:
    m = re.search(rf"/chapter/{novel_code}-(\d+)", link or "")
    return int(m.group(1)) if m else None


def batched(items: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


__all__ = [
    "API",
    "BASE",
    "Chapter",
    "Novel",
    "Toc",
    "MODE_HTML",
    "MODE_REST",
    "batched",
    "chapter_number_from_link",
    "extract_paragraphs",
    "fetch_catalog",
    "fetch_chapter",
    "fetch_toc",
    "find_novel",
    "get_novel_by_code",
    "parse_chapter_page",
    "parse_input",
    "parse_nav_links",
    "probe_content_mode",
    "search_novels",
    "slugify",
]
