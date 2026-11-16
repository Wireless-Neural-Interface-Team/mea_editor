#!/usr/bin/env bash
# Creates publish/ with only the files to install in NeuroRehab.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PUBLISH_DIR="$ROOT/publish"

rm -rf "$PUBLISH_DIR"
mkdir -p "$PUBLISH_DIR"

if [[ ! -f "$ROOT/plugin.toml" ]]; then
  echo "Missing file: plugin.toml" >&2
  exit 1
fi
cp "$ROOT/plugin.toml" "$PUBLISH_DIR/"

# Optional but recommended runtime requirements (auto plugin venv on client)
if [[ -f "$ROOT/requirements.txt" ]]; then
  cp "$ROOT/requirements.txt" "$PUBLISH_DIR/"
fi

ENTRY="main.py"
if [[ -f "$ROOT/plugin.toml" ]]; then
  MATCHED="$(grep -E '^\s*entry\s*=' "$ROOT/plugin.toml" | head -n1 | sed -E 's/.*=\s*"([^"]+)".*/\1/')"
  if [[ -n "$MATCHED" ]]; then
    ENTRY="$MATCHED"
  fi
fi

if [[ ! -f "$ROOT/$ENTRY" ]]; then
  echo "Entry file not found: $ENTRY" >&2
  exit 1
fi
cp "$ROOT/$ENTRY" "$PUBLISH_DIR/"

for py in "$ROOT"/*.py; do
  [[ -f "$py" ]] || continue
  base="$(basename "$py")"
  [[ "$base" == "$ENTRY" ]] && continue
  cp "$py" "$PUBLISH_DIR/"
done

# Root Python packages (directories with __init__.py). Skip venv/SDK/examples.
copy_publish_tree() {
  local src="$1"
  local dest="$2"
  mkdir -p "$dest"
  local entry
  for entry in "$src"/* "$src"/.[!.]* "$src"/..?*; do
    [[ -e "$entry" ]] || continue
    local name
    name="$(basename "$entry")"
    [[ "$name" == "__pycache__" || "$name" == ".venv" ]] && continue
    if [[ -d "$entry" ]]; then
      copy_publish_tree "$entry" "$dest/$name"
    else
      cp "$entry" "$dest/$name"
    fi
  done
}

for dir in "$ROOT"/*/; do
  [[ -d "$dir" ]] || continue
  base="$(basename "$dir")"
  case "$base" in
    .venv|__pycache__|examples|neurorehab_plugin|publish|scripts|.git|.pytest_cache|.mypy_cache|.ruff_cache)
      continue
      ;;
  esac
  [[ -f "$dir/__init__.py" ]] || continue
  copy_publish_tree "$dir" "$PUBLISH_DIR/$base"
done

# This kit sits inside the mea_editor repo. Publish the sibling package so the
# installed plugin can launch the same local editor.
if [[ ! -f "$ROOT/mea_editor/__init__.py" ]]; then
  sibling_mea="$(cd "$ROOT/.." && pwd)/mea_editor"
  if [[ -f "$sibling_mea/__init__.py" ]]; then
    copy_publish_tree "$sibling_mea" "$PUBLISH_DIR/mea_editor"
  fi
fi

if ! grep -qE 'selection_mode[[:space:]]*=' "$PUBLISH_DIR/plugin.toml"; then
  echo "WARNING: published plugin.toml has no selection_mode (default one_or_more)." >&2
  echo "Add selection_mode = \"optional\" if the button should stay visible without selection." >&2
elif grep -qE '^\s*#\s*selection_mode[[:space:]]*=' "$PUBLISH_DIR/plugin.toml"; then
  echo "WARNING: selection_mode is commented out in source plugin.toml." >&2
  echo "Uncomment the line before publishing." >&2
fi

echo ""
echo "Verify publish/plugin.toml (selection_mode = optional for GUI without selection)."
echo "Confirm all user-visible text is in English (name, description, UI strings)."
if [[ -d "$PUBLISH_DIR/neurorehab_plugin" ]]; then
  echo "ERROR: publish/ must not contain neurorehab_plugin/ — SDK is dev-only." >&2
  exit 1
fi
echo "Ready for NeuroRehab: $PUBLISH_DIR"
echo "Plugins > Import plugin to database… > publish/ folder (or zip of publish/)."
echo "Then check To install and click Apply changes on this workstation."
