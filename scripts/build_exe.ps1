param(
    [switch]$NoZip,
    [switch]$SkipDependencyInstall,
    [switch]$SkipDataCopy,
    [string]$PortableDbPath,
    [switch]$UseLatestAuditDb,
    [switch]$IsolatedDist,
    [switch]$AllowMissingImages,
    [switch]$GithubPortable,
    [string]$ZipName
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
$appName = "ExamGenerator"
$distDir = Join-Path $repoRoot "dist"
$sourceDataDir = Join-Path $repoRoot "data"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$zipFileName = if ([string]::IsNullOrWhiteSpace($ZipName)) {
    if ($GithubPortable) {
        "{0}_github_portable_{1}.zip" -f $appName, $timestamp
    } else {
        "{0}_portable_{1}.zip" -f $appName, $timestamp
    }
} else {
    $ZipName
}
$zipPath = Join-Path $distDir $zipFileName
$pyinstallerWorkDir = Join-Path $repoRoot ("tmp\pyinstaller_work_{0}" -f $timestamp)
$pyinstallerDistDir = if ($IsolatedDist) {
    Join-Path $distDir ("{0}_build_{1}" -f $appName, $timestamp)
} else {
    $distDir
}
$appDistDir = Join-Path $pyinstallerDistDir $appName
$launcherPath = Join-Path $appDistDir "Run_ExamGenerator.bat"
$readmePath = Join-Path $appDistDir "README_PORTABLE.txt"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [Parameter(Mandatory=$true)][string]$Description
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path $python)) {
    Write-Error "Virtualenv not found at $python"
    exit 1
}

Push-Location $repoRoot
try {
    Get-Process -Name $appName -ErrorAction SilentlyContinue | Stop-Process -Force

    if (-not $SkipDependencyInstall) {
        Write-Host "[1/4] Installing build dependencies..."
        Invoke-CheckedCommand -FilePath $python -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Description "pip upgrade"
        Invoke-CheckedCommand -FilePath $python -Arguments @("-m", "pip", "install", "-r", "requirements.txt", "pyinstaller") -Description "dependency install"
    }

    Write-Host "[2/4] Building executable with PyInstaller spec..."
    Invoke-CheckedCommand -FilePath $python -Arguments @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath", $pyinstallerWorkDir,
        "--distpath", $pyinstallerDistDir,
        "ExamGenerator.spec"
    ) -Description "PyInstaller build"

    if (-not (Test-Path $appDistDir)) {
        throw "Build output not found: $appDistDir"
    }

    Write-Host "[3/4] Preparing portable folder..."
    if ($GithubPortable) {
        $SkipDataCopy = $true
    }

    if (-not $SkipDataCopy) {
        if ([string]::IsNullOrWhiteSpace($PortableDbPath) -and $UseLatestAuditDb) {
            $latestAuditDb = Get-ChildItem -Path (Join-Path $repoRoot "tmp") -Recurse -Filter "staging_exam_bank.db" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending |
                Select-Object -First 1
            if ($null -eq $latestAuditDb) {
                throw "No audited staging DB found under tmp."
            }
            $PortableDbPath = $latestAuditDb.FullName
        }
        if ([string]::IsNullOrWhiteSpace($PortableDbPath)) {
            $PortableDbPath = Join-Path $sourceDataDir "exam_bank.db"
        }
        if (-not (Test-Path $PortableDbPath)) {
            throw "Portable DB not found: $PortableDbPath"
        }

        $targetDataDir = Join-Path $appDistDir "data"
        if (Test-Path $targetDataDir) {
            Remove-Item $targetDataDir -Recurse -Force
        }

        $prepareScript = Join-Path $repoRoot "scripts\prepare_portable_data.py"
        $prepareArgs = @(
            $prepareScript,
            "--source-db", $PortableDbPath,
            "--target-data-dir", $targetDataDir,
            "--repo-root", $repoRoot
        )
        if ($AllowMissingImages) {
            $prepareArgs += "--allow-missing-images"
        }

        Invoke-CheckedCommand -FilePath $python -Arguments $prepareArgs -Description "portable data preparation"
    } else {
        $targetDataDir = Join-Path $appDistDir "data"
        New-Item -ItemType Directory -Force -Path $targetDataDir | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $targetDataDir "clipboard_images") | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $targetDataDir "exports") | Out-Null
    }

    $launcherContent = @"
@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0ExamGenerator.exe"
"@
    Set-Content -Path $launcherPath -Value $launcherContent -Encoding ASCII

    if ($GithubPortable) {
        $readmeContent = @"
기출문제 문제은행 관리자 Portable

실행 방법
1. 이 ZIP 파일을 원하는 폴더에 압축 해제합니다.
2. Run_ExamGenerator.bat 또는 ExamGenerator.exe를 실행합니다.
3. Python, pip, 가상환경 설정은 필요하지 않습니다.

데이터베이스
- 이 GitHub portable build에는 실제 문제은행 DB가 포함되어 있지 않습니다.
- 첫 실행 시 data\exam_bank.db가 빈 SQLite DB로 생성됩니다.
- 문제풀이/시험지 출력 화면의 Exam 목록은 실제 문제가 import되거나 DB가 연결된 뒤 표시됩니다.
- 운영 문제은행 DB를 가진 사용자는 앱의 DB Mount/Import 기능 또는 별도 배포 지침에 따라 로컬 DB를 연결해야 합니다.

Codex 패널
- Codex SDK 실행 파일은 함께 번들되어 있습니다.
- 개인 인증은 포함하지 않습니다.
- 각 사용자는 앱에서 Codex > 로그인 버튼을 눌러 자기 계정으로 연결합니다.
- 로그인 정보는 이 portable 폴더의 data\codex_panel_home 아래에만 저장됩니다.

Build timestamp: $timestamp
Build type: GitHub portable, no question DB
"@
    } else {
        $readmeContent = @"
ExamGenerator Portable

1. Run Run_ExamGenerator.bat (or ExamGenerator.exe).
2. Keep the data folder in the same directory as ExamGenerator.exe.
3. data\seed_exam_bank.db is the factory database shipped with this build.
4. data\exam_bank.db is the writable user database used by the app.
5. If data\exam_bank.db is missing, the app recreates it from seed_exam_bank.db.
6. Images referenced by the DB are stored under data\portable_images.
7. The Codex side panel is bundled through openai-codex. No personal auth is
   shipped with the app. Each user can open Codex > 로그인 to connect their
   own account; local auth is stored under data\codex_panel_home.

Build timestamp: $timestamp
Source DB: $PortableDbPath
"@
    }
    Set-Content -Path $readmePath -Value $readmeContent -Encoding UTF8

    if (-not $NoZip) {
        Write-Host "[4/4] Creating portable ZIP package..."
        if (Test-Path $zipPath) {
            Remove-Item $zipPath -Force
        }
        Compress-Archive -Path $appDistDir -DestinationPath $zipPath -Force
        Write-Host "Portable ZIP created: $zipPath"
    } else {
        Write-Host "[4/4] ZIP step skipped (-NoZip)."
    }

    Write-Host "Portable folder ready: $appDistDir"
}
finally {
    Pop-Location
}
