"""Список ключей модели и ротация между ними (7.1–7.4 ТЗ NEUROSTRAZH).

Один ключ на книгу в пятьсот глав не хватает: у бесплатной квоты Gemini
есть суточный потолок, и разбор упирается в него на середине. Поэтому
ключей несколько, а работа сама переходит на следующий.

Главное правило ротации: запрос, на котором ключ кончился, **повторяется
по новому ключу**, а не теряется. Иначе на каждом переключении в книге
появлялась бы дыра в одну главу — и нашлась бы она нескоро.

Ключи лежат в `config.json`, файл в `.gitignore`. Наружу они отдаются
только замаскированными.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from config import settings

from .client import NoKeysLeft, key_id, short

#: `NoKeysLeft` живёт в `client.py` — там же, где остальные ошибки модели.
#: Заводить второй такой же класс здесь значило бы повторить историю с
#: тремя разными «отменами», из-за которой остановка показывалась ошибкой.

#: Состояния ключа.
ACTIVE = "active"
EXHAUSTED = "exhausted"

#: Через сколько после исчерпания квота Gemini обычно возвращается.
#: Используется, только если сервер не сказал точнее.
RESET_HOURS = 24

STAMP = "%Y-%m-%dT%H:%M:%S"


@dataclass
class Key:
    """Один ключ и всё, что о нём известно."""

    key: str = ""
    #: Произвольная метка, чтобы различать в списке.
    name: str = ""
    #: Сколько запросов разрешено. Ноль — без ограничения.
    limit: int = 0
    used: int = 0
    state: str = ACTIVE
    #: Когда пометили исчерпанным и когда квота вернётся.
    exhausted_at: str = ""
    reset_at: str = ""

    @property
    def left(self) -> int | None:
        """Сколько запросов осталось. None — ограничения нет."""
        return None if self.limit <= 0 else max(0, self.limit - self.used)

    @property
    def resets_in(self) -> int | None:
        """Секунд до сброса квоты. None — сброс не назначен."""
        if not self.reset_at:
            return None
        try:
            when = datetime.strptime(self.reset_at, STAMP)
        except ValueError:
            return None
        return max(0, int((when - datetime.now()).total_seconds()))

    def as_dict(self, safe: bool = True) -> dict:
        return {
            # Наружу ключ уходит только сокращённым, целиком — никогда.
            "key": short(self.key) if safe else self.key,
            "id": key_id(self.key),
            # Имя отдаём как есть, даже пустое: оно правится в поле ввода,
            # и подстановка сокращения записалась бы туда вместо имени.
            "name": self.name,
            # Подпись для показа там, где имени может не быть.
            "label": self.name or short(self.key),
            "limit": self.limit,
            "used": self.used,
            "left": self.left,
            "state": self.state,
            "exhausted_at": self.exhausted_at,
            "reset_at": self.reset_at,
            "resets_in": self.resets_in,
        }

    @classmethod
    def from_dict(cls, data) -> Key:
        # Строкой ключ приходит из старых настроек, когда он был один.
        if isinstance(data, str):
            return cls(key=data.strip())
        data = data or {}
        return cls(
            key=str(data.get("key") or "").strip(),
            name=str(data.get("name") or ""),
            limit=int(data.get("limit") or 0),
            used=int(data.get("used") or 0),
            state=str(data.get("state") or ACTIVE),
            exhausted_at=str(data.get("exhausted_at") or ""),
            reset_at=str(data.get("reset_at") or ""),
        )


class KeyStore:
    """Список ключей: хранение, ротация, учёт расхода.

    Один на программу: счётчики расхода должны видеть все потоки разбора,
    иначе три потока израсходуют лимит втрое.
    """

    def __init__(self):
        self._lock = threading.RLock()

    # ------------------------------------------------------------ хранение

    def all(self) -> list[Key]:
        with self._lock:
            found = [Key.from_dict(item) for item in (settings.llm.keys or [])]
            # Ключ из старой настройки — тоже ключ, иначе он молча пропал бы
            # при обновлении программы.
            old = (settings.llm.api_key or "").strip()
            if old and not any(k.key == old for k in found):
                found.insert(0, Key(key=old, name="из настроек"))
            return [k for k in found if k.key]

    def save(self, keys: list[Key]) -> list[Key]:
        with self._lock:
            settings.llm.keys = [k.as_dict(safe=False) for k in keys if k.key]
            # Единственное место хранения — список. Отдельное поле оставляем
            # пустым, чтобы ключ не жил в двух местах и не расходился.
            settings.llm.api_key = ""
            settings.save()
            return keys

    def add(self, text: str, name: str = "", limit: int = 0) -> list[Key]:
        """Добавляет ключ или сразу несколько строк.

        Вставка списком — обычное дело: ключи заводят пачкой и копируют
        из блокнота целиком.
        """
        with self._lock:
            keys = self.all()
            have = {k.key for k in keys}
            added = 0
            for line in str(text or "").replace(",", "\n").split("\n"):
                value = line.strip()
                if not value or value in have:
                    continue
                have.add(value)
                keys.append(Key(key=value,
                                name=name if added == 0 else "",
                                limit=limit))
                added += 1
            return self.save(keys)

    def remove(self, ident: str) -> list[Key]:
        """Удаляет ключ по признаку.

        Не по сокращённому виду: у ключей одного провайдера начало
        совпадает, и удаление ушло бы не туда.
        """
        with self._lock:
            keys = [k for k in self.all() if key_id(k.key) != ident]
            return self.save(keys)

    def update(self, ident: str, **fields) -> list[Key]:
        with self._lock:
            keys = self.all()
            for key in keys:
                if key_id(key.key) != ident:
                    continue
                for name, value in fields.items():
                    if hasattr(key, name) and value is not None:
                        setattr(key, name, value)
            return self.save(keys)

    # ------------------------------------------------------------ ротация

    def _wake(self, keys: list[Key]) -> bool:
        """Возвращает в строй ключи, у которых срок вышел."""
        changed = False
        for key in keys:
            if key.state != EXHAUSTED or key.reset_at == "":
                continue
            if key.resets_in == 0:
                key.state = ACTIVE
                key.used = 0
                key.exhausted_at = key.reset_at = ""
                changed = True
        return changed

    def active(self) -> Key:
        """Первый годный ключ. Нет ни одного — `NoKeysLeft`."""
        with self._lock:
            keys = self.all()
            if not keys:
                raise NoKeysLeft(
                    "Ключей нет. Добавьте хотя бы один в настройках анализа.")
            if self._wake(keys):
                self.save(keys)

            for key in keys:
                if key.state == ACTIVE:
                    return key
            raise NoKeysLeft(self.why_stopped(keys))

    def why_stopped(self, keys: list[Key] | None = None) -> str:
        keys = keys if keys is not None else self.all()
        soon = [k.resets_in for k in keys if k.resets_in is not None]
        when = min(soon) if soon else None
        if when is None:
            return ("Все ключи исчерпаны. Добавьте новый или снимите пометку "
                    "«исчерпан» вручную.")
        return (f"Все ключи исчерпаны. Ближайший сброс через "
                f"{_human(when)}.")

    def spend(self, key: Key, count: int = 1) -> None:
        """Отмечает израсходованные запросы.

        Ключ помечается исчерпанным по своему же лимиту, не дожидаясь
        отказа сервера: дождаться отказа — значит потерять запрос.
        """
        with self._lock:
            keys = self.all()
            for item in keys:
                if item.key != key.key:
                    continue
                item.used += count
                if item.limit > 0 and item.used >= item.limit:
                    _exhaust(item)
            self.save(keys)

    def exhaust(self, key: Key, seconds: int | None = None) -> None:
        """Помечает ключ исчерпанным. `seconds` — срок от сервера."""
        with self._lock:
            keys = self.all()
            for item in keys:
                if item.key == key.key:
                    _exhaust(item, seconds)
            self.save(keys)

    # -------------------------------------------------------- для экрана

    def state(self) -> dict:
        keys = self.all()
        self._wake(keys)
        return {
            "keys": [k.as_dict() for k in keys],
            "total": len(keys),
            "active": sum(1 for k in keys if k.state == ACTIVE),
            "exhausted": sum(1 for k in keys if k.state == EXHAUSTED),
            "model": settings.llm.model,
            "use_proxies": settings.llm.use_proxies,
        }


def _exhaust(key: Key, seconds: int | None = None) -> None:
    now = datetime.now()
    key.state = EXHAUSTED
    key.exhausted_at = now.strftime(STAMP)
    # Срок от сервера точнее расчётного — берём его, если он пришёл.
    ahead = timedelta(seconds=seconds) if seconds else timedelta(hours=RESET_HOURS)
    key.reset_at = (now + ahead).strftime(STAMP)


def _human(seconds: int) -> str:
    hours, rest = divmod(max(0, seconds), 3600)
    minutes = rest // 60
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин" if minutes else "меньше минуты"


#: Общий список на программу.
store = KeyStore()
