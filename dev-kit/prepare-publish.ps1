# Creates the publish/ folder with only the files to install in NeuroRehab.
# Includes: plugin.toml, requirements.txt, root *.py, root packages (__init__.py).
# Excludes: .venv, neurorehab_plugin, examples, scripts, caches.
#
# Usage: .\prepare-publish.ps1
# Then install publish/ in NeuroRehab (Plugins > Import plugin to database...).

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$PublishDir = Join-Path $Root "publish"

if (Test-Path $PublishDir) {
    Remove-Item -Recurse -Force $PublishDir
}
New-Item -ItemType Directory -Path $PublishDir | Out-Null

$always = @("plugin.toml")
foreach ($name in $always) {
    $source = Join-Path $Root $name
    if (-not (Test-Path $source)) {
        Write-Error "Missing file: $name"
    }
    Copy-Item $source (Join-Path $PublishDir $name)
}

$requirementsPath = Join-Path $Root "requirements.txt"
if (Test-Path $requirementsPath) {
    Copy-Item $requirementsPath (Join-Path $PublishDir "requirements.txt")
}

$entry = "main.py"
$toml = Get-Content (Join-Path $Root "plugin.toml") -Raw
if ($toml -match 'entry\s*=\s*"([^"]+)"') {
    $entry = $Matches[1]
}
$entryPath = Join-Path $Root $entry
if (-not (Test-Path $entryPath)) {
    Write-Error "Entry file not found: $entry"
}
Copy-Item $entryPath (Join-Path $PublishDir $entry)

Get-ChildItem -Path $Root -Filter "*.py" -File | ForEach-Object {
    if ($_.Name -eq $entry) { return }
    Copy-Item $_.FullName (Join-Path $PublishDir $_.Name)
}

# Root Python packages (directories with __init__.py). examples/, .venv,
# neurorehab_plugin/, publish/, and cache dirs are never published.
$skipPackageDirs = @(
    ".venv", "__pycache__", "examples", "neurorehab_plugin", "publish",
    "scripts", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"
)
function Copy-PublishTree([string]$Source, [string]$Dest) {
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Get-ChildItem -Path $Source -Force | ForEach-Object {
        if ($_.Name -eq "__pycache__" -or $_.Name -eq ".venv") { return }
        $target = Join-Path $Dest $_.Name
        if ($_.PSIsContainer) {
            Copy-PublishTree $_.FullName $target
        } else {
            Copy-Item $_.FullName $target
        }
    }
}
Get-ChildItem -Path $Root -Directory | ForEach-Object {
    if ($skipPackageDirs -contains $_.Name) { return }
    if (-not (Test-Path (Join-Path $_.FullName "__init__.py"))) { return }
    Copy-PublishTree $_.FullName (Join-Path $PublishDir $_.Name)
}

# This kit sits inside the mea_editor repo. Publish the sibling package so the
# installed plugin can launch the same local editor.
$localMea = Join-Path $Root "mea_editor\__init__.py"
if (-not (Test-Path $localMea)) {
    $siblingMea = Join-Path (Split-Path $Root -Parent) "mea_editor"
    if (Test-Path (Join-Path $siblingMea "__init__.py")) {
        Copy-PublishTree $siblingMea (Join-Path $PublishDir "mea_editor")
    }
}

# examples/ is never published (patterns for development only).

$publishedToml = Get-Content (Join-Path $PublishDir "plugin.toml") -Raw
if ($publishedToml -notmatch 'selection_mode\s*=') {
    Write-Warning "Published plugin.toml has no selection_mode: button will be hidden without a selected row (default one_or_more)."
}
if ($publishedToml -match '(?m)^\s*#\s*selection_mode\s*=') {
    Write-Warning "selection_mode is commented out in plugin.toml: uncomment before publishing."
}

Write-Host ""
Write-Host "Ready for NeuroRehab: $PublishDir"
Write-Host ""
Write-Host "Contents:"
Get-ChildItem -Path $PublishDir | ForEach-Object {
    if ($_.PSIsContainer) { Write-Host "  - $($_.Name)/" }
    else { Write-Host "  - $($_.Name)" }
}
if (Test-Path (Join-Path $PublishDir "neurorehab_plugin")) {
    Write-Error "publish/ must not contain neurorehab_plugin/ - SDK is dev-only."
}
Write-Host ""
Write-Host "Verify publish/plugin.toml (active selection_mode, correct entry)."
Write-Host "Confirm all user-visible text is in English (name, description, UI strings)."
Write-Host "Plugins > Import plugin to database... > publish/ folder or .zip of publish/."
Write-Host "Then check To install and click Apply changes on this workstation."
