"""Сколько программа скачала: за этот запуск и за месяц.

При лимитном пакете это первое, что хочется видеть, а узнать было
неоткуда: страницы, главы, обложки и обновления уходили в один общий
поток, о котором никто не отчитывался.

Считается здесь, в самом низу: через это место проходят и главы, и
рейтинги, и модель. Ставить счётчик выше пришлось бы в трёх разных
местах, и они бы разошлись.

Файл появляется только тогда, когда его назвали через `setup`. Без него
счётчик живёт в памяти и умирает вместе с программой — так он ведёт себя
в тестах и в командной строке, где месячный итог никому не нужен.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

#: Куда писать месячный итог. `None` — только в память.
FILE: Path | None = None

#: На диск пишем не после каждой главы: сотня килобайт роли не играет, а
#: запись на каждый ответ — это тысячи записей за прогон.
SAVE_EVERY = 256 * 1024

_LOCK = threading.Lock()
_SESSION = 0
_MONTH = ""
_MONTH_BYTES = 0
_UNSAVED = 0

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря")


def _now() -> str:
    return datetime.now().strftime("%Y-%m")


def _month_name(stamp: str) -> str:
    """«2026-08» → «август 2026». Для подписи, а не для сравнения."""
    try:
        year, month = stamp.split("-")
        return f"{MONTHS[int(month) - 1][:-1]} {year}"
    except (ValueError, IndexError):
        return stamp


def setup(path) -> None:
    """Назвать файл и поднять из него месячный итог."""
    global FILE, _MONTH, _MONTH_BYTES, _UNSAVED
    with _LOCK:
        FILE = Path(path)
        _MONTH, _MONTH_BYTES, _UNSAVED = _now(), 0, 0
        try:
            data = json.loads(FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        # Месяц сменился — прошлый итог не наш.
        if isinstance(data, dict) and str(data.get("month") or "") == _MONTH:
            _MONTH_BYTES = max(0, int(data.get("bytes") or 0))


def _save() -> None:
    """Записать итог. Звать под `_LOCK`."""
    if FILE is None:
        return
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(
            json.dumps({"month": _MONTH, "bytes": _MONTH_BYTES},
                       ensure_ascii=False),
            encoding="utf-8")
    except OSError as exc:
        # Счётчик полезен, но не настолько, чтобы ронять скачивание.
        log.warning("Не удалось записать счётчик трафика: %s", exc)


def note(size: int) -> None:
    """Прибавить скачанное."""
    global _SESSION, _MONTH, _MONTH_BYTES, _UNSAVED
    size = int(size or 0)
    if size <= 0:
        return
    with _LOCK:
        now = _now()
        if now != _MONTH:
            _MONTH, _MONTH_BYTES, _UNSAVED = now, 0, 0
        _SESSION += size
        _MONTH_BYTES += size
        _UNSAVED += size
        if _UNSAVED >= SAVE_EVERY:
            _UNSAVED = 0
            _save()


def flush() -> None:
    """Записать несохранённое — при закрытии программы."""
    global _UNSAVED
    with _LOCK:
        if _UNSAVED:
            _UNSAVED = 0
            _save()


def totals() -> dict:
    """Итоги для интерфейса."""
    with _LOCK:
        return {"session": _SESSION, "month": _MONTH_BYTES,
                "month_name": _month_name(_MONTH or _now()),
                "kept": FILE is not None}


def forget() -> None:
    """Обнулить счётчик. Нужно тестам и кнопке «начать заново»."""
    global _SESSION, _MONTH, _MONTH_BYTES, _UNSAVED
    with _LOCK:
        _SESSION = _MONTH_BYTES = _UNSAVED = 0
        _MONTH = _now()
        _save()


__all__ = ["FILE", "flush", "forget", "note", "setup", "totals"]
