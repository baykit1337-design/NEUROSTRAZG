"""Чтение .txt с автоопределением кодировки."""

from __future__ import annotations

from pathlib import Path

from .base import ReadError, Reader, split_paragraphs

#: Кодировки, которые пробуем по очереди, если определить не вышло.
FALLBACKS = ("utf-8", "cp1251", "utf-16")


def read_text(path: Path) -> str:
    """Текст файла с угадыванием кодировки.

    Русские тексты приходят и в UTF-8, и в CP1251; читать вслепую нельзя —
    получится мусор вместо букв.
    """
    raw = path.read_bytes()
    if not raw:
        return ""

    # BOM говорит о кодировке однозначно — с него и начинаем.
    for bom, encoding in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    ):
        if raw.startswith(bom):
            return raw.decode(encoding, errors="replace")

    try:
        import chardet

        guess = chardet.detect(raw[:100_000])
        if guess.get("encoding") and (guess.get("confidence") or 0) > 0.7:
            return raw.decode(guess["encoding"], errors="replace")
    except ImportError:
        pass

    for encoding in FALLBACKS:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


class TxtReader(Reader):
    suffixes = (".txt",)

    def paragraphs(self, path: Path) -> list[str]:
        try:
            return split_paragraphs(read_text(path))
        except OSError as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc
