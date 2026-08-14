"""Счётчик входящего трафика — для нижней строки состояния (6.10).

Скорость нужна, чтобы отличить «медленно, но идёт» от «висит». По числу
скачанных глав этого не видно: одна глава может тянуться минуту, и на
экране всё это время ничего не меняется.

Считаются только полученные тела ответов: заголовки и служебный обмен
измерять бессмысленно, а точность до байта здесь никому не нужна.
"""

from __future__ import annotations

import threading
import time

#: Сколько секунд помнить для расчёта скорости. Меньше — цифра прыгает,
#: больше — не поспевает за обрывом связи.
WINDOW = 5.0

_LOCK = threading.Lock()
#: Пары (когда, сколько). Старое выбрасывается при каждом обращении.
_SAMPLES: list[tuple[float, int]] = []
_TOTAL = 0


def add(size: int) -> None:
    """Отмечает полученные байты. Зовётся из любого потока качалки."""
    if size <= 0:
        return
    global _TOTAL
    now = time.monotonic()
    with _LOCK:
        _TOTAL += size
        _SAMPLES.append((now, size))
        _trim(now)


def _trim(now: float) -> None:
    """Выбрасывает всё, что старше окна. Вызывается под замком."""
    edge = now - WINDOW
    while _SAMPLES and _SAMPLES[0][0] < edge:
        _SAMPLES.pop(0)


def speed() -> float:
    """Байт в секунду за последние секунды. Тишина — ноль."""
    now = time.monotonic()
    with _LOCK:
        _trim(now)
        if not _SAMPLES:
            return 0.0
        got = sum(size for _, size in _SAMPLES)
        # Делим на всё окно, а не на промежуток между первым и последним
        # замером: иначе один запрос в конце окна давал бы бесконечность.
        return got / WINDOW


def total() -> int:
    with _LOCK:
        return _TOTAL


def reset() -> None:
    """Обнуляет счётчик — перед новой операцией."""
    global _TOTAL
    with _LOCK:
        _TOTAL = 0
        _SAMPLES.clear()


def state() -> dict:
    return {"speed": round(speed()), "total": total()}
