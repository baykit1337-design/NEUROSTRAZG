@echo off
rem NEUROSTRAZH -- one-click launcher for Windows (5.1).
rem
rem ASCII ONLY. This is not a style choice. cmd.exe reads a .bat byte by
rem byte in the current OEM code page and returns to a saved byte offset
rem after every command. A non-ASCII byte here shifts that offset,
rem parsing resumes in the middle of a line, the leading "rem" is lost,
rem and the rest of a comment gets executed as a command:
rem
rem     'oshibke' is not recognized as an internal or external command
rem
rem Every Russian message lives in start.py instead. Python writes to the
rem Windows console through WriteConsoleW and does not depend on the code
rem page at all, so no chcp call is needed here either.
rem
rem Going to the script folder -- so the file works from wherever the
rem project was unpacked.
cd /d "%~dp0"

rem Windows usually ships the "py" launcher, while plain "python" may be
rem missing from PATH. Try both before giving up.
set PY=py
%PY% --version >nul 2>&1 || set PY=python
%PY% --version >nul 2>&1 || (
    echo.
    echo   Python not found. Install it from https://www.python.org
    echo   and tick "Add Python to PATH" during setup.
    echo.
    echo   Python ne nayden. Ustanovite ego s python.org i otmetite
    echo   "Add Python to PATH" pri ustanovke.
    echo.
    pause
    exit /b 1
)

rem Dependencies, proxies.txt and the server itself -- all in start.py,
rem shared with the macOS launcher.
%PY% start.py

rem The window must stay open on a failure, or the error just flashes by.
echo.
pause
