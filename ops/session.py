"""Сессия разбора: на чём остановились и как продолжить (7.6 ТЗ).

Разбор книги в пятьсот глав не укладывается в одну квоту, поэтому он
обязан переживать остановку. Кэш фактов и так лежит на диске, но по нему
не видно главного: что именно было выбрано, сколько предстояло и почему
работа встала. Без этого «Продолжить» пришлось бы собирать руками —
заново выбирать папку и надеяться, что кэш подхватит.

Файл один на папку книги: `analysis/session.json`. Книг в работе бывает
несколько, и общий файл на всех означал бы, что вторая книга затирает
первую.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SESSION_FILE = "session.json"
STAMP = "%Y-%m-%dT%H:%M:%S"

#: Состояния сессии.
RUNNING = "running"
STOPPED = "stopped"
DONE = "done"

_LOCK = threading.Lock()


def _path(root) -> Path:
    return Path(str(root)).expanduser() / "analysis" / SESSION_FILE


@dataclass
class Session:
    """Что делали, сколько сделали и почему остановились."""

    root: str = ""
    targets: list = field(default_factory=list)
    total: int = 0
    done: int = 0
    failed: int = 0
    state: str = RUNNING
    #: Почему встали: исчерпаны ключи, остановил человек, ошибка.
    reason: str = ""
    started: str = ""
    updated: str = ""
    model: str = ""
    #: Какими ключами работали — по признакам, не самими ключами.
    keys: list = field(default_factory=list)

    @property
    def left(self) -> int:
        return max(0, self.total - self.done)

    @property
    def finished(self) -> bool:
        return self.state == DONE or self.left == 0

    def as_dict(self) -> dict:
        return {
            "root": self.root, "targets": list(self.targets),
            "total": self.total, "done": self.done, "failed": self.failed,
            "state": self.state, "reason": self.reason,
            "started": self.started, "updated": self.updated,
            "model": self.model, "keys": list(self.keys),
            "left": self.left, "finished": self.finished,
            "when": _human(self.started),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Session:
        data = data or {}
        return cls(
            root=str(data.get("root") or ""),
            targets=[str(t) for t in data.get("targets") or []],
            total=int(data.get("total") or 0),
            done=int(data.get("done") or 0),
            failed=int(data.get("failed") or 0),
            state=str(data.get("state") or RUNNING),
            reason=str(data.get("reason") or ""),
            started=str(data.get("started") or ""),
            updated=str(data.get("updated") or ""),
            model=str(data.get("model") or ""),
            keys=[str(k) for k in data.get("keys") or []],
        )


def _human(stamp: str) -> str:
    try:
        return datetime.strptime(stamp, STAMP).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return stamp


def load(root) -> Session | None:
    path = _path(root)
    if not path.is_file():
        return None
    try:
        return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        log.warning("Битая сессия разбора: %s", path)
        return None


def save(session: Session) -> Session:
    session.updated = datetime.now().strftime(STAMP)
    path = _path(session.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(session.as_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        # Сессия — удобство, а не работа программы: не смогли записать —
        # разбор всё равно идёт, кэш глав никуда не делся.
        log.warning("Не удалось записать сессию: %s", exc)
    return session


def start(root, targets, total: int, model: str = "", keys=None) -> Session:
    """Заводит сессию или продолжает прежнюю по той же папке."""
    found = load(root)
    if found is not None and not found.finished and found.targets == list(targets):
        found.state = RUNNING
        found.reason = ""
        found.total = total or found.total
        return save(found)

    return save(Session(
        root=str(root), targets=[str(t) for t in targets], total=total,
        state=RUNNING, started=datetime.now().strftime(STAMP),
        model=model, keys=list(keys or []),
    ))


def update(root, done: int = None, failed: int = None) -> Session | None:
    session = load(root)
    if session is None:
        return None
    if done is not None:
        session.done = done
    if failed is not None:
        session.failed = failed
    return save(session)


def stop(root, reason: str, done: int = None, failed: int = None) -> Session | None:
    """Останавливает сессию, сохраняя причину.

    Причина — половина смысла: «остановлено» и «кончились ключи» требуют
    от человека разного, и «Продолжить» в этих случаях доступно по-разному.
    """
    session = load(root)
    if session is None:
        return None
    if done is not None:
        session.done = done
    if failed is not None:
        session.failed = failed
    session.state = DONE if session.left == 0 else STOPPED
    session.reason = reason
    return save(session)


def finish(root, done: int = None) -> Session | None:
    session = load(root)
    if session is None:
        return None
    if done is not None:
        session.done = done
    session.state = DONE
    session.reason = ""
    return save(session)


def forget(root) -> bool:
    """«Начать заново» — стирает прогресс сессии, но не кэш глав."""
    path = _path(root)
    if not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
