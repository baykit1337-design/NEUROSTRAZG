"""Построчный журнал работы под прогресс-баром (7.7 ТЗ NEUROSTRAZH).

Прогресс-бар отвечает «сколько», а на вопрос «что именно сейчас
происходит» ответа не было вовсе: почему встало, по какому ключу шёл
запрос, была ли глава повторена. При работе на час это единственный
способ понять, что творится.

Журнал живёт в памяти задачи и не пишется на диск сам: строк много, а
ценность у них короткая. Кнопка «Сохранить лог» отдаёт то, что накопилось.
"""

from __future__ import annotations

import threading
from datetime import datetime

#: Сколько строк держать. Больше двухсот на экране всё равно не читают, а
#: на пятистах главах их набегает несколько тысяч.
KEEP = 200

STAMP = "%H:%M:%S"


class JobLog:
    """Кольцевой журнал одной задачи."""

    def __init__(self, keep: int = KEEP):
        self.keep = keep
        self._lines: list[dict] = []
        self._lock = threading.Lock()
        #: Сколько строк было всего — не только тех, что уместились.
        self.total = 0

    def add(self, text: str, kind: str = "info") -> None:
        if not str(text or "").strip():
            return
        with self._lock:
            self.total += 1
            self._lines.append({
                "at": datetime.now().strftime(STAMP),
                "text": str(text).strip(),
                "kind": kind,
            })
            if len(self._lines) > self.keep:
                del self._lines[:-self.keep]

    def lines(self, since: int = 0) -> list[dict]:
        """Строки начиная с указанной. Интерфейс дозапрашивает хвост."""
        with self._lock:
            first = max(0, self.total - len(self._lines))
            start = max(0, since - first)
            return list(self._lines[start:])

    def as_text(self) -> str:
        with self._lock:
            return "\n".join(f"{line['at']}  {line['text']}"
                             for line in self._lines)

    def state(self, since: int = 0) -> dict:
        return {"lines": self.lines(since), "total": self.total}
