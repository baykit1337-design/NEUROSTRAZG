"""Кэш фактов по главам.

Разбор главы стоит денег, поэтому повторный запуск обрабатывает только
новые и изменённые главы. «Изменённая» определяется по отпечатку текста:
если главу переписали или почистили, факты собираются заново.

Файлы лежат рядом с книгой: `analysis/facts/0209.json`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: Папка с разбором внутри папки книги.
ANALYSIS_DIR = "analysis"
FACTS_DIR = "facts"
REGISTRY_FILE = "registry.json"

#: Сколько знаков отпечатка хранить. Полного хеша не нужно.
FINGERPRINT = 16


def fingerprint(text: str) -> str:
    """Отпечаток текста главы — по нему видно, что глава изменилась."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:FINGERPRINT]


def _stem(number, source: str = "") -> str:
    """Имя файла кэша. Без номера — по имени исходного файла."""
    if number is not None:
        return f"{int(number):04d}"
    name = Path(source).stem if source else "без-номера"
    return re.sub(r"[^\w.-]+", "-", name, flags=re.UNICODE)[:80] or "без-номера"


@dataclass
class Entry:
    """Разобранная глава: сами факты плюс чем и когда их получили."""

    number: int | None = None
    title: str = ""
    source: str = ""
    fingerprint: str = ""
    model: str = ""
    facts: dict = None

    def as_dict(self) -> dict:
        return {
            "number": self.number, "title": self.title, "source": self.source,
            "fingerprint": self.fingerprint, "model": self.model,
            "facts": self.facts or {},
        }

    @classmethod
    def from_dict(cls, data: dict) -> Entry:
        return cls(
            number=data.get("number"),
            title=str(data.get("title") or ""),
            source=str(data.get("source") or ""),
            fingerprint=str(data.get("fingerprint") or ""),
            model=str(data.get("model") or ""),
            facts=data.get("facts") or {},
        )


class FactsCache:
    """Факты по главам на диске.

    Кэш не «умный»: он только помнит, что уже разобрано и от какого текста.
    Решение, слать ли главу заново, принимает вызывающий — так его видно.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / ANALYSIS_DIR / FACTS_DIR

    @property
    def registry_path(self) -> Path:
        return self.root / ANALYSIS_DIR / REGISTRY_FILE

    def path_for(self, number, source: str = "") -> Path:
        return self.dir / f"{_stem(number, source)}.json"

    def get(self, number, source: str = "") -> Entry | None:
        path = self.path_for(number, source)
        if not path.is_file():
            return None
        try:
            return Entry.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            # Битый файл кэша — не беда: разберём главу заново.
            log.warning("Битый кэш фактов: %s", path.name)
            return None

    def fresh(self, number, text: str, source: str = "") -> Entry | None:
        """Готовые факты, если глава с тех пор не менялась."""
        entry = self.get(number, source)
        if entry is None:
            return None
        if entry.fingerprint and entry.fingerprint != fingerprint(text):
            return None
        return entry

    def put(self, entry: Entry) -> Path:
        path = self.path_for(entry.number, entry.source)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(entry.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def entries(self) -> list[Entry]:
        """Всё разобранное, по возрастанию номера главы."""
        if not self.dir.is_dir():
            return []
        found = []
        for path in sorted(self.dir.glob("*.json")):
            try:
                found.append(Entry.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                log.warning("Битый кэш фактов: %s", path.name)
        found.sort(key=lambda e: (e.number is None, e.number or 0))
        return found

    def count(self) -> int:
        return len(list(self.dir.glob("*.json"))) if self.dir.is_dir() else 0

    def clear(self) -> int:
        """Забыть разбор. Пригодится, когда сменили модель."""
        removed = 0
        for path in self.dir.glob("*.json") if self.dir.is_dir() else []:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed


def parse_json(text: str) -> dict:
    """Достаёт JSON из ответа модели.

    Просить «строго JSON» мало: модель нет-нет да обернёт ответ в ```json.
    Поэтому сначала пробуем как есть, а потом вырезаем первый объект по
    скобкам — регулярным выражением вложенность не разобрать.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("пустой ответ")

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass

    start = text.find("{")
    if start == -1:
        raise ValueError("в ответе нет JSON")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start:index + 1]
                data = json.loads(chunk)
                if not isinstance(data, dict):
                    raise ValueError("ожидался объект JSON")
                return data

    raise ValueError("JSON в ответе не закрыт")
