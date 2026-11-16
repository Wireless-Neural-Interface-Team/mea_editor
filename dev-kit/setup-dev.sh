#!/usr/bin/env bash
# Isolated dev environment — Python downloaded into the project.
# Usage: chmod +x setup-dev.sh && ./setup-dev.sh

set -euo pipefail
PLUGIN_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PLUGIN_ROOT"

PYTHON_VERSION="${PYTHON_VERSION:-3.11.7}"
SDK_PATH="${SDK_PATH:-$PLUGIN_ROOT/neurorehab_plugin}"

if [[ ! -f "$SDK_PATH/setup.py" ]]; then
  echo "SDK not found: $SDK_PATH" >&2
  exit 1
fi

TOOLS_DIR="$PLUGIN_ROOT/tools"
UV_BIN="$TOOLS_DIR/uv"
UV_VERSION="0.6.14"

if [[ ! -x "$UV_BIN" ]]; then
  mkdir -p "$TOOLS_DIR"
  ARCH="$(uname -m)"
  OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
  case "$ARCH-$OS" in
    x86_64-linux|amd64-linux)
      UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
      ;;
    arm64-darwin|aarch64-darwin)
      UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-aarch64-apple-darwin.tar.gz"
      ;;
    x86_64-darwin)
      UV_URL="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-x86_64-apple-darwin.tar.gz"
      ;;
    *)
      echo "Unsupported platform: $ARCH $OS" >&2
      exit 1
      ;;
  esac
  echo "Downloading uv ($UV_VERSION)..."
  curl -fsSL "$UV_URL" -o "$TOOLS_DIR/uv.tar.gz"
  tar -xzf "$TOOLS_DIR/uv.tar.gz" -C "$TOOLS_DIR"
  rm -f "$TOOLS_DIR/uv.tar.gz"
  chmod +x "$UV_BIN"
fi

export UV_PYTHON_INSTALL_DIR="$PLUGIN_ROOT/.python"
export UV_CACHE_DIR="$PLUGIN_ROOT/.uv-cache"
VENV_PYTHON="$PLUGIN_ROOT/.venv/bin/python"

echo "Installing Python $PYTHON_VERSION in .python/ ..."
"$UV_BIN" python install "$PYTHON_VERSION"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Creating .venv/ with this Python..."
  "$UV_BIN" venv .venv --python "$PYTHON_VERSION"
else
  echo ".venv/ already exists."
fi

echo "Installing dev dependencies (requirements-dev.txt) in .venv/ ..."
"$UV_BIN" pip install --python "$VENV_PYTHON" -r requirements-dev.txt

echo ""
echo "Ready."
echo "  Python: .venv/bin/python"
echo "  Activate: source .venv/bin/activate"
echo "  Worker smoke test: ./smoke-worker.sh"
echo "  Guide: GUIDE.md"
echo "  Publish: ./prepare-publish.sh"
