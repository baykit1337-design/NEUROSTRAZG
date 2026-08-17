#!/bin/bash
# NEUROSTRAZH — запуск одним файлом на macOS и Linux (5.2 ТЗ).
#
# Двойной клик по этому файлу в Finder делает всё сам. Чтобы он был
# кликабельным, нужен бит выполнения:
#
#     chmod +x Запустить.command
#
# Переход в папку скрипта — чтобы файл работал из любого места, куда
# положили проект.
cd "$(dirname "$0")" || exit 1

# На маке `python` нередко отсутствует вовсе, есть только `python3`.
PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
    echo
    echo "  Python не найден. Поставьте его с python.org."
    echo
    read -r -p "  Нажмите Enter, чтобы закрыть окно."
    exit 1
fi

echo "  Проверяю зависимости..."
"$PY" -m pip install -r requirements.txt --quiet --disable-pip-version-check

# Без списка прокси программа ругается при запуске. Кладём образец —
# адреса человек впишет сам, а падать на пустом месте она не будет.
if [ ! -f proxies.txt ] && [ -f proxies.example.txt ]; then
    cp proxies.example.txt proxies.txt
fi

echo "  Запускаю NEUROSTRAZH..."
echo
# Браузер открывает сама программа — через секунду после старта, когда
# сервер уже отвечает. Открывать его здесь значит получить вторую вкладку
# с ошибкой соединения.
"$PY" webapp/app.py

# Пауза в конце — чтобы при ошибке окно не закрылось и было видно, что
# именно случилось.
echo
read -r -p "  Нажмите Enter, чтобы закрыть окно."
