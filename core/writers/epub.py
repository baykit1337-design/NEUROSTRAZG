"""Запись .epub с корректным OPF, чтобы файл открывался в читалках.

Порядок чтения задаётся spine — именно он определяет, в каком порядке
читалка листает главы, а не порядок файлов в архиве.
"""

from __future__ import annotations

import uuid
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from ..models import Chapter
from ..text import prepare
from .base import WriteError, Writer

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
           xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

CHAPTER_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head>
<meta charset="utf-8"/><title>{title}</title></head>
<body>{body}</body></html>"""

OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:{uid}</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>ru</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
{items}
  </manifest>
  <spine>
{spine}
  </spine>
</package>"""

NAV = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"><head>
<meta charset="utf-8"/><title>Оглавление</title></head>
<body><nav epub:type="toc"><ol>{items}</ol></nav></body></html>"""


class EpubWriter(Writer):
    suffix = ".epub"

    def write(self, path: Path, chapters: list[Chapter], **options) -> None:
        prep = options.get("prep")
        heading = options.get("headings", True)
        title = options.get("title") or path.stem
        author = options.get("author") or ""

        pages, items, spine, nav_items = [], [], [], []
        for index, chapter in enumerate(chapters, 1):
            name = f"ch{index:04d}.xhtml"
            parts = []
            if heading and chapter.title:
                parts.append(f"<h1>{escape(chapter.title)}</h1>")
            for block in prepare(chapter.paragraphs, chapter.title, prep):
                parts.append(f"<p>{escape(block.text)}</p>")

            pages.append((name, CHAPTER_PAGE.format(
                title=escape(chapter.title or name), body="".join(parts))))
            items.append(
                f'    <item id="c{index}" href="{name}" '
                f'media-type="application/xhtml+xml"/>'
            )
            # Порядок чтения задаёт spine.
            spine.append(f'    <itemref idref="c{index}"/>')
            nav_items.append(
                f'<li><a href="{name}">{escape(chapter.title or name)}</a></li>'
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                # mimetype обязан идти первым и без сжатия.
                archive.writestr(
                    zipfile.ZipInfo("mimetype"),
                    "application/epub+zip",
                    zipfile.ZIP_STORED,
                )
                archive.writestr("META-INF/container.xml", CONTAINER)
                for name, body in pages:
                    archive.writestr(f"OEBPS/{name}", body)
                archive.writestr("OEBPS/nav.xhtml", NAV.format(items="".join(nav_items)))
                archive.writestr("OEBPS/content.opf", OPF.format(
                    uid=uuid.uuid4(), title=escape(title), author=escape(author),
                    items="\n".join(items), spine="\n".join(spine),
                ))
        except OSError as exc:
            raise WriteError(f"{type(exc).__name__}: {exc}") from exc
