"""Чтение .txt с автоопределением кодировки."""

from __future__ import annotations

from pathlib import Path

from .base import ReadError, Reader, split_paragraphs

#: Кодировки, которые пробуем по очереди, если определить не вышло.
#:
#: Порядок здесь и есть весь смысл, а не список.
#:
#: `cp1251` раскодирует почти любые байты и потому забирает себе всё, до
#: чего дотянется. Китайский файл он забирал первым и превращал в бодрую
#: кириллическую кашу вида «ЎєОЧК¦Ч·ЦрЧЕХжАн» — молча, без единой
#: ошибки. Поэтому `gb18030` идёт раньше него.
#:
#: Обратной беды при этом нет: русский текст в cp1251 на `gb18030`
#: честно падает («illegal multibyte sequence») и спокойно доходит до
#: своей кодировки. Проверено на живых текстах, см. тесты.
FALLBACKS = ("utf-8", "gb18030", "cp1251", "utf-16")

#: Доля иероглифов, ниже которой удачный разбор в `gb18030` считаем
#: совпадением, а не китайским текстом.
CJK_SHARE = 0.1

#: И сколько их должно быть штук. Одной доли мало: русское «Да» в cp1251
#: это два байта, а два байта — ровно один годный иероглиф, и доля у
#: него выходит стопроцентная. На короткой строке отличить китайский от
#: совпадения нельзя вовсе, поэтому ниже этой границы остаёмся при
#: прежнем поведении — так надёжнее: коротких русских файлов много,
#: коротких китайских почти нет.
CJK_LEAST = 8


def _chinese(text: str) -> bool:
    """Похож ли разбор на китайский текст, а не на удачное совпадение."""
    if not text:
        return False
    hits = sum(1 for one in text if "㐀" <= one <= "鿿")
    return hits >= CJK_LEAST and hits >= len(text) * CJK_SHARE


def read_text(path: Path) -> str:
    """Текст файла с угадыванием кодировки.

    Русские тексты приходят и в UTF-8, и в CP1251, китайские — в GBK;
    читать вслепую нельзя, получится мусор вместо букв. Причём мусор
    тихий: неверная кодировка чаще всего не роняет чтение, а подменяет
    буквы, и заметить это можно только глазами.
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
            got = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if encoding == "gb18030" and not _chinese(got):
            # Разобралось, но иероглифов нет: значит это не китайский
            # текст, а совпадение. Пропускаем — своя кодировка ниже.
            continue
        return got
    return raw.decode("utf-8", errors="replace")


class TxtReader(Reader):
    suffixes = (".txt",)

    def paragraphs(self, path: Path) -> list[str]:
        try:
            return split_paragraphs(read_text(path))
        except OSError as exc:
            raise ReadError(f"{type(exc).__name__}: {exc}") from exc
