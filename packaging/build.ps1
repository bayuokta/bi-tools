<#
.SYNOPSIS
    Build paket BI Tools (PyInstaller onedir + installer Inno Setup + ZIP portable).

.DESCRIPTION
    Jalur build lokal yang sama dengan .github\workflows\release.yml. Versi
    dibaca dari core\version.py (satu sumber kebenaran) dan diteruskan ke
    Inno Setup lewat /DMyAppVersion.

.EXAMPLE
    powershell -File packaging\build.ps1
    powershell -File packaging\build.ps1 -SkipTests
    powershell -File packaging\build.ps1 -SkipInstaller    # hanya dist + zip
#>
[CmdletBinding()]
param(
    [string]$Version = "",
    [switch]$SkipTests,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

function Invoke-Step {
    param([string]$Title, [scriptblock]$Action)
    Write-Host ""
    Write-Host "== $Title" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "Langkah gagal: $Title (exit $LASTEXITCODE)"
    }
}

# --- Versi ---------------------------------------------------------------
$versionFile = Join-Path $RepoRoot "core\version.py"
$match = [regex]::Match((Get-Content $versionFile -Raw), '__version__\s*=\s*"([^"]+)"')
if (-not $match.Success) {
    throw "Tidak menemukan __version__ di core\version.py"
}
$declared = $match.Groups[1].Value
if ($Version -and $Version -ne $declared) {
    throw "Versi -Version ($Version) berbeda dengan core\version.py ($declared)"
}
$Version = $declared
Write-Host "Versi aplikasi: $Version" -ForegroundColor Green

# --- Prasyarat -----------------------------------------------------------
Invoke-Step "Periksa PyInstaller" {
    python -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"
}

if (-not $SkipTests) {
    Invoke-Step "Jalankan uji" {
        python -m unittest discover -s tests -t .
    }
}

# --- Build PyInstaller ---------------------------------------------------
foreach ($path in @("build", "dist")) {
    if (Test-Path $path) { Remove-Item $path -Recurse -Force }
}

# Installer lama dari build sebelumnya tidak boleh terbawa ke daftar artefak.
$installer = Join-Path $RepoRoot "packaging\Output\BITools-Setup-$Version.exe"
if (Test-Path $installer) { Remove-Item $installer -Force }

Invoke-Step "PyInstaller (spec onedir)" {
    python -m PyInstaller --noconfirm --clean packaging\bi_tools.spec
}

$appDir = Join-Path $RepoRoot "dist\BI Tools"
foreach ($required in @("BI Tools.exe", "bi-tools-cli.exe", "web\index.html", "web\app.js", "templates\tsd.template.html", "libs")) {
    if (-not (Test-Path (Join-Path $appDir $required))) {
        throw "Hasil build tidak lengkap: dist\BI Tools\$required"
    }
}
Write-Host "Folder aplikasi siap: $appDir" -ForegroundColor Green

# --- ZIP portable --------------------------------------------------------
$portable = Join-Path $RepoRoot "dist\BITools-$Version-portable.zip"
Invoke-Step "ZIP portable" {
    if (Test-Path $portable) { Remove-Item $portable -Force }
    # outputs/data/TSD_assets dibuat saat runtime; jangan ikut ke paket walau
    # folder dist pernah dipakai menjalankan aplikasi.
    $runtimeDirs = @("outputs", "data", "TSD_assets")
    $items = Get-ChildItem $appDir | Where-Object { $_.Name -notin $runtimeDirs }
    Compress-Archive -Path $items.FullName -DestinationPath $portable -CompressionLevel Optimal
}

# --- Wheel bitools-sync --------------------------------------------------
Invoke-Step "Wheel bitools-sync" {
    python -m pip wheel . --no-deps -w (Join-Path $RepoRoot "dist")
}
$wheel = Get-ChildItem (Join-Path $RepoRoot "dist") -Filter "bitools_sync-$Version-*.whl" |
    Select-Object -First 1
if (-not $wheel) { throw "Wheel bitools_sync tidak terbentuk" }

# --- Installer Inno Setup ------------------------------------------------
$isccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
)
$iscc = $env:BI_TOOLS_ISCC
if (-not ($iscc -and (Test-Path $iscc))) {
    $iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ($SkipInstaller) {
    Write-Host "Installer dilewati (-SkipInstaller)." -ForegroundColor Yellow
} elseif (-not $iscc) {
    Write-Host "ISCC.exe tidak ditemukan; installer dilewati." -ForegroundColor Yellow
    Write-Host "Pasang Inno Setup 6: winget install JRSoftware.InnoSetup" -ForegroundColor Yellow
} else {
    Invoke-Step "Installer Inno Setup" {
        & $iscc "/DMyAppVersion=$Version" (Join-Path $RepoRoot "packaging\bi-tools.iss")
    }
}

# --- Checksum ------------------------------------------------------------
$artifacts = @()
if (Test-Path $installer) { $artifacts += $installer }
if (Test-Path $portable) { $artifacts += $portable }
if ($wheel) { $artifacts += $wheel.FullName }

if ($artifacts.Count -gt 0) {
    $lines = foreach ($file in $artifacts) {
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $(Split-Path -Leaf $file)"
    }
    $sums = Join-Path $RepoRoot "dist\SHA256SUMS.txt"
    # Windows PowerShell 5.1 tidak mengenal -Encoding utf8NoBOM; tulis manual
    # agar build lokal dan pwsh menghasilkan checksum UTF-8 tanpa BOM.
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($sums, [string[]]$lines, $utf8NoBom)
    Write-Host "Checksum: $sums" -ForegroundColor Green
}

Write-Host ""
Write-Host "Selesai. Artefak:" -ForegroundColor Green
foreach ($file in $artifacts) {
    $size = "{0:N1} MB" -f ((Get-Item $file).Length / 1MB)
    Write-Host ("  {0}  ({1})" -f $file.Replace("$RepoRoot\", ""), $size)
}
