# Isolated dev environment — Python downloaded into the project (no system install required).
#
# Usage: .\setup-dev.ps1
# Python installed in .python/; virtual environment in .venv/

param(
    [string]$SdkPath = (Join-Path $PSScriptRoot "neurorehab_plugin"),
    [string]$PythonVersion = "3.11.7"
)

$ErrorActionPreference = "Stop"
$PluginRoot = $PSScriptRoot
Set-Location $PluginRoot

if (-not (Test-Path (Join-Path $SdkPath "setup.py"))) {
    Write-Error @"
SDK not found: $SdkPath
The neurorehab_plugin/ folder must be next to this script (all-in-one kit).
"@
}

function Get-UvExecutable {
    $toolsDir = Join-Path $PluginRoot "tools"
    $uvExe = Join-Path $toolsDir "uv.exe"
    if (Test-Path $uvExe) {
        return $uvExe
    }

    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $zipPath = Join-Path $toolsDir "uv.zip"
    $uvVersion = "0.6.14"
    $uvUrl = "https://github.com/astral-sh/uv/releases/download/$uvVersion/uv-x86_64-pc-windows-msvc.zip"

    Write-Host "Downloading uv ($uvVersion)..."
    Invoke-WebRequest -Uri $uvUrl -OutFile $zipPath -UseBasicParsing
    Expand-Archive -Path $zipPath -DestinationPath $toolsDir -Force
    Remove-Item $zipPath -Force

    if (-not (Test-Path $uvExe)) {
        Write-Error "uv.exe not found after extraction in $toolsDir"
    }
    return $uvExe
}

$uv = Get-UvExecutable
$pythonHome = Join-Path $PluginRoot ".python"
$uvCache = Join-Path $PluginRoot ".uv-cache"
$venvPython = Join-Path $PluginRoot ".venv\Scripts\python.exe"

$env:UV_PYTHON_INSTALL_DIR = $pythonHome
$env:UV_CACHE_DIR = $uvCache

Write-Host "Installing Python $PythonVersion in .python/ ..."
# uv writes progress to stderr; exit code is the authority.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $uv python install $PythonVersion
    if ($LASTEXITCODE -ne 0) {
        Write-Error "uv python install failed with exit $LASTEXITCODE"
    }

    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating .venv/ with this Python..."
        & $uv venv .venv --python $PythonVersion
        if ($LASTEXITCODE -ne 0) {
            Write-Error "uv venv failed with exit $LASTEXITCODE"
        }
    } else {
        Write-Host ".venv/ already exists."
    }

    Write-Host "Installing dev dependencies (requirements-dev.txt) in .venv/ ..."
    & $uv pip install --python $venvPython -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "uv pip install failed with exit $LASTEXITCODE"
    }
} finally {
    $ErrorActionPreference = $prevEap
}

Write-Host ""
Write-Host "Ready."
Write-Host "  Python: .venv\Scripts\python.exe"
Write-Host "  Activate: .\.venv\Scripts\Activate.ps1"
Write-Host "  Worker smoke test: .\smoke-worker.ps1"
Write-Host "  Guide: GUIDE.md"
Write-Host "  Publish: .\prepare-publish.ps1"
