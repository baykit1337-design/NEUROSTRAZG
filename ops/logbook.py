"""Журнал программы в файл.

До сих пор всё уходило только в консоль. На Windows программу запускают
двойным щелчком, окно закрывается вместе с ней, и единственная строка,
по которой поломку можно было бы разобрать, пропадает навсегда. Именно
поэтому «в рейтинге Цидяня прочерки вместо чисел» висит без движения:
спросить, что написано в консоли, можно, а прочитать — нечего.

Файл один, растёт до предела и переезжает в `.1`, `.2` и так далее.
Пять файлов по два мегабайта — это неделя обычной работы и ноль забот о
том, что журнал съест диск.

Отдельно — сборка отчёта о проблеме. Отчёт человек отправляет наружу,
поэтому ключи и пароли из него вычищаются здесь, а не «не попадают туда
сами»: попадут, стоит однажды записать в журнал не ту строку.
"""

from __future__ import annotations

import logging
import logging.handlers
import platform
import re
import sys
from pathlib import Path

from .history import DATA_DIR

#: Куда пишем. Рядом с журналом операций и корзиной: одно место на всё,
#: что программа хранит о себе.
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "neurostrazh.log"

#: Предел одного файла и сколько старых держать.
MAX_BYTES = 2 * 1024 * 1024
KEEP = 5

#: Сколько последних строк класть в отчёт о проблеме. Больше не нужно:
#: поломка видна в конце, а не в позавчерашнем запуске.
TAIL_LINES = 300

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
WHEN = "%Y-%m-%d %H:%M:%S"

#: Что вычищать из отчёта. Ключ Gemini начинается с `AIza`, пароль
#: прокси стоит в адресе после имени. Оба узнаются по виду, и полагаться
#: на то, что «в журнал они и не попадают», нельзя: попадут.
SECRETS = (
    (re.compile(r"AIza[0-9A-Za-z_\-]{10,}"), "AIza…вырезано"),
    (re.compile(r"(?<=://)([^/\s:@]+):([^/\s@]+)@"), r"\1:…@"),
    (re.compile(r"(?i)\b(api[_-]?key|token|password|пароль)\b\s*[:=]\s*\S+"),
     r"\1: …вырезано"),
)

#: Уже подключались? Второй обработчик писал бы каждую строку дважды.
_started = False


def scrub(text: str) -> str:
    """Убирает из текста ключи и пароли.

    Отчёт уходит наружу — в переписку, в issue, куда угодно. Вырезаем по
    виду, а не по списку известных ключей: неизвестный ключ тоже ключ.

    Заодно прогоняем через `mvl.proxies.scrub`: он помнит пароли,
    прочитанные из файла прокси, и вычистит даже те, что по виду не
    отличить от обычного слова.
    """
    out = str(text or "")
    for rule, replace in SECRETS:
        out = rule.sub(replace, out)

    # Отложенный импорт: `ops` не тянет `mvl` при загрузке модуля.
    from mvl.proxies import scrub as forget_passwords

    return forget_passwords(out)


def start(level: int = logging.INFO) -> Path | None:
    """Подключает запись в файл ко всему, что программа пишет в журнал.

    Возвращает путь к файлу или `None`, если писать не вышло: программа
    без журнала работает, а вот падать из-за журнала не должна.
    """
    global _started
    if _started:
        return LOG_FILE

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=KEEP, encoding="utf-8")
    except OSError:
        return None

    handler.setFormatter(logging.Formatter(FORMAT, WHEN))
    handler.setLevel(level)
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > level:
        root.setLevel(level)
    _started = True
    return LOG_FILE


def tail(lines: int = TAIL_LINES) -> str:
    """Последние строки журнала.

    Файла может не быть вовсе — это не ошибка, а «ещё ничего не
    случилось».
    """
    if not LOG_FILE.is_file():
        return ""
    try:
        kept = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Журнал не читается: {exc}"
    return "\n".join(kept.splitlines()[-max(1, lines):])


def about() -> list[tuple[str, str]]:
    """Чем и где запущено. Половина вопросов снимается этими строками."""
    from mvl import __version__

    return [
        ("Программа", f"NEUROSTRAZH {__version__}"),
        ("Python", sys.version.split()[0]),
        ("Система", f"{platform.system()} {platform.release()}"),
        ("Папка данных", str(DATA_DIR)),
        ("Журнал", str(LOG_FILE) if LOG_FILE.is_file() else "ещё не заведён"),
    ]


def report(extra: str = "") -> str:
    """Отчёт о проблеме: чем запущено, что сказал человек, хвост журнала.

    Одна кнопка вместо переписки «пришлите строку из консоли» — тем
    более что консоли у человека может не быть вовсе.
    """
    parts = ["## Отчёт NEUROSTRAZH", ""]
    parts += [f"- {name}: {value}" for name, value in about()]
    if str(extra or "").strip():
        parts += ["", "## Что делали", "", str(extra).strip()]
    parts += ["", f"## Журнал, последние {TAIL_LINES} строк", "",
              "```", tail() or "(журнал пуст)", "```"]
    return scrub("\n".join(parts))
