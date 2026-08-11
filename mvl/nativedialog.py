"""Системный диалог выбора папки и файла (проводник Windows).

Tk запускается **отдельным процессом**, а не потоком. Причина простая: Tk
плохо переносит жизнь вне главного потока, а повторное создание корневого
окна в одном и том же процессе рано или поздно подвешивает Flask. Отдельный
процесс живёт ровно на время диалога и уносит все проблемы с собой — сервер
при этом не блокируется, а окно так же поднимается поверх браузера.

Если графической оболочки нет (сервер запущен без рабочего стола), диалог
честно сообщает об этом, и интерфейс остаётся на встроенном обозревателе.
"""

from __future__ import annotations

import json
import subprocess
import sys

#: Диалог ждёт человека, поэтому запас большой; нужен только чтобы забытое
#: окно не держало процесс вечно.
TIMEOUT = 600

# Скрипт для дочернего процесса. Печатает JSON — так пути с пробелами и
# кириллицей доезжают без сюрпризов.
_SCRIPT = r"""
import json, sys

mode, title, initial = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception as exc:
    print(json.dumps({"error": "tkinter недоступен: %s" % exc}))
    raise SystemExit(0)

try:
    root = tk.Tk()
    root.withdraw()
    # Поверх браузера, иначе окно теряется за ним.
    root.attributes("-topmost", True)
    root.update()

    types = [("Книги и тексты", "*.epub *.docx *.txt *.md"), ("Все файлы", "*.*")]
    if mode == "dir":
        paths = [filedialog.askdirectory(title=title, initialdir=initial or None)]
    elif mode == "files":
        # Множественное выделение через Ctrl и Shift.
        paths = list(filedialog.askopenfilenames(
            title=title, initialdir=initial or None, filetypes=types) or [])
    else:
        paths = [filedialog.askopenfilename(
            title=title, initialdir=initial or None, filetypes=types)]
    root.destroy()
except Exception as exc:
    print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}))
    raise SystemExit(0)

# Пустой список = пользователь нажал «Отмена».
paths = [p for p in paths if p]
print(json.dumps({"paths": paths}))
"""


class DialogUnavailable(RuntimeError):
    """Системный диалог показать не удалось — работаем встроенным обзором."""


def _ask(mode: str, title: str, initial: str = "") -> list[str]:
    try:
        result = subprocess.run(
            [sys.executable, "-c", _SCRIPT, mode, title, initial or ""],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise DialogUnavailable("Окно выбора не закрыли — отменяю") from exc
    except OSError as exc:
        raise DialogUnavailable(f"Не удалось открыть диалог: {exc}") from exc

    line = (result.stdout or "").strip().splitlines()
    if not line:
        detail = (result.stderr or "").strip().splitlines()
        raise DialogUnavailable(
            "Системный диалог недоступен"
            + (f": {detail[-1]}" if detail else " — нет графической оболочки")
        )

    try:
        payload = json.loads(line[-1])
    except ValueError as exc:
        raise DialogUnavailable("Диалог вернул неразборчивый ответ") from exc

    if payload.get("error"):
        raise DialogUnavailable(payload["error"])
    return list(payload.get("paths") or [])


def ask_directory(title: str = "Выберите папку", initial: str = "") -> str:
    """Путь к папке или пустая строка, если нажали «Отмена»."""
    paths = _ask("dir", title, initial)
    return paths[0] if paths else ""


def ask_open_file(title: str = "Выберите файл", initial: str = "") -> str:
    """Путь к файлу или пустая строка, если нажали «Отмена»."""
    paths = _ask("file", title, initial)
    return paths[0] if paths else ""


def ask_open_files(title: str = "Выберите файлы", initial: str = "") -> list[str]:
    """Несколько файлов сразу — выделение через Ctrl и Shift."""
    return _ask("files", title, initial)


def ask_any(title: str = "Выберите файлы или папку", initial: str = "") -> list[str]:
    """Одна кнопка «Выбрать…»: сначала файлы, иначе папка.

    Tk не умеет диалог, принимающий и файлы, и папки одним окном, поэтому
    сперва предлагаем выбрать файлы; если человек закрыл окно, ничего не
    выбрав, показываем выбор папки.
    """
    files = ask_open_files(title, initial)
    if files:
        return files
    folder = ask_directory("Или выберите папку целиком", initial)
    return [folder] if folder else []


def available() -> bool:
    """Есть ли вообще графическая оболочка — для подсказки в интерфейсе."""
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import tkinter; r=tkinter.Tk(); r.destroy(); print('ok')"],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "ok" in (result.stdout or "")
