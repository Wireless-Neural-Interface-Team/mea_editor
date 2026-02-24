"""
MEA Editor - GUI and library to create and modify MEA compatible with probeinterface.

This package provides:
- Electrode: data model for electrode/contact
- load_electrodes_from_file, save_electrodes_to_file: I/O for probeinterface JSON
- ElectrodeArrayEditorQt, run_app(): Qt GUI editor
"""

from .electrode import Electrode
from .electrode_array_editor_io import load_electrodes_from_file, save_electrodes_to_file
from .electrode_array_editor_qt import ElectrodeArrayEditorQt, run_app

__all__ = [
    "Electrode",
    "load_electrodes_from_file",
    "save_electrodes_to_file",
    "ElectrodeArrayEditorQt",
    "run_app",
]

__version__ = "0.1.0"
