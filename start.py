"""Запуск одним файлом: общая часть для Windows, macOS и Linux (5.1 ТЗ).

Почему работа живёт здесь, а не в самих `Запустить.bat` и
`Запустить.command`.

`cmd.exe` читает `.bat` побайтово в текущей кодовой странице и после
каждой команды возвращается к файлу по запомненному смещению. `chcp`
посреди файла меняет раскодировку, но не смещение: разбор продолжается с
середины строки, `rem` в начале теряется, и остаток комментария уходит в
исполнение. В консоли это выглядит так:

    'ошибке' is not recognized as an internal or external command

— по обрывку русского комментария на каждую строку. Поэтому в `.bat` нет
ни одного не-ASCII байта, а всё, что нужно сказать по-русски, говорится
отсюда: Python на Windows пишет в консоль через `WriteConsoleW` и от
кодовой страницы не зависит вовсе.

Заодно правило «зависимости, прокси, запуск» лежит в одном месте, а не в
двух расходящихся копиях под две системы.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def say(text: str = "") -> None:
    """Строка в консоль с общим отступом."""
    print(f"  {text}" if text else "")


def deps() -> None:
    """Доставляет зависимости.

    Молча: два десятка строк «уже установлено» при каждом запуске прячут
    единственную строку, которую стоило прочесть. Неудача установки — не
    повод не пробовать запуск: пакеты могли остаться с прошлого раза, а
    если нет, программа скажет об этом внятнее, чем pip.
    """
    need = ROOT / "requirements.txt"
    if not need.is_file():
        return

    say("Проверяю зависимости...")
    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(need),
         "--quiet", "--disable-pip-version-check"],
        cwd=ROOT, check=False)
    if done.returncode:
        say("Зависимости доставить не вышло — пробую запустить как есть.")


def proxies() -> None:
    """Кладёт образец списка прокси, если своего ещё нет.

    Существующий не трогаем ни при каких условиях: в нём адреса с
    паролями, и затереть их образцом — потерять их насовсем.
    """
    mine = ROOT / "proxies.txt"
    example = ROOT / "proxies.example.txt"
    if mine.exists() or not example.is_file():
        return
    shutil.copy(example, mine)
    say("Создал proxies.txt из образца — адреса впишите в него сами.")


def serve() -> int:
    """Поднимает программу и ждёт, пока её закроют.

    Браузер открывает сама программа — через секунду после старта, когда
    сервер уже отвечает. Открывать его отсюда значит получить вторую
    вкладку с ошибкой соединения.
    """
    app = ROOT / "webapp" / "app.py"
    if not app.is_file():
        say(f"Не нашёл {app} — проект распакован не целиком.")
        return 1

    say("Запускаю NEUROSTRAZH...")
    say()
    return subprocess.run([sys.executable, str(app)], cwd=ROOT,
                          check=False).returncode


def main() -> int:
    deps()
    proxies()
    return serve()


if __name__ == "__main__":
    sys.exit(main())
