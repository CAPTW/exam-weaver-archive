@echo off
setlocal
cd /d "%~dp0"

set "PYTHONW=%~dp0.venv\Scripts\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=%~dp0..\..\.venv\Scripts\pythonw.exe"

if not exist "%PYTHONW%" (
    echo Python virtual environment was not found.
    echo Expected: %PYTHONW%
    echo.
    echo Please ask the developer to create the .venv folder first.
    pause
    exit /b 1
)

start "" "%PYTHONW%" -m src.gui.main
exit /b 0
