"""Файловая система: имена файлов, папки, обзор директорий для веб-интерфейса."""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

# Символы, запрещённые в именах файлов Windows; на *nix они тоже неудобны.
FORBIDDEN = r'<>:"/\\|?*'
MAX_NAME_LEN = 120
# CON, PRN, AUX, NUL, COM1..9, LPT1..9 — зарезервированы в Windows.
RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
    f"lpt{i}" for i in range(1, 10)
}


def sanitize_filename(name: str, fallback: str = "untitled") -> str:
    """Чистит строку до безопасного имени файла или папки."""
    name = unicodedata.normalize("NFC", str(name or ""))
    name = "".join("_" if (ch in FORBIDDEN or ord(ch) < 32) else ch for ch in name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(". ")  # Windows не терпит точку/пробел в конце

    if len(name) > MAX_NAME_LEN:
        name = name[:MAX_NAME_LEN].rstrip(". ")
    if name.split(".")[0].lower() in RESERVED:
        name = f"_{name}"
    return name or fallback


def chapter_filename(number: int, title: str) -> str:
    """`0001 - Название главы.txt` — ведущие нули до 4 знаков ради сортировки."""
    safe = sanitize_filename(title, fallback=f"Chapter {number}")
    return f"{number:04d} - {safe}.txt"


def expand(path: str | os.PathLike) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()


def prepare_output_dir(base: str | os.PathLike, folder_name: str) -> Path:
    """Создаёт папку {base}/{folder_name} и возвращает путь.

    Существующая папка используется как есть — на неё опирается докачка.

    Без имени пишем прямо в выбранную папку. Скачиванию своя папка на
    книгу нужна — их там десятки, — а тому, кто разбивает один файл,
    сочинять ей имя незачем: он уже выбрал, куда положить.
    """
    base_path = expand(base)
    if base_path.exists() and not base_path.is_dir():
        raise NotADirectoryError(f"Не папка: {base_path}")

    name = str(folder_name or "").strip()
    target = base_path / sanitize_filename(name, fallback="novel") if name \
        else base_path
    target.mkdir(parents=True, exist_ok=True)

    probe = target / ".write-test"
    try:
        probe.touch()
        probe.unlink()
    except OSError as exc:
        raise PermissionError(f"Нет прав на запись в {target}: {exc}") from exc
    return target


def list_dirs(
    path: str | os.PathLike | None = None,
    suffixes: tuple[str, ...] | None = None,
) -> dict:
    """Содержимое директории для выбора в интерфейсе.

    Папки — всегда. Файлы — только если задан список расширений (тогда это
    выбор файла, а не места сохранения).
    """
    current = expand(path) if path else Path.home()
    if not current.is_dir():
        current = Path.home()

    entries: list[dict] = []
    files: list[dict] = []
    try:
        for item in sorted(current.iterdir(), key=lambda p: p.name.lower()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                entries.append({"name": item.name, "path": str(item)})
            elif suffixes and item.suffix.lower() in suffixes:
                try:
                    size = item.stat().st_size
                except OSError:
                    size = 0
                files.append({"name": item.name, "path": str(item), "size": size})
    except PermissionError:
        entries, files = [], []

    parent = str(current.parent) if current.parent != current else None
    return {
        "path": str(current),
        "parent": parent,
        "home": str(Path.home()),
        "dirs": entries,
        "files": files,
        "writable": os.access(current, os.W_OK),
    }


def write_chapter(path: Path, novel_name: str, title: str, number: int, text: str) -> None:
    """Пишет главу в .txt: шапка с названиями, затем текст."""
    header = f"{novel_name}\n{title}\n\n"
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(header + text + "\n", encoding="utf-8")
    tmp.replace(path)  # атомарная замена: недокачанных файлов не остаётся
