"""Чтение .fb2: XML, главы по <section>, заголовки по <title>."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from ..models import Chapter
from ..naming import parse
from .base import ReadError, Reader


def _strip_ns(tag: str) -> str:
    """`{namespace}section` → `section`."""
    return tag.rsplit("}", 1)[-1]


def _text_of(node) -> list[str]:
    """Абзацы внутри узла: каждый <p> — свой абзац.

    Абзацы из <title> пропускаем: это заголовок главы, он живёт отдельно.
    Иначе при чтении собственной записи название задваивалось бы.
    """
    in_title = set()
    for child in node.iter():
        if _strip_ns(child.tag) == "title":
            in_title.update(id(p) for p in child.iter())

    paragraphs = []
    for element in node.iter():
        if _strip_ns(element.tag) != "p" or id(element) in in_title:
            continue
        text = "".join(element.itertext()).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _title_of(node) -> str:
    for child in node:
        if _strip_ns(child.tag) == "title":
            return " ".join("".join(child.itertext()).split())
    return ""


class Fb2Reader(Reader):
    suffixes = (".fb2",)
    multi_chapter = True

    def read(self, path: Path) -> list[Chapter]:
        try:
            tree = ElementTree.parse(str(path))
        except (ElementTree.ParseError, OSError) as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc

        root = tree.getroot()
        body = None
        for element in root.iter():
            if _strip_ns(element.tag) == "body":
                body = element
                break
        if body is None:
            raise ReadError("в файле нет <body>")

        sections = [e for e in body.iter() if _strip_ns(e.tag) == "section"]
        if not sections:
            sections = [body]

        chapters = []
        for section in sections:
            title = _title_of(section)
            paragraphs = _text_of(section)
            if not paragraphs:
                continue
            name = parse(title)
            chapters.append(
                Chapter(
                    number=name.number, part=name.part, title=title,
                    paragraphs=paragraphs, source=str(path),
                )
            )
        if not chapters:
            raise ReadError("не нашлось ни одной главы")
        return chapters

    def paragraphs(self, path: Path) -> list[str]:
        return [p for chapter in self.read(path) for p in chapter.paragraphs]
