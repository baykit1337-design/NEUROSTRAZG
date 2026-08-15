"""Расшифровка названий на страницах Фанкью (5.2 ТЗ NEUROSTRAZH).

Сайт подменяет часть иероглифов символами из служебной области Unicode и
рисует их своим шрифтом. Затронуты только три поля: название книги, автор
и описание. Всё остальное — числа, идентификаторы, ссылки — приходит
чистым, поэтому качать книги и следить за движением рейтинга можно и без
расшифровки.

Соответствие «служебный код → настоящий знак» лежит в самом шрифте, в
таблице `cmap`: имена глифов у этого шрифта заданы через кодовую точку
(`uni4E2D`), и по ним знак восстанавливается напрямую.

Таблица кэшируется по имени семейства. Имя меняется при обновлении шрифта,
и незнакомое имя — это сигнал скачать заново, а не повод сдаться.
"""

from __future__ import annotations

import logging
import re
import threading

log = logging.getLogger(__name__)

#: Служебная область Unicode, куда сайт уводит подменённые знаки.
PRIVATE_FROM = 0xE000
PRIVATE_TO = 0xF8FF

#: Имя семейства и адрес шрифта прямо в стилях страницы.
FAMILY = re.compile(r"font-family\s*:\s*['\"]?([\w-]+)['\"]?", re.I)
SOURCE = re.compile(r"url\(['\"]?(https?://[^)'\"]+\.(?:woff2?|otf|ttf))", re.I)

#: Имя глифа вида `uni4E2D` или `u4E2D` — из него и берётся знак.
GLYPH = re.compile(r"^uni?([0-9A-Fa-f]{4,6})$")

_LOCK = threading.Lock()
#: Разобранные таблицы по имени семейства.
_TABLES: dict[str, dict] = {}


class FontUnavailable(Exception):
    """Расшифровать нечем. Не поломка: рейтинг работает и без имён."""


def has_secret(text) -> bool:
    """Есть ли в строке подменённые знаки."""
    return any(PRIVATE_FROM <= ord(ch) <= PRIVATE_TO for ch in str(text or ""))


def font_of(css: str) -> tuple[str, str]:
    """Имя семейства и адрес файла из стилей страницы."""
    family = FAMILY.search(css or "")
    source = SOURCE.search(css or "")
    return (family.group(1) if family else "",
            source.group(1) if source else "")


def _from_font(data: bytes) -> dict:
    """Таблица подстановки из файла шрифта."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError as exc:
        raise FontUnavailable(
            "Расшифровка названий требует пакета fonttools: "
            "pip install fonttools") from exc

    import io

    try:
        font = TTFont(io.BytesIO(data), lazy=True)
        cmap = font.getBestCmap()
    except Exception as exc:  # noqa: BLE001 — причину показываем целиком
        raise FontUnavailable(f"Шрифт не разобрался: {exc}") from exc

    table = {}
    for code, glyph in cmap.items():
        if not (PRIVATE_FROM <= code <= PRIVATE_TO):
            continue
        found = GLYPH.match(str(glyph))
        if found:
            table[chr(code)] = chr(int(found.group(1), 16))
    return table


def table_for(family: str, data: bytes | None = None) -> dict:
    """Готовая таблица по имени семейства.

    Уже разобранный шрифт второй раз не качается и не разбирается: на
    странице рейтинга сто книг, и делать это на каждую было бы расточительно.
    """
    family = str(family or "")
    with _LOCK:
        found = _TABLES.get(family)
    if found is not None:
        return found

    if not data:
        raise FontUnavailable(f"Шрифт «{family}» ещё не скачан")

    table = _from_font(data)
    with _LOCK:
        _TABLES[family] = table
    log.info("Шрифт «%s»: разобрано подстановок %s", family, len(table))
    return table


def known(family: str) -> bool:
    with _LOCK:
        return str(family or "") in _TABLES


def decode(text, table: dict | None) -> str:
    """Возвращает строку с восстановленными знаками.

    Знак, которого нет в таблице, остаётся как есть: показать строку с
    одним пропуском лучше, чем не показать вовсе.
    """
    text = str(text or "")
    if not table or not has_secret(text):
        return text
    return "".join(table.get(ch, ch) for ch in text)


def forget() -> None:
    with _LOCK:
        _TABLES.clear()
