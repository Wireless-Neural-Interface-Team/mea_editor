# Smoke test: load the plugin entry in an isolated worker subprocess.
# Same runtime model as the NeuroRehab desktop client (venv worker).
#
# Usage:
#   .\setup-dev.ps1          # first time
#   .\smoke-worker.ps1
#   .\smoke-worker.ps1 -Entry main.py -PluginId my_plugin

param(
    [string]$Entry = "",
    [string]$PluginId = ""
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Missing .venv/. Run .\setup-dev.ps1 first."
}

$tomlPath = Join-Path $Root "plugin.toml"
if (-not (Test-Path $tomlPath)) {
    Write-Error "Missing plugin.toml in $Root"
}

$toml = Get-Content $tomlPath -Raw
if (-not $PluginId -and $toml -match 'id\s*=\s*"([^"]+)"') {
    $PluginId = $Matches[1]
}
if (-not $Entry -and $toml -match 'entry\s*=\s*"([^"]+)"') {
    $Entry = $Matches[1]
}
if (-not $PluginId -or -not $Entry) {
    Write-Error "Could not resolve plugin id/entry from plugin.toml."
}

$entryPath = Join-Path $Root $Entry
if (-not (Test-Path $entryPath)) {
    Write-Error "Entry file not found: $Entry"
}

$env:NR_SDK_ROOT = $Root
$env:NR_PLUGIN_ROOT = $Root
$env:NR_PLUGINS_ROOT = $Root
$env:NR_PLUGIN_PYTHON = $VenvPython
$env:PYTHONPATH = $Root
$env:PYTHONUNBUFFERED = "1"

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$pyside = & $VenvPython -c "import PySide6; import os; print(os.path.dirname(PySide6.__file__))" 2>$null
$pysideOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEap
if ($pysideOk -and $pyside) {
    $env:NR_HOST_PYSIDE_PATH = ($pyside | Out-String).Trim()
    $env:PYTHONPATH = "$Root;$($env:NR_HOST_PYSIDE_PATH)"
}

$pyCode = @"
import json, os, subprocess, sys
from pathlib import Path

root = Path(r'$Root')
venv_py = Path(r'$VenvPython')
entry = root / r'$Entry'
env = dict(os.environ)
proc = subprocess.Popen(
    [str(venv_py), '-m', 'neurorehab_plugin.worker_main'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    cwd=str(root),
    env=env,
)
ready = json.loads(proc.stdout.readline())
if ready.get('event') != 'ready':
    raise SystemExit(f'Worker failed to start: {ready}')
proc.stdin.write(json.dumps({
    'id': 1,
    'op': 'configure',
    'plugin_id': r'$PluginId',
    'entry_path': str(entry),
}) + '\n')
proc.stdin.flush()
resp = json.loads(proc.stdout.readline())
if not resp.get('ok'):
    sys.stderr.write((resp.get('traceback') or resp.get('error') or 'configure failed') + '\n')
    raise SystemExit(1)
proc.stdin.write(json.dumps({'id': 0, 'op': 'shutdown'}) + '\n')
proc.stdin.flush()
proc.wait(timeout=10)
err = proc.stderr.read().strip()
if err:
    print(err, file=sys.stderr)
print('OK')
"@

$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $VenvPython -c $pyCode
$smokeCode = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($smokeCode -ne 0) {
    Write-Error "Worker smoke test failed for $PluginId ($Entry)."
}

Write-Host "Worker smoke test OK: $PluginId -> $Entry"
