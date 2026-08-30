"""Ночной запуск очереди книг.

Очередь книг и задумана как ночная работа: поставил десяток книг, ушёл
спать, утром они лежат. Но нажимать «Запустить» всё равно приходилось
руками — то есть сидеть до ночи или качать днём, когда канал нужен для
другого. У человека с медленным и платным интернетом это не мелочь: ночью
и быстрее, и часто дешевле.

Расписание нарочно самое простое: одно время в сутки. Не «каждые четыре
часа», не «по будням» — очередь не сервис, а список книг, который
кончается. Сложное расписание пришлось бы объяснять, а объяснять нечего.

Что здесь **не** делается: сам запуск. Модуль только хранит время и
отвечает, наступило ли оно. Запускает тот, кто умеет запускать, — иначе
пришлось бы тащить сюда пол-программы.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .history import DATA_DIR

log = logging.getLogger(__name__)

FILE = DATA_DIR / "schedule.json"

#: Окно, в которое запуск ещё уместен. Программу могли включить в десять
#: утра — «время три часа ночи уже прошло» не повод качать сейчас: канал
#: нужен человеку. А проспать назначенное из-за минутной задержки нельзя.
WINDOW_MINUTES = 30

TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass
class Plan:
    """Когда запускать очередь и с какими настройками."""

    #: «03:00». Пусто — время не назначено.
    at: str = ""
    on: bool = False
    #: Настройки прогона — те же, что у кнопки «Запустить очередь».
    payload: dict = field(default_factory=dict)
    #: Дата последнего запуска по расписанию: «2026-08-30».
    last: str = ""

    def as_dict(self) -> dict:
        return {"at": self.at, "on": self.on, "last": self.last}

    @classmethod
    def from_dict(cls, data: dict) -> Plan:
        data = data if isinstance(data, dict) else {}
        return cls(
            at=str(data.get("at") or ""),
            on=bool(data.get("on")),
            payload=dict(data.get("payload") or {}),
            last=str(data.get("last") or ""),
        )


def good_time(value: str) -> bool:
    """Похоже ли на время суток."""
    return bool(TIME.match(str(value or "").strip()))


def get() -> Plan:
    try:
        return Plan.from_dict(json.loads(FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Plan()


def _keep(plan: Plan) -> Plan:
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(
            json.dumps({**plan.as_dict(), "payload": plan.payload},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError as exc:
        log.warning("Не удалось записать расписание: %s", exc)
    return plan


def save(at: str, on: bool, payload: dict | None = None) -> Plan:
    """Назначить время. Пустое время выключает расписание."""
    at = str(at or "").strip()
    if at and not good_time(at):
        raise ValueError("Время указывается как «03:00»")
    was = get()
    return _keep(Plan(at=at, on=bool(on and at),
                      payload=dict(payload if payload is not None
                                   else was.payload),
                      last=was.last))


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def due(plan: Plan | None = None, now: datetime | None = None) -> bool:
    """Пора ли запускать.

    Три условия сразу: расписание включено, назначенное время сегодня уже
    наступило и с тех пор прошло не больше получаса, и сегодня по
    расписанию ещё не запускали.
    """
    plan = get() if plan is None else plan
    now = now or datetime.now()
    if not plan.on or not good_time(plan.at):
        return False
    if plan.last == now.date().isoformat():
        return False
    passed = _minutes(now.strftime("%H:%M")) - _minutes(plan.at)
    return 0 <= passed < WINDOW_MINUTES


def mark(now: datetime | None = None) -> Plan:
    """Запомнить, что сегодня уже запускали."""
    now = now or datetime.now()
    plan = get()
    plan.last = now.date().isoformat()
    return _keep(plan)


__all__ = ["FILE", "Plan", "WINDOW_MINUTES", "due", "get", "good_time",
           "mark", "save"]
