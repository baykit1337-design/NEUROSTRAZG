"""Чтение .odt: ZIP-архив, текст лежит в content.xml."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .base import ReadError, Reader

TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"


class OdtReader(Reader):
    suffixes = (".odt",)

    def paragraphs(self, path: Path) -> list[str]:
        try:
            with zipfile.ZipFile(path) as archive:
                content = archive.read("content.xml")
        except (zipfile.BadZipFile, KeyError, OSError) as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc

        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise ReadError(f"content.xml не разобрался: {exc}") from exc

        paragraphs = []
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag not in ("p", "h"):
                continue
            text = "".join(element.itertext()).strip()
            if text:
                paragraphs.append(text)
        return paragraphs
