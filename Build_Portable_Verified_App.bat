@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%PYTHON%" (
    echo Python virtual environment was not found.
    echo Expected: %PYTHON%
    echo.
    echo Please ask the developer to create the .venv folder first.
    pause
    exit /b 1
)

echo [1/2] Running tests before packaging...
"%PYTHON%" -m pytest -q
if errorlevel 1 (
    echo.
    echo Tests failed. Packaging was stopped.
    pause
    exit /b 1
)

echo.
echo [2/2] Building portable ZIP with the latest audited DB...
taskkill /IM ExamGenerator.exe /F >nul 2>nul
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_exe.ps1" -UseLatestAuditDb -IsolatedDist
if errorlevel 1 (
    echo.
    echo Portable packaging failed.
    pause
    exit /b 1
)

echo.
echo Portable packaging completed.
pause
exit /b 0
