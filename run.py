"""
Launch the MEA Editor. Run from project root: python run.py

An optional JSON path opens that local file. Save stays on disk.
"""
import sys

from mea_editor.electrode_array_editor_qt import run_app

if __name__ == "__main__":
    run_app(sys.argv[1] if len(sys.argv) > 1 else None)
