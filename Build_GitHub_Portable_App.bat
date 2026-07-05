@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
set "POWERSHELL_EXE=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"

if not exist "%PYTHON%" (
    echo Python virtual environment was not found.
    echo Expected: %PYTHON%
    echo.
    echo This build helper is for maintainers. End users should download the
    echo portable ZIP from GitHub Releases and run Run_ExamGenerator.bat.
    pause
    exit /b 1
)

echo [1/2] Running portable/repository tests...
"%PYTHON%" -m pytest -q tests\test_repository.py tests\test_export_interface.py tests\test_practice_interface.py tests\test_runtime_paths.py tests\test_launchers.py
if errorlevel 1 (
    echo.
    echo Tests failed. Packaging was stopped.
    pause
    exit /b 1
)

echo.
echo [2/2] Building GitHub portable ZIP without a question DB...
taskkill /IM ExamGenerator.exe /F >nul 2>nul
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_exe.ps1" -GithubPortable -IsolatedDist
if errorlevel 1 (
    echo.
    echo GitHub portable packaging failed.
    pause
    exit /b 1
)

echo.
echo GitHub portable packaging completed. Check the dist folder for the ZIP.
pause
exit /b 0
