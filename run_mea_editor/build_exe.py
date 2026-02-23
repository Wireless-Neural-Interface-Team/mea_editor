"""
Script to build a standalone executable for the MEA Editor (mea_editor package).

Usage:
    python run_mea_editor/build_exe.py

Prerequisites:
    pip install pyinstaller PySide6
    pip install -e .   # install mea_editor in development mode

The executable will be generated in dist/ElectrodeArrayEditor.exe
"""

import subprocess
import sys
from pathlib import Path

# run_mea_editor/ folder and project root
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent


def main():
    exe_path = PROJECT_ROOT / "dist" / "ElectrodeArrayEditor.exe"
    if exe_path.exists():
        try:
            exe_path.unlink()
        except PermissionError:
            print("ERROR: The executable is locked (running or in use by another program).")
            print("Close ElectrodeArrayEditor.exe and try again.")
            sys.exit(1)

    launcher = SCRIPT_DIR / "run_mea_editor.py"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ElectrodeArrayEditor",
        "--windowed",
        "--onefile",
        "--clean",
        str(launcher.resolve()),
    ]
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
    print(f"\n✓ Executable created: {exe_path}")


if __name__ == "__main__":
    main()
