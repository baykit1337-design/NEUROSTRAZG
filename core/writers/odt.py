"""Запись .odt — минимальный, но корректный OpenDocument."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from ..models import Chapter
from ..text import prepare
from .base import WriteError, Writer

MIMETYPE = "application/vnd.oasis.opendocument.text"

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
                   manifest:version="1.2">
 <manifest:file-entry manifest:full-path="/" manifest:media-type="{mime}"/>
 <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""

CONTENT = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  office:version="1.2">
 <office:body><office:text>{body}</office:text></office:body>
</office:document-content>"""


class OdtWriter(Writer):
    suffix = ".odt"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        prep = options.get("prep")
        heading = options.get("headings", True)
        separator = options.get("separator", "")

        parts = []
        for index, chapter in enumerate(chapters):
            if index and separator:
                parts.append(f"<text:p>{escape(separator)}</text:p>")
            if heading and chapter.title:
                parts.append(
                    f'<text:h text:outline-level="1">{escape(chapter.title)}</text:h>'
                )
            for block in prepare(chapter.paragraphs, chapter.title, prep):
                parts.append(f"<text:p>{escape(block.text)}</text:p>")

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                # mimetype обязан идти первым и без сжатия.
                archive.writestr(
                    zipfile.ZipInfo("mimetype"), MIMETYPE, zipfile.ZIP_STORED
                )
                archive.writestr("META-INF/manifest.xml", MANIFEST.format(mime=MIMETYPE))
                archive.writestr("content.xml", CONTENT.format(body="".join(parts)))
        except OSError as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
