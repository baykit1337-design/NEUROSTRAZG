"""Чтение .html через BeautifulSoup."""

from __future__ import annotations

from pathlib import Path

from .base import ReadError, Reader, split_paragraphs
from .txt import read_text


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

        blocks = soup.find_all(["p", "h1", "h2", "h3", "h4", "div"])
        paragraphs = []
        for block in blocks:
            # У вложенных div текст уже собран родителем — берём только те,
            # внутри которых нет других блоков.
            if block.name == "div" and block.find(["p", "div"]):
                continue
            text = block.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)

        if not paragraphs:
            paragraphs = split_paragraphs(soup.get_text("\n", strip=True))
        return paragraphs
