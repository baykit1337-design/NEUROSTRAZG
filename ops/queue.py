"""Очередь задач: несколько операций подряд, без участия человека.

Скачать главы 400–500 → разбить → переименовать → проверить → собрать в
один документ. Сейчас каждый шаг требует присутствия; с очередью
запускается на ночь.

Очередь только хранит и упорядочивает шаги. Что именно делает шаг, решает
слой выше: сюда передают, как его выполнить. Иначе очередь пришлось бы
править при каждой новой вкладке.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .history import DATA_DIR

log = logging.getLogger(__name__)

QUEUE_FILE = DATA_DIR / "queues.json"

#: Состояния шага.
WAITING = "waiting"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"


class QueueError(Exception):
    """С очередью что-то не так."""


@dataclass
class Step:
    """Один шаг: что делать и с какими параметрами."""

    kind: str = ""
    params: dict = field(default_factory=dict)
    title: str = ""
    state: str = WAITING
    message: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "params": self.params,
                "title": self.title or self.kind,
                "state": self.state, "message": self.message}

    @classmethod
    def from_dict(cls, data: dict) -> Step:
        return cls(
            kind=str((data or {}).get("kind") or ""),
            params=dict((data or {}).get("params") or {}),
            title=str((data or {}).get("title") or ""),
            state=str((data or {}).get("state") or WAITING),
            message=str((data or {}).get("message") or ""),
        )


@dataclass
class Queue:
    """Список шагов под именем — его можно запустить снова."""

    name: str = ""
    steps: list[Step] = field(default_factory=list)
    state: str = WAITING
    current: int = -1

    @property
    def done(self) -> int:
        return sum(1 for s in self.steps if s.state == DONE)

    def as_dict(self) -> dict:
        return {
            "name": self.name, "state": self.state, "current": self.current,
            "steps": [s.as_dict() for s in self.steps],
            "total": len(self.steps), "done": self.done,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Queue:
        return cls(
            name=str((data or {}).get("name") or ""),
            steps=[Step.from_dict(s) for s in (data or {}).get("steps") or []],
            state=str((data or {}).get("state") or WAITING),
            current=int((data or {}).get("current", -1)),
        )

    def reset(self) -> None:
        """Готовит очередь к повторному запуску."""
        self.state = WAITING
        self.current = -1
        for step in self.steps:
            step.state = WAITING
            step.message = ""


# ------------------------------------------------------------- хранение

_LOCK = threading.Lock()


def _load() -> dict[str, Queue]:
    if not QUEUE_FILE.is_file():
        return {}
    try:
        data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        log.warning("Битый файл очередей — начинаем заново")
        return {}
    found = {}
    for item in data if isinstance(data, list) else []:
        queue = Queue.from_dict(item)
        if queue.name:
            found[queue.name] = queue
    return found


def _write(queues: dict[str, Queue]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([q.as_dict() for q in queues.values()],
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    tmp.replace(QUEUE_FILE)


def all_queues() -> list[Queue]:
    with _LOCK:
        return sorted(_load().values(), key=lambda q: q.name.lower())


def get(name: str) -> Queue | None:
    with _LOCK:
        return _load().get(name)


def save(queue: Queue) -> Queue:
    """Очередь сохраняется и запускается повторно — в этом её смысл."""
    if not queue.name.strip():
        raise QueueError("У очереди должно быть имя")
    with _LOCK:
        found = _load()
        found[queue.name] = queue
        _write(found)
    return queue


def remove(name: str) -> bool:
    with _LOCK:
        found = _load()
        if name not in found:
            return False
        del found[name]
        _write(found)
    return True


# --------------------------------------------------------------- запуск


def run(queue: Queue, perform, on_change=None, cancel=None) -> Queue:
    """Выполняет шаги подряд.

    `perform(step)` делает шаг и возвращает текст итога либо возбуждает
    исключение. При ошибке очередь останавливается и говорит, какой шаг не
    прошёл: продолжать после сбоя нельзя — следующий шаг ждёт результата
    предыдущего.
    """
    queue.state = RUNNING
    queue.current = -1
    if on_change:
        on_change(queue)

    for index, step in enumerate(queue.steps):
        if cancel is not None and cancel.is_set():
            step.state = SKIPPED
            queue.state = SKIPPED
            if on_change:
                on_change(queue)
            return queue

        queue.current = index
        step.state = RUNNING
        step.message = ""
        if on_change:
            on_change(queue)

        try:
            step.message = str(perform(step) or "")
            step.state = DONE
        except Exception as exc:  # noqa: BLE001 — причину показываем целиком
            step.state = FAILED
            step.message = f"{type(exc).__name__}: {exc}"
            queue.state = FAILED
            log.warning("Очередь «%s» остановилась на шаге %s: %s",
                        queue.name, step.kind, step.message)
            # Остальные шаги не выполняются, но и не теряются.
            for rest in queue.steps[index + 1:]:
                rest.state = SKIPPED
            if on_change:
                on_change(queue)
            return queue

        if on_change:
            on_change(queue)

    queue.state = DONE
    queue.current = len(queue.steps)
    if on_change:
        on_change(queue)
    return queue
