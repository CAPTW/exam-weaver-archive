@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHONW=%~dp0.venv\Scripts\pythonw.exe"

if not exist "%PYTHONW%" (
    set "GIT_COMMON="
    for /f "delims=" %%G in ('git -C "%~dp0." rev-parse --git-common-dir 2^>nul') do set "GIT_COMMON=%%G"
    if defined GIT_COMMON (
        for %%G in ("!GIT_COMMON!") do set "GIT_COMMON_ABS=%%~fG"
        for %%G in ("!GIT_COMMON_ABS!\..") do set "REPO_ROOT=%%~fG"
        set "PYTHONW=!REPO_ROOT!\.venv\Scripts\pythonw.exe"
    )
)

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
