param(
    [switch]$NoZip,
    [switch]$SkipDependencyInstall,
    [switch]$SkipDataCopy,
    [string]$PortableDbPath,
    [switch]$UseLatestAuditDb,
    [switch]$IsolatedDist,
    [switch]$AllowMissingImages
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$python = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
$appName = "ExamGenerator"
$distDir = Join-Path $repoRoot "dist"
$sourceDataDir = Join-Path $repoRoot "data"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$zipPath = Join-Path $distDir ("{0}_portable_{1}.zip" -f $appName, $timestamp)
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
    }

    $launcherContent = @"
@echo off
setlocal
cd /d "%~dp0"
start "" "%~dp0ExamGenerator.exe"
"@
    Set-Content -Path $launcherPath -Value $launcherContent -Encoding ASCII

    $readmeContent = @"
ExamGenerator Portable

1. Run Run_ExamGenerator.bat (or ExamGenerator.exe).
2. Keep the data folder in the same directory as ExamGenerator.exe.
3. data\seed_exam_bank.db is the factory database shipped with this build.
4. data\exam_bank.db is the writable user database used by the app.
5. If data\exam_bank.db is missing, the app recreates it from seed_exam_bank.db.
6. Images referenced by the DB are stored under data\portable_images.

Build timestamp: $timestamp
Source DB: $PortableDbPath
"@
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
