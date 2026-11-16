#!/usr/bin/env bash
# Copy neurorehab_plugin/ from the repository root (maintainers only).
#
# Usage: from plugins/dev-kit/  →  ./sync-sdk.sh

set -euo pipefail
KIT_ROOT="$(cd "$(dirname "$0")" && pwd)"
SDK_SOURCE="$(cd "$KIT_ROOT/../../neurorehab_plugin" && pwd)"
SDK_TARGET="$KIT_ROOT/neurorehab_plugin"

if [[ ! -f "$SDK_SOURCE/setup.py" ]]; then
  echo "SDK not found: $SDK_SOURCE" >&2
  exit 1
fi

rm -rf "$SDK_TARGET"
cp -R "$SDK_SOURCE" "$SDK_TARGET"
find "$SDK_TARGET" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$SDK_TARGET" -type f -name '*.pyc' -delete
echo "SDK copied to: $SDK_TARGET"
