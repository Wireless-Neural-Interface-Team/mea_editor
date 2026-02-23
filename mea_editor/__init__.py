"""
MEA Editor - GUI and library to create and modify MEA compatible with probeinterface.

This package provides:
- Electrode: data model for electrode/contact
- load_electrodes_from_file, save_electrodes_to_file: I/O for probeinterface JSON
- ElectrodeArrayEditorQt, main(): Qt GUI editor
"""

from .electrode_array_types import Electrode
from .electrode_array_io import load_electrodes_from_file, save_electrodes_to_file
from .electrode_array_editor_qt import ElectrodeArrayEditorQt, main

__all__ = [
    "Electrode",
    "load_electrodes_from_file",
    "save_electrodes_to_file",
    "ElectrodeArrayEditorQt",
    "main",
]

__version__ = "0.1.0"
