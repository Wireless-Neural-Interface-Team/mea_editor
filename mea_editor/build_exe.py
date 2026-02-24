"""
Script to build a standalone executable for the MEA Editor.

Usage:
    mea-editor-build
    # or: python -m mea_editor.build_exe

Prerequisites:
    pip install mea-editor pyinstaller

The executable will be generated in dist/ (in the current directory).
"""

import subprocess
import sys
from pathlib import Path

def main():
    output_dir = Path.cwd() / "dist"
    exe_name = "ElectrodeArrayEditor.exe" if sys.platform == "win32" else "ElectrodeArrayEditor"
    exe_path = output_dir / exe_name

    if exe_path.exists():
        try:
            exe_path.unlink()
        except PermissionError:
            print("ERROR: The executable is locked (running or in use by another program).")
            print("Close ElectrodeArrayEditor and try again.")
            sys.exit(1)

    # Module path for PyInstaller (handles relative imports)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=ElectrodeArrayEditor",
        "--windowed",
        "--onefile",
        "--clean",
        "--distpath", str(output_dir),
        "mea_editor.electrode_array_editor_qt",
    ]
    subprocess.run(cmd, check=True, cwd=Path.cwd())
    print(f"\n✓ Executable created: {exe_path}")


if __name__ == "__main__":
    main()
