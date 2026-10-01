"""
MEA Editor - GUI and library to create and modify MEA arrays.

Native files use mea_editor JSON. SpikeInterface export writes probeinterface JSON.
XLSX export writes the full electrode + pad + orientation-marker workbook.

The Qt GUI is imported lazily so I/O and library use do not require a working
PySide6 display.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._version import __version__
from .attribute_schema import AttributeSpec, default_schema
from .electrode import Electrode, ElectrodeSnapshot
from .electrode_array_editor_io import (
    ArrayDocument,
    export_array_xlsx,
    export_spikeinterface_json,
    load_array_document,
    load_array_from_file,
    load_electrodes_from_file,
    save_array_to_file,
    save_electrodes_to_file,
)
from .orientation_marker import OrientationMarker, OrientationMarkerSnapshot
from .pad import Pad, PadSnapshot

if TYPE_CHECKING:
    from .electrode_array_editor_qt import ElectrodeArrayEditorQt, run_app

__all__ = [
    "__version__",
    "ArrayDocument",
    "AttributeSpec",
    "Electrode",
    "ElectrodeSnapshot",
    "OrientationMarker",
    "OrientationMarkerSnapshot",
    "Pad",
    "PadSnapshot",
    "default_schema",
    "load_array_document",
    "load_array_from_file",
    "load_electrodes_from_file",
    "save_array_to_file",
    "save_electrodes_to_file",
    "export_spikeinterface_json",
    "export_array_xlsx",
    "ElectrodeArrayEditorQt",
    "run_app",
]


def __getattr__(name: str) -> Any:
    if name in {"ElectrodeArrayEditorQt", "run_app"}:
        from .electrode_array_editor_qt import ElectrodeArrayEditorQt, run_app

        values = {
            "ElectrodeArrayEditorQt": ElectrodeArrayEditorQt,
            "run_app": run_app,
        }
        globals()[name] = values[name]
        return values[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
