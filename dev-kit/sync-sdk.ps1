# Copy neurorehab_plugin/ from the repository root (maintainers only).
#
# Usage: from plugins\dev-kit\  →  .\sync-sdk.ps1

$ErrorActionPreference = "Stop"
$KitRoot = $PSScriptRoot
$SdkSource = (Resolve-Path (Join-Path $KitRoot "..\..\neurorehab_plugin")).Path
$SdkTarget = Join-Path $KitRoot "neurorehab_plugin"

if (-not (Test-Path (Join-Path $SdkSource "setup.py"))) {
    Write-Error "SDK not found: $SdkSource"
}

if (Test-Path $SdkTarget) {
    Remove-Item -Recurse -Force $SdkTarget
}

Copy-Item -Recurse $SdkSource $SdkTarget
Get-ChildItem -Path $SdkTarget -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $SdkTarget -Recurse -Filter *.pyc -ErrorAction SilentlyContinue |
    Remove-Item -Force
Write-Host "SDK copied to: $SdkTarget"
