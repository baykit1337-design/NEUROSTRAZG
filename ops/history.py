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

#: И сколько они могут весить вместе. Счёт по штукам от диска не спасает:
#: десять копий книги на пятьсот глав — это гигабайты, о которых человек
#: узнаёт от диска, а не от программы.
MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024

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
    #: Какие файлы операция создала в `output`. Нужны, чтобы «вернуть как
    #: было» умело не только вернуть заменённое, но и убрать добавленное:
    #: копия хранит лишь то, что перезаписали, а разбиение в пустую папку
    #: не перезаписывает ничего — и возвращать по одной копии было бы
    #: нечего.
    wrote: list = field(default_factory=list)
    #: Эту операцию уже вернули. Иначе «вернуть как было» второй раз
    #: брало бы ту же запись, и шаг назад упирался бы в один и тот же.
    undone: bool = False

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
            "wrote": list(self.wrote),
            "undone": self.undone,
            "restorable": bool(self.backup) and Path(self.backup).is_dir(),
            "undoable": self.undoable,
        }

    @property
    def undoable(self) -> bool:
        """Есть ли что откатывать.

        Двумя способами сразу: вернуть заменённое из копии и убрать
        добавленное. Одной копии мало — в пустую папку операция ничего не
        перезаписывает, и копии не будет вовсе.
        """
        if not self.output or not Path(self.output).is_dir():
            return False
        if self.backup and Path(self.backup).is_dir():
            return True
        return any((Path(self.output) / Path(name).name).is_file()
                   for name in self.wrote)

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
            # Записи, сделанные до появления поля, его не имеют — и это
            # не поломка журнала, а обычная прежняя строка.
            wrote=[str(one) for one in (data.get("wrote") or [])],
            undone=bool(data.get("undone")),
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
        failed: int = 0, backup: str = "", note: str = "", wrote=()) -> Record:
    """Дописывает строку в журнал."""
    record = Record(
        stamp=datetime.now().strftime(STAMP), operation=operation,
        source=str(source), output=str(output), files=files, failed=failed,
        backup=str(backup), note=note,
        wrote=[str(one) for one in wrote],
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


def backup_tree(root, paths, operation: str = "") -> str:
    """Копирует файлы, сохраняя их место относительно корня.

    `backup_files` кладёт всё в одну папку по именам — для глав книги
    этого хватает, они и лежат рядом. Для файлов программы нет: там
    `ops/base.py` и `core/base.py` — разные файлы с одним именем, и
    плоская копия потеряла бы один из них молча. А вернуть такую копию на
    место было бы нечем: неизвестно, откуда каждый файл взялся.
    """
    root = Path(root)
    found = [Path(one) for one in paths if Path(one).is_file()]
    if not found:
        return ""

    stamp = datetime.now().strftime(STAMP)
    name = f"{stamp}_{operation}".strip("_") or stamp
    target = BACKUP_DIR / name

    try:
        for one in found:
            try:
                where = one.relative_to(root)
            except ValueError:
                # Файл не из-под корня — кладём по имени, как раньше.
                where = Path(one.name)
            destination = target / where
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(one, destination)
    except OSError as exc:
        log.warning("Не удалось скопировать файлы из %s: %s", root, exc)
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


def weigh(path) -> int:
    """Сколько весит папка со всем, что в ней лежит."""
    total = 0
    for one in Path(path).rglob("*"):
        try:
            if one.is_file():
                total += one.stat().st_size
        except OSError as exc:
            log.debug("Не взвесить %s: %s", one, exc)
    return total


def trim(keep: int = KEEP_BACKUPS, cap: int = MAX_BACKUP_BYTES) -> int:
    """Удаляет старые копии: сперва лишние по счёту, потом по весу.

    Одного счёта мало. Десять копий книги на пятьсот глав — это гигабайты
    на диске, где у человека может не быть и одного; а десять копий одной
    правки — это ничто. Решает вес, счёт остаётся верхней границей.
    """
    removed = 0
    for path in backups()[keep:]:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError as exc:
            log.warning("Не удалось удалить копию %s: %s", path, exc)

    if cap <= 0:
        return removed
    left = [(path, weigh(path)) for path in backups()]
    total = sum(size for _, size in left)
    # Самую свежую не трогаем никогда: она и есть «вернуть как было».
    for path, size in reversed(left[1:]):
        if total <= cap:
            break
        try:
            shutil.rmtree(path)
            total -= size
            removed += 1
            log.info("Копия %s удалена: корзина переросла %s байт", path, cap)
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


def last_undo() -> Record | None:
    """Последняя операция, которую есть чем откатить.

    Откатывать нечего у тех, чьи файлы уже унесли или удалили руками.
    Такие записи пропускаем: «вернуть как было» должно либо работать,
    либо не предлагаться.
    """
    for record in records():
        if record.undoable and not record.undone:
            return record
    return None


def steps_back() -> int:
    """Сколько шагов назад ещё можно сделать.

    Чтобы «вернуть как было» не выглядело последней возможностью: видно,
    что за ним стоит ещё пять операций.
    """
    return sum(1 for record in records()
               if record.undoable and not record.undone)


def mark_undone(record: Record) -> None:
    """Пометить операцию возвращённой.

    Без пометки второе нажатие взяло бы ту же самую запись: она осталась
    бы и в журнале, и откатываемой. Шаг назад стоял бы на месте.
    """
    found = _load()
    for one in found:
        if (one.stamp == record.stamp and one.output == record.output
                and one.operation == record.operation):
            one.undone = True
    record.undone = True
    try:
        _save(found)
    except OSError as exc:
        log.warning("Не удалось отметить возврат в журнале: %s", exc)


def undo(record: Record) -> int:
    """Возвращает папку к тому, что было до операции.

    Двумя шагами, и оба нужны. Копия хранит только **заменённые** файлы:
    операция, разложившая книгу по пустой папке, не перезаписала ничего,
    и одной копией её было бы не откатить — папка так и осталась бы с
    новыми файлами. Поэтому сперва убираем добавленное, потом возвращаем
    заменённое.

    Убираем строго то, что записали сами, и только по имени: имя из
    журнала может оказаться путём, а удалять по чужому пути — последнее
    дело. Всё убранное перед этим уходит в корзину: возвращение должно
    быть так же обратимо, как и то, от чего оно спасает.
    """
    where = Path(record.output)
    if not where.is_dir():
        raise RestoreError(f"Папка не найдена: {where}")

    ours = [where / Path(name).name for name in record.wrote]
    doomed = [one for one in ours if one.is_file()]
    if doomed:
        backup_files(doomed, "перед-возвратом")
    for one in doomed:
        one.unlink(missing_ok=True)

    back = 0
    if record.backup and Path(record.backup).is_dir():
        back = restore(Path(record.backup), where)
    mark_undone(record)
    return back + len(doomed)


def state() -> dict:
    """Что лежит в журнале и в корзине — для интерфейса."""
    kept = [{"path": str(p), "name": p.name,
             "files": sum(1 for f in p.rglob("*") if f.is_file()),
             "bytes": weigh(p)}
            for p in backups()]
    return {
        "records": [r.as_dict() for r in records()],
        "backups": kept,
        "keep": KEEP_BACKUPS,
        # Вес корзины и всей папки данных. При лимитном диске это важнее,
        # чем число копий: копия книги на пятьсот глав весит полгигабайта.
        "bytes": sum(one["bytes"] for one in kept),
        "cap": MAX_BACKUP_BYTES,
        "data_bytes": weigh(DATA_DIR),
        "dir": str(DATA_DIR),
        # Что откатится по «вернуть как было». Считается здесь, а не в
        # интерфейсе: правило «копия есть и папка на месте» должно быть
        # одно, а не своё у каждой кнопки.
        "undo": (found.as_dict() if (found := last_undo()) else None),
        # Сколько шагов назад ещё осталось: одна кнопка без счётчика
        # выглядит как единственная попытка.
        "undo_left": steps_back(),
    }
