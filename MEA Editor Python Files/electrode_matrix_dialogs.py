from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLineEdit, QSpinBox

"""
Standalone dialogs used by the electrode matrix editor.

The goal of this module is to keep dialog code separated from the main window:
- clearer responsibilities,
- easier maintenance,
- easier reuse by other tools/scripts.
"""

DEFAULT_ROWS = 8
DEFAULT_COLS = 8
DEFAULT_PITCH = 50.0
DEFAULT_UNITS = "µm"


class NewMatrixDialog(QDialog):
    """
    Single window used to create a new aligned matrix.

    Returned values define the initial grid:
    - rows/cols: matrix size
    - pitch: spacing between neighboring contacts
    - si_units: metadata unit stored with the matrix file
    """

    def __init__(self, parent=None) -> None:
        """
        Initialize new-matrix creation dialog.

        Args:
            parent: Parent window (optional).
        """
        super().__init__(parent)
        self.setWindowTitle("New Matrix Parameters")

        form = QFormLayout(self)
        # Number of rows (1-512).
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 512)
        self.rows_spin.setValue(DEFAULT_ROWS)
        # Number of columns (1-512).
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 512)
        self.cols_spin.setValue(DEFAULT_COLS)
        # Spacing between contacts (pitch).
        self.pitch_spin = QDoubleSpinBox()
        self.pitch_spin.setRange(0.001, 100000.0)
        self.pitch_spin.setDecimals(3)
        self.pitch_spin.setValue(DEFAULT_PITCH)
        self.units_edit = QLineEdit(DEFAULT_UNITS)
        self.units_edit.setPlaceholderText("unit (e.g. um, mm)")

        form.addRow("Rows", self.rows_spin)
        form.addRow("Cols", self.cols_spin)
        form.addRow("Pitch", self.pitch_spin)
        form.addRow("si_units", self.units_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[int, int, float, str]:
        """
        Return validated values from widgets.

        Returns:
            (rows, cols, pitch, si_units). If si_units empty, uses DEFAULT_UNITS.
        """
        units = self.units_edit.text().strip() or DEFAULT_UNITS
        return self.rows_spin.value(), self.cols_spin.value(), self.pitch_spin.value(), units
