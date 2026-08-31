"""Чтение .md — тот же текст, но разметка разбирается при выводе."""

from __future__ import annotations

import re
from pathlib import Path

from .base import ReadError, Reader, split_paragraphs
from .txt import read_text


class MarkdownReader(Reader):
    suffixes = (".md", ".markdown")

    def take_heading(self, paragraphs, path):
        """У markdown заголовок помечен решётками — снимаем их перед разбором."""
        if paragraphs:
            stripped = re.sub(r"^\s*#{1,6}\s+", "", paragraphs[0])
            if stripped != paragraphs[0]:
                return stripped.strip(), paragraphs[1:]
        return super().take_heading(paragraphs, path)

    def paragraphs(self, path: Path) -> list[str]:
        """Абзацы книги. У markdown абзац — строка, а не кусок между
        пустыми строками.

        Книги для загрузчика пишутся без пустых строк вовсе: пустая строка
        превращается на сайте в пустой абзац. По прежнему правилу такая
        книга читалась одним абзацем на весь файл — и «Разбить» честно
        сообщала «глав: 1», сколько бы их там ни было.

        Книгу с пустыми строками это правило читает так же: абзац там всё
        равно занимает одну строку. Проигрывает только текст, перенесённый
        по ширине окна, — но так книги здесь не пишет никто.
        """
        try:
            text = read_text(path)
        except OSError as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc
        found = [line.strip() for line in text.splitlines() if line.strip()]
        # Пустой файл `split_paragraphs` отдаёт пустым списком — сохраняем
        # это поведение, а не подсовываем список из одной пустой строки.
        return found or split_paragraphs(text)
