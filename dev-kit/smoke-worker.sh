#!/usr/bin/env bash
# Smoke test: load the plugin entry in an isolated worker subprocess.
# Usage: chmod +x smoke-worker.sh && ./smoke-worker.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VENV_PYTHON="$ROOT/.venv/bin/python"
ENTRY="${ENTRY:-}"
PLUGIN_ID="${PLUGIN_ID:-}"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing .venv/. Run ./setup-dev.sh first." >&2
  exit 1
fi

if [[ ! -f "$ROOT/plugin.toml" ]]; then
  echo "Missing plugin.toml" >&2
  exit 1
fi

if [[ -z "$PLUGIN_ID" ]]; then
  PLUGIN_ID="$(sed -n 's/^id[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$ROOT/plugin.toml" | head -n 1)"
fi
if [[ -z "$ENTRY" ]]; then
  ENTRY="$(sed -n 's/^entry[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$ROOT/plugin.toml" | head -n 1)"
fi
if [[ -z "$PLUGIN_ID" || -z "$ENTRY" ]]; then
  echo "Could not resolve plugin id/entry from plugin.toml." >&2
  exit 1
fi
if [[ ! -f "$ROOT/$ENTRY" ]]; then
  echo "Entry file not found: $ENTRY" >&2
  exit 1
fi

export NR_SDK_ROOT="$ROOT"
export NR_PLUGIN_ROOT="$ROOT"
export NR_PLUGINS_ROOT="$ROOT"
export NR_PLUGIN_PYTHON="$VENV_PYTHON"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1

PYSIDE="$("$VENV_PYTHON" -c "import PySide6, os; print(os.path.dirname(PySide6.__file__))" 2>/dev/null || true)"
if [[ -n "$PYSIDE" ]]; then
  export NR_HOST_PYSIDE_PATH="$PYSIDE"
  export PYTHONPATH="$ROOT:$PYSIDE"
fi

"$VENV_PYTHON" - <<'PY' "$ROOT" "$VENV_PYTHON" "$ENTRY" "$PLUGIN_ID"
import json, os, subprocess, sys
from pathlib import Path

root = Path(sys.argv[1])
venv_py = Path(sys.argv[2])
entry = root / sys.argv[3]
plugin_id = sys.argv[4]
env = dict(os.environ)
proc = subprocess.Popen(
    [str(venv_py), "-m", "neurorehab_plugin.worker_main"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    cwd=str(root),
    env=env,
)
ready = json.loads(proc.stdout.readline())
if ready.get("event") != "ready":
    raise SystemExit(f"Worker failed to start: {ready}")
proc.stdin.write(json.dumps({
    "id": 1,
    "op": "configure",
    "plugin_id": plugin_id,
    "entry_path": str(entry),
}) + "\n")
proc.stdin.flush()
resp = json.loads(proc.stdout.readline())
if not resp.get("ok"):
    sys.stderr.write((resp.get("traceback") or resp.get("error") or "configure failed") + "\n")
    raise SystemExit(1)
proc.stdin.write(json.dumps({"id": 0, "op": "shutdown"}) + "\n")
proc.stdin.flush()
proc.wait(timeout=10)
err = proc.stderr.read().strip()
if err:
    print(err, file=sys.stderr)
print("OK")
PY

echo "Worker smoke test OK: $PLUGIN_ID -> $ENTRY"
