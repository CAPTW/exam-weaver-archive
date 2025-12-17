# Exam Weaver - Windows PowerShell 빌드 스크립트
# 실행: powershell -ExecutionPolicy Bypass -File build-windows.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Exam Weaver - Windows 빌드 스크립트" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Node.js 설치 확인
try {
    $nodeVersion = node -v
    Write-Host "[정보] Node.js 버전: $nodeVersion" -ForegroundColor Green
} catch {
    Write-Host "[오류] Node.js가 설치되어 있지 않습니다." -ForegroundColor Red
    Write-Host "https://nodejs.org/ 에서 Node.js LTS를 설치해주세요." -ForegroundColor Yellow
    Read-Host "Enter 키를 눌러 종료"
    exit 1
}

# npm 버전 확인
$npmVersion = npm -v
Write-Host "[정보] npm 버전: $npmVersion" -ForegroundColor Green
Write-Host ""

# 빌드 유형 선택
Write-Host "빌드 유형을 선택하세요:" -ForegroundColor Yellow
Write-Host "  1. Portable (설치 불필요, 단일 exe)" -ForegroundColor White
Write-Host "  2. Installer (설치 프로그램)" -ForegroundColor White
Write-Host "  3. 둘 다" -ForegroundColor White
Write-Host ""
$buildType = Read-Host "선택 (1/2/3, 기본값: 1)"
if ([string]::IsNullOrEmpty($buildType)) { $buildType = "1" }

# 의존성 설치
Write-Host ""
Write-Host "[1/4] 의존성 설치 중..." -ForegroundColor Cyan
npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] 의존성 설치 실패" -ForegroundColor Red
    exit 1
}

# 웹 빌드
Write-Host ""
Write-Host "[2/4] 웹 앱 빌드 중..." -ForegroundColor Cyan
npm run build
if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] 웹 빌드 실패" -ForegroundColor Red
    exit 1
}

# PDF.js 파일 복사
Write-Host ""
Write-Host "[3/4] PDF.js 파일 복사 중..." -ForegroundColor Cyan
npm run copy-pdfjs

# Electron 빌드
Write-Host ""
Write-Host "[4/4] Electron 앱 빌드 중..." -ForegroundColor Cyan

switch ($buildType) {
    "1" {
        npx electron-builder --win portable
    }
    "2" {
        npx electron-builder --win nsis
    }
    "3" {
        npx electron-builder --win
    }
    default {
        npx electron-builder --win portable
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "[오류] Electron 빌드 실패" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  빌드 완료!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "빌드된 파일 위치: release\" -ForegroundColor White
Write-Host ""

# 빌드 결과 표시
if (Test-Path "release") {
    Write-Host "생성된 파일:" -ForegroundColor Yellow
    Get-ChildItem -Path "release" -Filter "*.exe" | ForEach-Object {
        Write-Host "  - $($_.Name)" -ForegroundColor White
    }
}

Write-Host ""
Read-Host "Enter 키를 눌러 종료"
