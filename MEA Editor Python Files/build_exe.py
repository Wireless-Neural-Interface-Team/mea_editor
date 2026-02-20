"""
Script to build a standalone executable for the electrode_matrix editor.

Usage:
    python build_exe.py

Prerequisites:
    pip install pyinstaller PySide6

The executable will be generated in dist/ElectrodeMatrixEditor.exe
"""

import os
import subprocess
import sys
from pathlib import Path

# Script directory (Projet Mapping MEA)
SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(SCRIPT_DIR)


def main():
    exe_path = SCRIPT_DIR / "dist" / "ElectrodeMatrixEditor.exe"
    if exe_path.exists():
        try:
            exe_path.unlink()
        except PermissionError:
            print("ERROR: The executable is locked (running or in use by another program).")
            print("Close ElectrodeMatrixEditor.exe and try again.")
            sys.exit(1)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ElectrodeMatrixEditor",
        "--windowed",
        "--onefile",
        "--clean",
        "electrode_matrix_editor_qt.py",
    ]
    subprocess.run(cmd, check=True)
    print(f"\n✓ Executable created: {exe_path}")


if __name__ == "__main__":
    main()
