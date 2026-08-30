"""Чтение .html через BeautifulSoup."""

from __future__ import annotations

import logging
from pathlib import Path

from .base import ReadError, Reader, split_paragraphs
from .txt import read_text

log = logging.getLogger(__name__)


class HtmlReader(Reader):
    suffixes = (".html", ".htm", ".xhtml")

    def paragraphs(self, path: Path) -> list[str]:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise ReadError("Для .html нужен beautifulsoup4") from exc

        try:
            soup = BeautifulSoup(read_text(path), "html.parser")
        except Exception as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc

        # Скрипты и стили — не текст книги.
        for junk in soup(["script", "style", "noscript"]):
            junk.decompose()

        # Идём по телу подряд, а не выбираем теги по всему документу:
        # порядок абзацев обязан совпадать с порядком в файле, а текст,
        # который лежит в теле сам по себе, без обёртки, — это тоже абзац.
        #
        # Так пишет переводчик EPUB: у него часть строк обёрнута в `<p>`, а
        # часть стоит прямо в `<body>`. Выборка по тегам такие строки
        # молча теряла — глава приезжала с дырой посередине.
        body = soup.body or soup
        paragraphs = []
        for piece in body.children:
            name = getattr(piece, "name", None)
            if name is None:
                # Голый текст между тегами.
                text = str(piece).strip()
            elif name in ("p", "h1", "h2", "h3", "h4", "h5", "h6"):
                text = piece.get_text(" ", strip=True)
            elif name in ("div", "section", "article", "blockquote"):
                # Внутри может быть своя разметка — разбираем её отдельно,
                # иначе десяток абзацев слипся бы в один.
                inner = piece.find_all(["p", "h1", "h2", "h3", "h4"])
                if inner:
                    paragraphs.extend(
                        one.get_text(" ", strip=True) for one in inner)
                    continue
                text = piece.get_text(" ", strip=True)
            else:
                continue
            if text:
                paragraphs.append(text)

        paragraphs = [one for one in paragraphs if one]
        if not paragraphs:
            paragraphs = split_paragraphs(soup.get_text("\n", strip=True))
        return paragraphs

    def title_of(self, path: Path) -> str:
        """Название главы из `<title>`, если оно там есть.

        У переводчика EPUB имя файла — `ch0001_translated_gemini`, а
        настоящее название главы лежит в заголовке документа. Без этого
        книга собиралась с именами файлов вместо названий.
        """
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(read_text(path), "html.parser")
        except Exception as exc:  # noqa: BLE001 — нет названия, и ладно
            log.debug("Название из %s не прочиталось: %s", path, exc)
            return ""
        found = soup.title.get_text(" ", strip=True) if soup.title else ""
        return found
