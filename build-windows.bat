@echo off
chcp 65001 > nul
echo.
echo ========================================
echo   Exam Weaver - Windows 빌드 스크립트
echo ========================================
echo.

:: Node.js 설치 확인
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [오류] Node.js가 설치되어 있지 않습니다.
    echo https://nodejs.org/ 에서 Node.js LTS를 설치해주세요.
    pause
    exit /b 1
)

:: npm 버전 확인
echo [정보] Node.js 버전:
node -v
echo [정보] npm 버전:
npm -v
echo.

:: 의존성 설치
echo [1/3] 의존성 설치 중...
call npm install
if %errorlevel% neq 0 (
    echo [오류] 의존성 설치 실패
    pause
    exit /b 1
)
echo.

:: 웹 빌드
echo [2/3] 웹 앱 빌드 중...
call npm run build
if %errorlevel% neq 0 (
    echo [오류] 웹 빌드 실패
    pause
    exit /b 1
)
echo.

:: PDF.js 파일 복사
echo [2.5/3] PDF.js 파일 복사 중...
call npm run copy-pdfjs
echo.

:: Electron 빌드 (Portable)
echo [3/3] Windows Portable 앱 빌드 중...
call npx electron-builder --win portable
if %errorlevel% neq 0 (
    echo [오류] Electron 빌드 실패
    pause
    exit /b 1
)

echo.
echo ========================================
echo   빌드 완료!
echo ========================================
echo.
echo 빌드된 파일 위치: release\
echo Portable 실행 파일: Exam Weaver-*-Portable.exe
echo.
echo 설치 프로그램을 만들려면 다음 명령을 실행하세요:
echo   npm run electron:build
echo.
pause
