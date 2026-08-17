@echo off
rem NEUROSTRAZH — запуск одним файлом (5.1 ТЗ).
rem
rem Кодовая страница 65001 — чтобы русские буквы в консоли не превратились
rem в кашу. Переход в папку скрипта — чтобы файл работал из любого места,
rem куда положили проект.
chcp 65001 >nul
cd /d "%~dp0"

rem На Windows питон чаще ставится вместе с лаунчером `py`, а `python` в
rem PATH может и не оказаться — пробуем оба, иначе человек видит невнятное
rem «не является внутренней или внешней командой».
set PY=py
%PY% --version >nul 2>&1 || set PY=python
%PY% --version >nul 2>&1 || (
    echo.
    echo   Python не найден. Поставьте его с python.org
    echo   и при установке отметьте "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo   Проверяю зависимости...
%PY% -m pip install -r requirements.txt --quiet --disable-pip-version-check

rem Без списка прокси программа ругается при запуске. Кладём образец —
rem адреса человек впишет сам, а падать на пустом месте она не будет.
if not exist proxies.txt (
    if exist proxies.example.txt copy proxies.example.txt proxies.txt >nul
)

echo   Запускаю NEUROSTRAZH...
echo.
rem Браузер открывает сама программа — через секунду после старта, когда
rem сервер уже отвечает. Открывать его здесь значит получить вторую
rem вкладку с ошибкой соединения.
%PY% webapp/app.py

rem Пауза в конце — чтобы при ошибке окно не закрылось и было видно, что
rem именно случилось.
echo.
pause
