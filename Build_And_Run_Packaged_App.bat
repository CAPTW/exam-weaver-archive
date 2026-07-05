@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=%~dp0..\..\.venv\Scripts\python.exe"
set "PACKAGED_EXE=%~dp0dist\ExamGenerator\ExamGenerator.exe"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%PYTHON%" (
    echo Python virtual environment was not found.
    echo Expected: %PYTHON%
    echo.
    echo Please ask the developer to create the .venv folder first.
    pause
    exit /b 1
)

echo [1/3] Running tests before packaging...
"%PYTHON%" -m pytest -q
if errorlevel 1 (
    echo.
    echo Tests failed. Packaging was stopped.
    pause
    exit /b 1
)

echo.
echo [2/3] Building packaged app from the latest source code...
taskkill /IM ExamGenerator.exe /F >nul 2>nul
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_exe.ps1" -NoZip
if errorlevel 1 (
    echo.
    echo Packaging failed.
    pause
    exit /b 1
)

if not exist "%PACKAGED_EXE%" (
    echo.
    echo Packaged app was not found.
    echo Expected: %PACKAGED_EXE%
    pause
    exit /b 1
)

echo.
echo [3/3] Starting packaged app...
start "" "%PACKAGED_EXE%"
exit /b 0
