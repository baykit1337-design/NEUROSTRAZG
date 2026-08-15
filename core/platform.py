"""Платформенные мелочи: открытие файлов и домашняя папка.

Держим в одном месте, чтобы `os.startfile` не разъезжался по коду и
программа работала на Windows, macOS и Linux одинаково.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"


class OpenError(RuntimeError):
    """Файл не удалось открыть."""


def home() -> Path:
    """Домашняя папка — одинаково на всех системах."""
    return Path.home()


def open_file(path: str | Path) -> Path:
    """Открывает файл в программе по умолчанию.

    Windows — `os.startfile`, macOS — `open`, Linux — `xdg-open`.
    """
    target = Path(path).expanduser()
    if not target.exists():
        raise OpenError(f"Файл не найден: {target}")

    try:
        if WINDOWS:
            import os

            os.startfile(str(target))  # noqa: S606 — программа по умолчанию
        elif MACOS:
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except FileNotFoundError as exc:
        # Нечем открывать: на голой системе без окружения рабочего стола
        # `xdg-open` не поставлен. Это не поломка программы, и говорить об
        # этом надо человеческими словами.
        helper = "open" if MACOS else "xdg-open"
        raise OpenError(
            f"В системе нет «{helper}» — открывать файлы нечем. "
            f"Путь: {target}") from exc
    except Exception as exc:
        raise OpenError(f"{type(exc).__name__}: {exc}") from exc
    return target


#: Шрифты, которые есть не везде, и чем их заменить.
FONT_FALLBACKS = {
    "Times New Roman": ("Times New Roman", "Liberation Serif", "DejaVu Serif", "Georgia"),
    "Arial": ("Arial", "Liberation Sans", "DejaVu Sans", "Helvetica"),
    "Calibri": ("Calibri", "Carlito", "DejaVu Sans"),
}


def font_note(name: str) -> str:
    """Предупреждение, если шрифта может не быть в системе.

    Проверить наличие шрифта надёжно нельзя — документ откроется на другой
    машине. Поэтому не молчим, а предупреждаем.
    """
    if WINDOWS or name not in FONT_FALLBACKS:
        return ""
    alternatives = ", ".join(FONT_FALLBACKS[name][1:3])
    return (
        f"Шрифта «{name}» может не быть в этой системе. "
        f"Word подставит похожий ({alternatives})."
    )
