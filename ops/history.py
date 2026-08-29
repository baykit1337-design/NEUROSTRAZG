"""Журнал операций и корзина.

Две вещи, которых не хватало при неудачной операции: понять, что вообще
делалось с этой книгой месяц назад, и вернуть прежнюю версию.

Журнал пишется всегда, корзина — только когда операция пишет поверх уже
существующих файлов. В новую папку — писать поверх нечего, копировать
нечего.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _under_test() -> bool:
    """Запущены ли мы прогонщиком тестов.

    Проверка нужна, чтобы прогон не писал в настоящий журнал
    пользователя. Смотрим именно на то, чем запущен процесс: сам по себе
    импорт `unittest` ещё ничего не значит — его может импортировать и
    обычный код.
    """
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    name = getattr(spec, "name", "") or ""
    return name.startswith(("unittest", "pytest")) or "pytest" in sys.argv[0]


def _default_dir() -> Path:
    """Куда складывать журнал и копии.

    Порядок: явно заданная переменная окружения, потом временная папка
    для прогона тестов, потом папка рядом с программой.
    """
    chosen = os.environ.get("NEUROSTRAZH_DATA")
    if chosen:
        return Path(chosen)
    if _under_test():
        return Path(tempfile.gettempdir()) / "neurostrazh-tests-data"
    return Path(__file__).resolve().parent.parent / "data"

#: Куда складывать журнал и копии. Рядом с программой, а не с книгой:
#: книг много, а история одна.
DATA_DIR = _default_dir()
HISTORY_FILE = DATA_DIR / "history.json"
BACKUP_DIR = DATA_DIR / "backup"

#: Сколько операций держать в корзине. Старые удаляются сами, иначе папка
#: с копиями книги на пятьсот глав быстро съест диск.
KEEP_BACKUPS = 10

#: Сколько записей журнала хранить.
KEEP_RECORDS = 500

#: Формат имени папки копии: по нему же она и сортируется.
STAMP = "%Y-%m-%d_%H-%M-%S"


@dataclass
class Record:
    """Одна строка журнала."""

    stamp: str = ""
    operation: str = ""
    source: str = ""
    output: str = ""
    files: int = 0
    failed: int = 0
    backup: str = ""
    note: str = ""

    @property
    def when(self) -> str:
        """Дата и время в читаемом виде."""
        try:
            return datetime.strptime(self.stamp, STAMP).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return self.stamp

    def as_dict(self) -> dict:
        return {
            "stamp": self.stamp, "when": self.when, "operation": self.operation,
            "source": self.source, "output": self.output, "files": self.files,
            "failed": self.failed, "backup": self.backup, "note": self.note,
            "restorable": bool(self.backup) and Path(self.backup).is_dir(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Record:
        return cls(
            stamp=str(data.get("stamp") or ""),
            operation=str(data.get("operation") or ""),
            source=str(data.get("source") or ""),
            output=str(data.get("output") or ""),
            files=int(data.get("files") or 0),
            failed=int(data.get("failed") or 0),
            backup=str(data.get("backup") or ""),
            note=str(data.get("note") or ""),
        )


def _load() -> list[Record]:
    if not HISTORY_FILE.is_file():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Битый журнал не должен мешать работать.
        log.warning("Битый журнал операций — начинаем заново")
        return []
    return [Record.from_dict(item) for item in data if isinstance(item, dict)]


def _save(records: list[Record]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_FILE.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps([r.as_dict() for r in records[-KEEP_RECORDS:]],
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    tmp.replace(HISTORY_FILE)


def records(limit: int = 100) -> list[Record]:
    """Журнал, свежие записи первыми."""
    return list(reversed(_load()))[:limit]


def add(operation: str, source: str = "", output: str = "", files: int = 0,
        failed: int = 0, backup: str = "", note: str = "") -> Record:
    """Дописывает строку в журнал."""
    record = Record(
        stamp=datetime.now().strftime(STAMP), operation=operation,
        source=str(source), output=str(output), files=files, failed=failed,
        backup=str(backup), note=note,
    )
    found = _load()
    found.append(record)
    try:
        _save(found)
    except OSError as exc:
        # Журнал — вещь полезная, но не настолько, чтобы ронять операцию.
        log.warning("Не удалось записать журнал: %s", exc)
    return record


# --------------------------------------------------------------- корзина


def backup(folder: Path, operation: str = "") -> str:
    """Копирует папку в корзину перед перезаписью.

    Возвращает путь к копии или пустую строку, если копировать было нечего.
    """
    folder = Path(folder)
    if not folder.is_dir() or not any(folder.iterdir()):
        return ""

    stamp = datetime.now().strftime(STAMP)
    name = f"{stamp}_{operation}".strip("_") or stamp
    target = BACKUP_DIR / name

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(folder, target, dirs_exist_ok=True)
    except OSError as exc:
        log.warning("Не удалось сделать копию %s: %s", folder, exc)
        return ""

    trim()
    return str(target)


def backup_files(paths, operation: str = "") -> str:
    """Копирует в корзину только названные файлы.

    Нужно там, где пишут прямо в выбранную человеком папку. Копировать её
    целиком нельзя: выбрать могут рабочий стол, и полгигабайта чужих
    файлов уедут в корзину ради двадцати новых. Пропасть же может только
    то, что будет перезаписано, — его и бережём.
    """
    found = [Path(one) for one in paths if Path(one).is_file()]
    if not found:
        return ""

    stamp = datetime.now().strftime(STAMP)
    name = f"{stamp}_{operation}".strip("_") or stamp
    target = BACKUP_DIR / name

    try:
        target.mkdir(parents=True, exist_ok=True)
        for one in found:
            shutil.copy2(one, target / one.name)
    except OSError as exc:
        log.warning("Не удалось скопировать файлы из %s: %s",
                    found[0].parent, exc)
        return ""

    trim()
    return str(target)


def backup_file(path: Path, operation: str = "") -> str:
    """Копирует один файл в корзину.

    Правка одной главы в читалке не повод копировать всю папку: на книге в
    пятьсот глав это полгигабайта ради одного абзаца. В корзине копия
    выглядит как папка с одним файлом — восстановление работает так же.
    """
    path = Path(path)
    if not path.is_file():
        return ""

    stamp = datetime.now().strftime(STAMP)
    name = f"{stamp}_{operation}".strip("_") or stamp
    target = BACKUP_DIR / name

    try:
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / path.name)
    except OSError as exc:
        log.warning("Не удалось скопировать %s: %s", path, exc)
        return ""

    trim()
    return str(target)


def backups() -> list[Path]:
    """Копии в корзине, свежие первыми."""
    if not BACKUP_DIR.is_dir():
        return []
    return sorted((p for p in BACKUP_DIR.iterdir() if p.is_dir()),
                  key=lambda p: p.name, reverse=True)


def trim(keep: int = KEEP_BACKUPS) -> int:
    """Удаляет старые копии. Папка с копиями книги растёт быстро."""
    removed = 0
    for path in backups()[keep:]:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            log.warning("Не удалось удалить копию %s: %s", path, exc)
    return removed


class RestoreError(Exception):
    """Восстановить не удалось."""


def restore(backup_path: Path, target: Path) -> int:
    """Возвращает файлы из копии на место.

    Перед восстановлением текущее состояние тоже уходит в корзину: иначе
    «Восстановить», нажатое по ошибке, было бы так же необратимо, как и то,
    от чего оно спасает.
    """
    source = Path(backup_path)
    target = Path(target)
    if not source.is_dir():
        raise RestoreError(f"Копия не найдена: {source}")

    backup(target, "перед-восстановлением")
    try:
        target.mkdir(parents=True, exist_ok=True)
        count = 0
        for item in source.rglob("*"):
            if not item.is_file():
                continue
            destination = target / item.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            count += 1
    except OSError as exc:
        raise RestoreError(f"Не удалось восстановить: {exc}") from exc

    add("восстановление", source=str(source), output=str(target), files=count)
    return count


def state() -> dict:
    """Что лежит в журнале и в корзине — для интерфейса."""
    return {
        "records": [r.as_dict() for r in records()],
        "backups": [
            {"path": str(p), "name": p.name,
             "files": sum(1 for f in p.rglob("*") if f.is_file())}
            for p in backups()
        ],
        "keep": KEEP_BACKUPS,
        "dir": str(DATA_DIR),
    }
