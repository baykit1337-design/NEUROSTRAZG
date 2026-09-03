"""Чтение .epub.

Epub — это ZIP-архив, а не текст: открывать его как файл нельзя, иначе в
обработку летят сырые байты. Разбор берём из обкатанного `split_book`.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..models import Chapter
from ..naming import parse_title
from .base import ReadError, Reader, split_paragraphs

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class EpubReader(Reader):
    suffixes = (".epub",)
    multi_chapter = True

    def read(self, path: Path) -> list[Chapter]:
        import split_book

        try:
            raw = split_book.epub_chapters(path)
        except SystemExit as exc:
            # split_book при неудаче кидает SystemExit — в сервере это
            # недопустимо, переводим в обычное исключение.
            raise ReadError(str(exc) or "не удалось разобрать epub") from exc
        except Exception as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc

        from ..text import strip_leading_title

        chapters = []
        for title, text in raw:
            # Разбор заголовка, а не имени файла: в заголовке цифра чаще
            # всего часть названия, и «Act 3 is about to begin.» третьей
            # главой не является. Нет номера — и не надо: порядок глав в
            # епабе задан корешком, и выдумывать числа не за чем.
            name = parse_title(title)
            # Название нередко стоит и в тексте — убираем общей функцией.
            paragraphs = strip_leading_title(split_paragraphs(text), title)
            chapters.append(
                Chapter(
                    number=name.number,
                    part=name.part,
                    title=title,
                    paragraphs=paragraphs,
                    source=str(path),
                )
            )
        return chapters

    def paragraphs(self, path: Path) -> list[str]:
        return [p for chapter in self.read(path) for p in chapter.paragraphs]
