"""
Qt standalone editor for electrode arrays.

Architecture overview
---------------------
- `ElectrodeArrayView`: custom QGraphicsView for interaction + overlays (electrode_array_view.py)
- `GridScene`: lightweight scene wrapper exposing dynamic X/Y axes (grid_scene.py)
- `ElectrodeView`: visual/interactive representation of one `Electrode` (electrode_view.py)
- `ElectrodeArrayEditorQt`: main window, business logic, file workflow (this file)
- `electrode_array_editor_io`: load/save probeinterface JSON (electrode_array_editor_io.py)
"""

from __future__ import annotations

from collections import Counter

try:
    from PySide6.QtCore import QPoint, QRectF, QTimer, Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGraphicsScene,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc

# Relative imports require this module to be loaded as part of the mea_editor package.
# Do NOT run this file directly (python electrode_array_editor_qt.py) - it will fail with
# ImportError: attempted relative import with no known parent package.
# Use instead: python run.py (from project root), or mea-editor (when installed).
from .electrode_array_dialogs import NewArrayDialog
from .electrode_array_editor_io import load_electrodes_from_file, save_electrodes_to_file
from .electrode import Electrode
from .electrode_array_view import AXIS_BAND_HEIGHT, AXIS_BAND_WIDTH, ElectrodeArrayView
from .electrode_view import ElectrodeView
from .grid_scene import GridScene

# Extra scene space around electrodes to allow panning/scrollbars.
DEFAULT_SCENE_MARGIN = 100.0
# Fit-view framing behavior.
FIT_PADDING_MIN = 80.0
FIT_PADDING_RATIO = 0.2


class ElectrodeArrayEditorQt(QMainWindow):
    """
    Main application window orchestrating UI, state, and file workflow.

    This class is the controller layer:
    - keeps canonical electrode dictionary,
    - updates scene items,
    - handles commands (edit/move/save/open/undo/redo).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Electrode Array Editor (Qt Standalone)")
        self.resize(1280, 800)
        self.current_file_path: str | None = None
        self.is_dirty = False
        self.si_units = "um"
        self.is_add_mode = False

        # Canonical electrode models keyed by eid.
        self.electrodes: dict[int, Electrode] = {}
        # Scene items keyed by same eid for sync.
        self.items: dict[int, ElectrodeView] = {}
        # Undo/redo: full snapshots of (x, y, radius, enabled, channel_index, contact_id, ...).
        self.undo_stack: list[
            dict[int, tuple[float, float, float, bool, int, str, tuple[float, float, float, float], str, str]]
        ] = []
        self.redo_stack: list[
            dict[int, tuple[float, float, float, bool, int, str, tuple[float, float, float, float], str, str]]
        ] = []
        self._max_history = 200
        self._is_restoring_state = False
        # Snapshot taken at mouse press; committed on release if changed.
        self._interaction_snapshot: (
            dict[int, tuple[float, float, float, bool, int, str, tuple[float, float, float, float], str, str]]
            | None
        ) = None

        self.scene = GridScene(self)
        self.scene.set_axes_provider(self._grid_axes)
        self.scene.selectionChanged.connect(self._refresh_panel_values)
        self.view = ElectrodeArrayView(self.scene)
        self.view.set_interaction_callbacks(self._on_interaction_begin, self._on_interaction_end)
        self.view.set_add_callbacks(lambda: self.is_add_mode, self._add_electrode_at)
        self.view.set_delete_callback(self._delete_selected)
        self.view.set_view_transform_changed_callback(self._refresh_label_layouts)

        self._build_ui()
        self._build_menu()
        self._startup_done = False

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """
        Prompt to save before closing if there are unsaved changes.
        """
        if self.electrodes and self.is_dirty:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Unsaved changes")
            msg.setText("The current array has unsaved changes.")
            msg.setInformativeText("Do you want to save before closing?")
            save_btn = msg.addButton("Save", QMessageBox.AcceptRole)
            discard_btn = msg.addButton("Discard", QMessageBox.DestructiveRole)
            cancel_btn = msg.addButton(QMessageBox.Cancel)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == save_btn:
                if self._save_current_array(show_success=False):
                    event.accept()
                else:
                    event.ignore()
            elif clicked == discard_btn:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def showEvent(self, event) -> None:  # type: ignore[override]
        """
        On first show: run startup workflow, then fit view once viewport is sized.
        """
        super().showEvent(event)
        if not self._startup_done:
            self._startup_done = True
            QTimer.singleShot(0, self._startup_workflow)
        else:
            QTimer.singleShot(0, self._fit_view)

    def _build_ui(self) -> None:
        """
        Build interface: view on left, side panel on right.

        Panel contains: selection, si_units, edit fields, move, tools
        (add, toggle enabled, fit), help.
        """
        # Central widget and horizontal layout (view | panel).
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # View on left, stretch 4 to take most space.
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.view, stretch=4)

        # Right side panel, stretch 1.
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(8)
        layout.addWidget(panel, stretch=1)

        def make_row(*widgets):
            """Compact helper to place multiple widgets on one form row (edit + button)."""
            row = QWidget()
            lo = QHBoxLayout(row)
            lo.setContentsMargins(0, 0, 0, 0)
            lo.setSpacing(4)
            for w in widgets:
                lo.addWidget(w)
            return row

        # Selection block: selected count + si_units.
        sel_box = QFrame()
        sel_box.setFrameShape(QFrame.StyledPanel)
        sel_form = QFormLayout(sel_box)
        self.selected_count_label = QLabel("0")
        self.si_units_edit = QLineEdit(self.si_units)
        b_units = QPushButton("Apply si_units")
        b_units.clicked.connect(self._apply_si_units)
        units_row = QWidget()
        units_layout = QHBoxLayout(units_row)
        units_layout.setContentsMargins(0, 0, 0, 0)
        units_layout.setSpacing(4)
        units_layout.addWidget(self.si_units_edit)
        units_layout.addWidget(b_units)
        sel_form.addRow("Selected", self.selected_count_label)
        sel_form.addRow("si_units", units_row)
        self.contact_find_edit = QLineEdit("")
        self.contact_find_edit.setPlaceholderText("e.g. A-001")
        self.contact_find_edit.setClearButtonEnabled(True)
        b_find_contact = QPushButton("Find")
        b_find_contact.clicked.connect(self._find_by_contact_id)
        self.contact_find_edit.returnPressed.connect(self._find_by_contact_id)
        sel_form.addRow("Find contact ID", make_row(self.contact_find_edit, b_find_contact))
        panel_layout.addWidget(sel_box)

        # Edit block: radius, X/Y, channel, contact_id, plane_axis, shank, shape.
        edit_box = QFrame()
        edit_box.setFrameShape(QFrame.StyledPanel)
        e_form = QFormLayout(edit_box)
        self.radius_edit = QLineEdit("")
        self.x_edit = QLineEdit("")
        self.y_edit = QLineEdit("")
        self.channel_index_edit = QLineEdit("")
        self.contact_id_edit = QLineEdit("")
        self.contact_plane_axis_edit = QLineEdit("")
        self.shank_id_edit = QLineEdit("")
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["circle"])
        self.dx_edit = QLineEdit("0")
        self.dy_edit = QLineEdit("0")

        b_radius = QPushButton("Apply Radius")
        b_radius.clicked.connect(self._apply_radius)
        b_xy = QPushButton("Apply X/Y")
        b_xy.clicked.connect(self._apply_xy_single)
        b_channel = QPushButton("Apply Channel")
        b_channel.clicked.connect(self._apply_channel_index)
        b_contact = QPushButton("Apply Contact ID")
        b_contact.clicked.connect(self._apply_contact_id)
        b_plane = QPushButton("Apply Contact Plane Axis")
        b_plane.clicked.connect(self._apply_contact_plane_axis)
        b_shank = QPushButton("Apply Shank ID")
        b_shank.clicked.connect(self._apply_shank_id)
        b_shape = QPushButton("Apply Shape")
        b_shape.clicked.connect(self._apply_shape)

        e_form.addRow("Radius", make_row(self.radius_edit, b_radius))
        e_form.addRow("X/Y (single)", make_row(self.x_edit, self.y_edit, b_xy))
        e_form.addRow("Channel index", make_row(self.channel_index_edit, b_channel))
        e_form.addRow("Contact ID", make_row(self.contact_id_edit, b_contact))
        e_form.addRow("Contact plane axis", make_row(self.contact_plane_axis_edit, b_plane))
        e_form.addRow("Shank ID", make_row(self.shank_id_edit, b_shank))
        e_form.addRow("Shape", make_row(self.shape_combo, b_shape))
        panel_layout.addWidget(edit_box)

        # Move block: dX, dY to move selection.
        move_box = QFrame()
        move_box.setFrameShape(QFrame.StyledPanel)
        move_form = QFormLayout(move_box)
        b_move = QPushButton("Move Selection dX/dY")
        b_move.clicked.connect(self._move_selection_by_delta)
        move_form.addRow("dX (group)", self.dx_edit)
        move_form.addRow("dY (group)", self.dy_edit)
        move_form.addRow(b_move)
        panel_layout.addWidget(move_box)

        # Tools block: add electrode, toggle enabled, fit view.
        tools_box = QFrame()
        tools_box.setFrameShape(QFrame.StyledPanel)
        t_form = QFormLayout(tools_box)
        self.b_add_electrode = QPushButton("Add Electrode")
        self.b_add_electrode.setCheckable(True)
        self.b_add_electrode.toggled.connect(self._set_add_mode)
        b_delete = QPushButton("Delete Selected Electrode")
        b_delete.clicked.connect(self._delete_selected)
        b_toggle = QPushButton("Toggle Enabled")
        b_toggle.clicked.connect(self._toggle_enabled)
        b_fit = QPushButton("Fit View")
        b_fit.clicked.connect(self._fit_view)
        t_form.addRow(self.b_add_electrode)
        t_form.addRow(b_delete)
        t_form.addRow(b_toggle)
        t_form.addRow(b_fit)
        panel_layout.addWidget(tools_box)

        help_label = QLabel(
            "Click: select one\n"
            "Ctrl+Click: add/remove from selection\n"
            "Drag empty area: box selection\n"
            "Move: use X/Y or dX/dY in the panel\n"
            "Suppr/Backspace: delete selected\n"
            "Wheel: zoom"
        )
        help_label.setWordWrap(True)
        panel_layout.addWidget(help_label)
        panel_layout.addStretch(1)

    def _build_menu(self) -> None:
        """
        Create File menu with New, Open, Save, Save As, Export xlsx.

        Each action is connected to its handler and keyboard shortcut.
        """
        file_menu = self.menuBar().addMenu("File")
        act_new = QAction("New array...", self)
        act_new.setShortcut(QKeySequence.New)
        act_new.triggered.connect(self._create_new_array_interactive)
        file_menu.addAction(act_new)

        act_open = QAction("Open...", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._menu_open_array)
        file_menu.addAction(act_open)

        act_save = QAction("Save", self)
        act_save.setShortcut(QKeySequence.Save)
        act_save.triggered.connect(self._menu_save_array)
        file_menu.addAction(act_save)

        act_save_as = QAction("Save As...", self)
        act_save_as.setShortcut(QKeySequence.SaveAs)
        act_save_as.triggered.connect(self._menu_save_array_as)
        file_menu.addAction(act_save_as)

        act_export_xlsx = QAction("Export array as XLSX...", self)
        act_export_xlsx.triggered.connect(self._menu_export_matrix_xlsx)
        file_menu.addAction(act_export_xlsx)

    def _selected_items(self) -> list[ElectrodeView]:
        """
        Return currently selected items, filtered to ElectrodeView.

        Returns:
            List of selected ElectrodeView (excludes other item types).
        """
        return [it for it in self.scene.selectedItems() if isinstance(it, ElectrodeView)]

    def _find_by_contact_id(self) -> None:
        """
        Select electrode(s) whose contact_id matches the find field and scroll the view to them.

        Matching order: exact (after strip), then case-insensitive exact.
        """
        query = self.contact_find_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Find contact ID", "Enter a contact ID to search.")
            return
        if not self.items:
            QMessageBox.information(self, "Find contact ID", "No electrodes in the current array.")
            return

        def norm(s: str) -> str:
            return str(s).strip()

        matches = [it for it in self.items.values() if norm(it.model.contact_id) == query]
        if not matches:
            q_lower = query.lower()
            matches = [it for it in self.items.values() if norm(it.model.contact_id).lower() == q_lower]
        if not matches:
            QMessageBox.information(
                self,
                "Contact ID not found",
                f"No electrode has contact ID « {query} ».",
            )
            return

        self.scene.clearSelection()
        for item in matches:
            item.setSelected(True)

        united = matches[0].sceneBoundingRect()
        for item in matches[1:]:
            united = united.united(item.sceneBoundingRect())
        pad = 40.0
        united = united.adjusted(-pad, -pad, pad, pad)
        self.view.ensureVisible(united, 80, 80)
        self._refresh_panel_values()

    def _grid_axes(self) -> tuple[list[float], list[float]]:
        """
        Return sorted unique X/Y coordinates for grid and axes.

        Returns:
            (xs, ys): lists of electrode abscissas and ordinates.
        """
        # Round to avoid near-duplicate grid lines from float noise.
        xs = sorted({round(model.x, 6) for model in self.electrodes.values()})
        ys = sorted({round(model.y, 6) for model in self.electrodes.values()})
        return xs, ys

    def _electrode_bounds_rect(self, margin: float = 0.0) -> QRectF:
        """
        Compute bounding rect of all electrodes (center + radius).

        Args:
            margin: Optional margin added on each side.

        Returns:
            QRectF enclosing all circles, or default rect if empty.
        """
        if not self.electrodes:
            return QRectF(-1.0, -1.0, 2.0, 2.0)  # Fallback for empty scene.
        min_x = min(model.x - model.radius for model in self.electrodes.values())
        max_x = max(model.x + model.radius for model in self.electrodes.values())
        min_y = min(model.y - model.radius for model in self.electrodes.values())
        max_y = max(model.y + model.radius for model in self.electrodes.values())
        rect = QRectF(min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0))
        if margin > 0:
            rect = rect.adjusted(-margin, -margin, margin, margin)
        return rect

    def _capture_state(
        self,
    ) -> dict[int, tuple[float, float, float, bool, int, str, tuple[float, float, float, float], str, str]]:
        """
        Capture full state snapshot for undo/redo.

        Returns:
            Dict eid -> (x, y, radius, enabled, channel_index, contact_id,
                         contact_plane_axis, shank_id, shape).
        """
        return {
            eid: (
                m.x,
                m.y,
                m.radius,
                m.enabled,
                m.channel_index,
                m.contact_id,
                m.contact_plane_axis,
                m.shank_id,
                m.shape,
            )
            for eid, m in self.electrodes.items()
        }

    def _set_electrodes(self, models: list[Electrode]) -> None:
        """
        Replace entire scene content with the given model list.

        Clears scene, recreates items, updates electrodes/items,
        sceneRect, duplicate flags, panel and title.
        """
        self.scene.clear()
        self.electrodes.clear()
        self.items.clear()
        for model in models:
            # on_change: refresh panel + overlays; on_selection: refresh panel.
            item = ElectrodeView(model, self._on_scene_visuals_changed, self._refresh_panel_values)
            self.scene.addItem(item)
            self.electrodes[model.eid] = model
            self.items[model.eid] = item
        # Expand scene rect so user can pan/scroll in margins.
        self.scene.setSceneRect(self._electrode_bounds_rect(margin=DEFAULT_SCENE_MARGIN))
        self._update_duplicate_flags()
        self._refresh_panel_values()
        self.si_units_edit.setText(self.si_units)
        self._update_title()
        # Defer label layout so view has updated after scene change (add/delete).
        QTimer.singleShot(0, self._refresh_label_layouts)
    
    def _set_add_mode(self, enabled: bool) -> None:
        """
        Toggle one-click electrode creation mode.

        Change button text and cursor (cross when active).
        """
        self.is_add_mode = enabled
        if enabled:
            self.b_add_electrode.setText("Stop Adding")
            self.view.viewport().setCursor(Qt.CrossCursor)
        else:
            self.b_add_electrode.setText("Add Electrode")
            self.view.viewport().unsetCursor()

    def _add_electrode_at(self, x: float, y: float) -> None:
        """
        Create a new electrode at (x, y) and select it.

        Uses next available eid, default contact_id "A-000".
        """
        before = self._capture_state()
        next_eid = max(self.electrodes.keys(), default=-1) + 1  # Unique id.
        model = Electrode(eid=next_eid, x=x, y=y, channel_index=next_eid, contact_id="A-000")
        models = list(self.electrodes.values()) + [model]
        self._set_electrodes(models)
        self.scene.clearSelection()
        if next_eid in self.items:
            self.items[next_eid].setSelected(True)
        self._commit_if_changed(before)

    def _apply_si_units(self) -> None:
        """
        Apply distance unit (si_units) at array level.

        Reads from panel field, validates, updates and marks dirty.
        """
        units = self.si_units_edit.text().strip()
        if not units:
            QMessageBox.information(self, "No values", "Fill si_units before applying.")
            self.si_units_edit.setText(self.si_units)
            return
        if units == self.si_units:
            return
        self.si_units = units
        self.si_units_edit.setText(self.si_units)
        self.is_dirty = True
        self._update_title()

    def _update_title(self) -> None:
        """
        Update window title with file path and asterisk if modified.
        """
        dirty_suffix = " *" if self.is_dirty else ""
        if self.current_file_path:
            self.setWindowTitle(f"Electrode Array Editor (Qt Standalone) - {self.current_file_path}{dirty_suffix}")
        else:
            self.setWindowTitle(f"Electrode Array Editor (Qt Standalone){dirty_suffix}")

    def _startup_workflow(self) -> None:
        """
        On startup, show dialog: open or create array.

        If user cancels or fails to open/create, close application.
        Called after main window is shown so it appears as a proper window.
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("Electrode Array Editor")
        msg.setText("Choose how to start:")
        open_btn = msg.addButton("Open existing array", QMessageBox.AcceptRole)
        new_btn = msg.addButton("Create new array", QMessageBox.ActionRole)
        cancel_btn = msg.addButton(QMessageBox.Cancel)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == open_btn:
            loaded = self._prompt_open_array_file()
            if not loaded:
                if not self._prompt_new_array_parameters():
                    self.close()
        elif clicked == new_btn:
            if not self._prompt_new_array_parameters():
                self.close()
        else:
            self.close()

    def _prompt_new_array_parameters(self) -> bool:
        """
        Open new-matrix dialog and generate grid if accepted.

        Returns:
            True if grid was created, False if cancelled.
        """
        dialog = NewArrayDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return False
        rows, cols, pitch, units = dialog.values()
        self.si_units = units
        self._generate_aligned_grid(rows, cols, pitch)
        self.current_file_path = None
        self.is_dirty = True
        self._update_title()
        self._fit_view()
        self.raise_()
        self.activateWindow()
        return True

    def _prompt_open_array_file(self) -> bool:
        """
        Prompt for JSON path via dialog and load array.

        Returns:
            True if loaded successfully, False if cancelled or error.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open array JSON",
            "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return False
        try:
            self._load_array_from_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", f"Could not load file:\n{exc}")
            return False
        self.current_file_path = path
        self.is_dirty = False
        self._update_title()
        self._fit_view()
        self.raise_()
        self.activateWindow()
        return True

    def _menu_open_array(self) -> None:
        """Menu handler for Open action with unsaved-work protection."""
        if self._confirm_before_replace("open an array"):
            self._prompt_open_array_file()

    def _menu_save_array(self) -> None:
        """Menu handler for Save."""
        self._save_current_array(show_success=True)

    def _menu_save_array_as(self) -> None:
        """Menu handler for Save As."""
        self._save_current_array_as(show_success=True)

    def _menu_export_matrix_xlsx(self) -> None:
        """Menu handler for array export as XLSX."""
        if not self.electrodes:
            QMessageBox.information(self, "Export XLSX", "No array to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export array XLSX",
            "",
            "Excel files (*.xlsx);;All files (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            self._export_matrix_to_xlsx(path)
        except ImportError as exc:
            QMessageBox.critical(
                self,
                "Export XLSX",
                f"Could not export XLSX:\n{exc}\n\nInstall with: pip install openpyxl",
            )
            return
        except Exception as exc:
            QMessageBox.critical(self, "Export XLSX", f"Could not export XLSX:\n{exc}")
            return
        QMessageBox.information(self, "Export XLSX", "Matrix exported successfully.")

    def _save_current_array(self, show_success: bool = False) -> bool:
        """
        Save to current path. If no path, open Save As dialog.

        Args:
            show_success: Show success message after save.

        Returns:
            True if saved, False otherwise.
        """
        if not self.electrodes:
            QMessageBox.information(self, "Save array", "No array to save.")
            return False
        if not self.current_file_path:
            return self._save_current_array_as(show_success=show_success)
        try:
            self._save_array_to_file(self.current_file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", f"Could not save file:\n{exc}")
            return False
        self.is_dirty = False
        self._update_title()
        if show_success:
            QMessageBox.information(self, "Save array", "Array saved successfully.")
        return True

    def _save_current_array_as(self, show_success: bool = False) -> bool:
        """
        Save with explicit file selection dialog.

        Returns:
            True if saved, False if cancelled or error.
        """
        if not self.electrodes:
            QMessageBox.information(self, "Save array", "No array to save.")
            return False
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save array JSON",
            self.current_file_path or "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return False
        try:
            self._save_array_to_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", f"Could not save file:\n{exc}")
            return False
        self.current_file_path = path
        self.is_dirty = False
        self._update_title()
        if show_success:
            QMessageBox.information(self, "Save array", "Array saved successfully.")
        return True

    def _confirm_before_replace(self, action_label: str) -> bool:
        """
        Prompt save/discard/cancel before replacing content.

        Returns:
            True if user confirmed; False to abort.
        """
        if self.electrodes and self.is_dirty:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Unsaved changes")
            msg.setText("The current array has unsaved changes.")
            msg.setInformativeText("Do you want to save before continuing?")
            save_btn = msg.addButton("Save", QMessageBox.AcceptRole)
            discard_btn = msg.addButton("Discard", QMessageBox.DestructiveRole)
            cancel_btn = msg.addButton(QMessageBox.Cancel)
            msg.exec()
            clicked = msg.clickedButton()
            if clicked == save_btn:
                if not self._save_current_array(show_success=False):
                    return False
            elif clicked == discard_btn:
                pass
            elif clicked == cancel_btn:
                return False
            else:
                return False

        # If array not empty, ask for replacement confirmation.
        if self.electrodes:
            confirm = QMessageBox.question(
                self,
                "Confirm action",
                f"Are you sure you want to {action_label}?\nThe current array will be replaced.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return False
        return True

    def _save_array_to_file(self, path: str) -> None:
        """
        Persist current models via electrode_array_editor_io (probeinterface format).
        """
        save_electrodes_to_file(path, list(self.electrodes.values()), self.si_units)

    def _load_array_from_file(self, path: str) -> None:
        """
        Load models from file and update si_units in memory.
        """
        models, units = load_electrodes_from_file(path)
        self.si_units = units
        self._set_electrodes(models)

    def _export_matrix_to_xlsx(self, path: str) -> None:
        """
        Export array data into an XLSX file.

        Output columns:
        - channel
        - row
        - col
        """
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ImportError("openpyxl is required for XLSX export.") from exc

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "array"
        worksheet.append(["channel", "row", "col"])
        for model in sorted(self.electrodes.values(), key=lambda m: (m.channel_index, m.eid)):
            worksheet.append([model.channel_index, model.x, model.y])
        workbook.save(path)

    def _update_duplicate_flags(self) -> tuple[list[int], list[str], int]:
        """
        Recompute duplicate flags (channel_index, contact_id) and refresh colors.

        Returns:
            (duplicate_channels, duplicate_contacts, empty_contact_count).
        """
        # Count channel_index and contact_id to detect duplicates.
        channel_counts = Counter(model.channel_index for model in self.electrodes.values())
        contact_counts = Counter(model.contact_id for model in self.electrodes.values())
        duplicate_channels = sorted(value for value, count in channel_counts.items() if count > 1)
        # Ignore empty contact_id in duplicate highlighting.
        duplicate_contacts = sorted(v for v, c in contact_counts.items() if c > 1 and v.strip() != "")
        empty_contact_count = contact_counts.get("", 0)
        dup_channel_set = set(duplicate_channels)
        dup_contact_set = set(duplicate_contacts)
        # Mark each model according to whether it is a duplicate.
        for model in self.electrodes.values():
            model.has_channel_duplicate = model.channel_index in dup_channel_set
            model.has_contact_duplicate = model.contact_id in dup_contact_set
        for item in self.items.values():
            item._refresh_style()
        return duplicate_channels, duplicate_contacts, empty_contact_count

    def _states_equal(self, a, b) -> bool:
        """
        Compare two snapshots with tolerance on floats.

        Args:
            a, b: Dicts eid -> state tuple.

        Returns:
            True if states equivalent (same keys, close values).
        """
        if a.keys() != b.keys():
            return False
        tol = 1e-9
        for eid in a:
            # Compare each field; tolerance on x, y, radius, contact_plane_axis.
            ax, ay, ar, ae, ac, aid, aplane, ashank, ashape = a[eid]
            bx, by, br, be, bc, bid, bplane, bshank, bshape = b[eid]
            if ae != be or ac != bc or aid != bid or ashank != bshank or ashape != bshape:
                return False
            if any(abs(av - bv) > tol for av, bv in zip(aplane, bplane)):
                return False
            if abs(ax - bx) > tol or abs(ay - by) > tol or abs(ar - br) > tol:
                return False
        return True

    def _restore_state(self, state) -> None:
        """
        Restore snapshot into scene (undo/redo).

        Recreates Electrode models from state, calls _set_electrodes,
        then refreshes visuals.
        """
        self._is_restoring_state = True
        try:
            models: list[Electrode] = []
            for eid, values in sorted(state.items(), key=lambda kv: kv[0]):
                x, y, radius, enabled, channel_index, contact_id, contact_plane_axis, shank_id, shape = values
                models.append(
                    Electrode(
                        eid=eid,
                        x=x,
                        y=y,
                        radius=radius,
                        enabled=enabled,
                        channel_index=channel_index,
                        contact_id=contact_id,
                        contact_plane_axis=contact_plane_axis,
                        shank_id=shank_id,
                        shape=shape,
                    )
                )
            self._set_electrodes(models)
        finally:
            self._is_restoring_state = False
        self._on_scene_visuals_changed()

    def _push_undo(self, before_state) -> None:
        """
        Push state onto undo stack and clear redo stack.

        Limits history size to _max_history.
        """
        self.undo_stack.append(before_state)
        if len(self.undo_stack) > self._max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _commit_if_changed(self, before_state) -> None:
        """
        Record undo entry only when state actually changed.

        Compares before_state with current; if different, push undo and mark dirty.
        """
        after_state = self._capture_state()
        if not self._states_equal(before_state, after_state):
            self._push_undo(before_state)
            self.is_dirty = True
            self._update_title()

    def _on_interaction_begin(self) -> None:
        """
        Store snapshot of state before interaction (mouse press).
        """
        self._interaction_snapshot = self._capture_state()

    def _on_interaction_end(self) -> None:
        """
        Finalize interaction on mouse release: commit undo if changed.
        """
        if self._interaction_snapshot is None:
            return
        self._commit_if_changed(self._interaction_snapshot)
        self._interaction_snapshot = None
        # Refresh panel and scene rect after drag (skipped during drag to avoid crash).
        self._on_scene_visuals_changed()

    def _on_scene_visuals_changed(self) -> None:
        """
        Refresh panel and overlays when geometry/selection changes.

        Ignored during _is_restoring_state to avoid undo/redo recursion.
        Skipped during drag (_interaction_snapshot set) to avoid crash when
        moving many electrodes: ItemPositionHasChanged fires for each item,
        causing excessive setSceneRect/invalidate calls.
        """
        if self._is_restoring_state:
            return  # Avoid recursion during undo/redo restore.
        if self._interaction_snapshot is not None:
            return  # Skip during drag; _on_interaction_end will refresh.
        self._refresh_panel_values()
        self.scene.setSceneRect(self._electrode_bounds_rect(margin=DEFAULT_SCENE_MARGIN))
        self.scene.invalidate(
            self.scene.sceneRect(),
            QGraphicsScene.BackgroundLayer | QGraphicsScene.ForegroundLayer,
        )
        self.view.viewport().update()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """
        Handle global shortcuts: Ctrl+Z (undo), Ctrl+Y (redo).
        Suppr/Backspace for delete is handled by ElectrodeArrayView when it has focus.
        """
        if event.matches(QKeySequence.Undo):
            self._undo()
            event.accept()
            return
        if event.matches(QKeySequence.Redo):
            self._redo()
            event.accept()
            return
        super().keyPressEvent(event)

    def _undo(self) -> None:
        """
        Undo: restore previous state and put current into redo.
        """
        if not self.undo_stack:
            return
        current = self._capture_state()
        previous = self.undo_stack.pop()
        self.redo_stack.append(current)
        self._restore_state(previous)

    def _redo(self) -> None:
        """
        Redo: restore next state and put current back into undo.
        """
        if not self.redo_stack:
            return
        current = self._capture_state()
        nxt = self.redo_stack.pop()
        self.undo_stack.append(current)
        self._restore_state(nxt)

    def _generate_aligned_grid(self, rows: int, cols: int, pitch: float) -> None:
        """
        Create regular rows x cols grid with pitch spacing.

        Electrodes at (c*pitch, r*pitch), eid = 0..rows*cols-1.
        """
        models: list[Electrode] = []
        eid = 0
        for r in range(rows):
            for c in range(cols):
                models.append(Electrode(eid=eid, x=c * pitch, y=r * pitch, channel_index=eid, contact_id="A-000"))
                eid += 1
        self._set_electrodes(models)

    def _create_new_array_interactive(self) -> None:
        """
        Handler for File > New: confirm replacement, open dialog, create grid.
        """
        if not self._confirm_before_replace("create a new array"):
            return
        before = self._capture_state()
        if self._prompt_new_array_parameters():
            self._commit_if_changed(before)

    def _refresh_label_layouts(self) -> None:
        """
        Refresh label positions on all electrode items (after zoom/scale change).
        Labels use ItemIgnoresTransformations; their layout depends on view scale.
        """
        for item in self.items.values():
            item._layout_labels()

    def _fit_view(self) -> None:
        """
        Fit view to frame electrodes with margin and centering.

        Two spaces managed:
        - fit_rect: visual framing (electrodes + padding),
        - sceneRect: larger navigable area for scroll/pan in margins.
        Centers fit_rect in usable area (excluding axis bands).
        """
        if not self.electrodes:
            return
        base_rect = self._electrode_bounds_rect(margin=0.0)
        # Padding scales with electrode extent for comfortable framing.
        fit_padding = max(FIT_PADDING_MIN, FIT_PADDING_RATIO * max(base_rect.width(), base_rect.height()))
        fit_rect = base_rect.adjusted(-fit_padding, -fit_padding, fit_padding, fit_padding)
        scene_margin = max(DEFAULT_SCENE_MARGIN, fit_padding * 1.5)
        self.scene.setSceneRect(self._electrode_bounds_rect(margin=scene_margin))
        self.view.fitInView(fit_rect, Qt.KeepAspectRatio)
        # fitInView resets transform; reapply Cartesian orientation (Y up).
        vp = self.view.viewport().rect()
        axis_w = AXIS_BAND_WIDTH
        axis_h = AXIS_BAND_HEIGHT
        usable_w = max(vp.width() - axis_w, 1)
        usable_h = max(vp.height() - axis_h, 1)
        # Center the fit rect in the usable area (excluding axis bands).
        desired_vp_center = QPoint(axis_w + usable_w // 2, axis_h + usable_h // 2)
        current_vp_pos = self.view.mapFromScene(fit_rect.center())
        # Scroll so fit rect center aligns with usable area center.
        delta_vp = current_vp_pos - desired_vp_center
        self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().value() + delta_vp.x())
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().value() + delta_vp.y())
        self._refresh_label_layouts()

    def _apply_radius(self) -> None:
        """
        Apply radius field value to all selected electrodes.

        Validates radius > 0. Ignored if no selection.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        try:
            radius = float(self.radius_edit.text())
            if radius <= 0:
                raise ValueError
        except ValueError:
            # Non-numeric or <= 0 value.
            QMessageBox.critical(self, "Invalid radius", "Radius must be a positive number.")
            return
        for item in selected:
            item.set_radius(radius)
            item.sync_from_model()
        self._refresh_panel_values()
        # Record undo if effective change.
        self._commit_if_changed(before)

    def _apply_xy_single(self) -> None:
        """
        Set absolute X/Y for a single selected electrode.

        Requires exactly one selection. Validates X and Y are numeric.
        """
        selected = self._selected_items()
        if len(selected) != 1:
            QMessageBox.information(self, "Single selection required", "Select exactly one electrode.")
            return
        before = self._capture_state()
        try:
            x = float(self.x_edit.text())
            y = float(self.y_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid X/Y", "X and Y must be numeric values.")
            return
        selected[0].setPos(x, y)
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _apply_channel_index(self) -> None:
        """
        Apply channel_index to all selected electrodes.

        Updates duplicate flags after modification.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        text = self.channel_index_edit.text().strip()
        if text == "":
            QMessageBox.information(self, "No values", "Fill Channel index before applying.")
            return
        try:
            value = int(text)
        except ValueError:
            QMessageBox.critical(self, "Invalid channel index", "Channel index must be an integer.")
            return
        for item in selected:
            item.model.channel_index = value
            item.sync_from_model()
        self._update_duplicate_flags()
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _apply_contact_id(self) -> None:
        """
        Apply contact_id to all selected electrodes.

        Updates duplicate flags after modification.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        text = self.contact_id_edit.text().strip()
        if text == "":
            QMessageBox.information(self, "No values", "Fill Contact ID before applying.")
            return
        for item in selected:
            item.model.contact_id = text
            item.sync_from_model()
        self._update_duplicate_flags()
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _parse_contact_plane_axis_text(self, text: str) -> tuple[float, float, float, float] | None:
        """
        Parse axis text: "x0,x1,y0,y1" or space-separated values.

        Returns:
            (x0, x1, y0, y1) or None if not exactly 4 numeric values.
        """
        parts = [p for p in text.replace(",", " ").split() if p]
        if len(parts) != 4:
            return None
        try:
            x0, x1, y0, y1 = (float(p) for p in parts)
        except ValueError:
            return None
        return x0, x1, y0, y1

    def _apply_contact_plane_axis(self) -> None:
        """
        Apply contact plane axis (x0,x1,y0,y1) to selected electrodes.

        Parses field text; requires 4 numeric values.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        text = self.contact_plane_axis_edit.text().strip()
        if text == "":
            QMessageBox.information(self, "No values", "Fill Contact plane axis before applying.")
            return
        value = self._parse_contact_plane_axis_text(text)
        if value is None:
            QMessageBox.critical(self, "Invalid contact plane axis", "Use 4 values: x0, x1, y0, y1.")
            return
        for item in selected:
            item.model.contact_plane_axis = value
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _apply_shank_id(self) -> None:
        """
        Apply shank_id to all selected electrodes.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        text = self.shank_id_edit.text()
        for item in selected:
            item.model.shank_id = text
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _apply_shape(self) -> None:
        """
        Apply shape to selected electrodes (currently forced to 'circle').
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        value = self.shape_combo.currentText().strip().lower() or "circle"
        if value != "circle":
            value = "circle"
        for item in selected:
            item.model.shape = value
            item.sync_from_model()
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _move_selection_by_delta(self) -> None:
        """
        Move selected electrodes by (dX, dY).

        Reads dX and dY from panel fields; validates they are numeric.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        try:
            dx = float(self.dx_edit.text())
            dy = float(self.dy_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid dX/dY", "dX and dY must be numeric values.")
            return
        for item in selected:
            p = item.pos()
            item.setPos(p.x() + dx, p.y() + dy)
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _delete_selected(self) -> None:
        """
        Delete all selected electrodes.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        selected_eids = {item.model.eid for item in selected}
        models = [m for m in self.electrodes.values() if m.eid not in selected_eids]
        self._set_electrodes(models)
        self._commit_if_changed(before)

    def _toggle_enabled(self) -> None:
        """
        Invert enabled flag for each selected electrode.
        """
        selected = self._selected_items()
        if not selected:
            return
        before = self._capture_state()
        for item in selected:
            item.model.enabled = not item.model.enabled
            item.sync_from_model()
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _refresh_panel_values(self) -> None:
        """
        Update side panel fields according to selection.

        - 0 selections: empty fields.
        - 1 selection: all electrode values.
        - N selections: common values or empty if mixed.
        """
        selected = self._selected_items()
        self.selected_count_label.setText(str(len(selected)))

        # Single selection: show all editable fields.
        if len(selected) == 1:
            m = selected[0].model
            # Fill all fields with model values.
            self.radius_edit.setText(f"{m.radius:.2f}")
            self.x_edit.setText(f"{m.x:.2f}")
            self.y_edit.setText(f"{m.y:.2f}")
            self.channel_index_edit.setText(str(m.channel_index))
            self.contact_id_edit.setText(m.contact_id)
            x0, x1, y0, y1 = m.contact_plane_axis
            self.contact_plane_axis_edit.setText(f"{x0:g}, {x1:g}, {y0:g}, {y1:g}")
            self.shank_id_edit.setText(m.shank_id)
            self.shape_combo.setCurrentText(m.shape if m.shape else "circle")
            return

        # Multi-selection: show common values or empty when mixed.
        if len(selected) > 1:
            # Extract values from each electrode.
            radii = [it.model.radius for it in selected]
            channels = [it.model.channel_index for it in selected]
            contacts = [it.model.contact_id for it in selected]
            axes = [it.model.contact_plane_axis for it in selected]
            shanks = [it.model.shank_id for it in selected]
            # Show common value or empty if mixed.
            self.radius_edit.setText(f"{radii[0]:.2f}" if max(radii) - min(radii) < 1e-9 else "")
            self.channel_index_edit.setText(str(channels[0]) if min(channels) == max(channels) else "")
            self.contact_id_edit.setText(contacts[0] if all(c == contacts[0] for c in contacts) else "")
            if all(a == axes[0] for a in axes):
                x0, x1, y0, y1 = axes[0]
                self.contact_plane_axis_edit.setText(f"{x0:g}, {x1:g}, {y0:g}, {y1:g}")
            else:
                self.contact_plane_axis_edit.setText("")
            self.shank_id_edit.setText(shanks[0] if all(s == shanks[0] for s in shanks) else "")
            self.shape_combo.setCurrentText("circle")
            self.x_edit.setText("")
            self.y_edit.setText("")
            return

        # No selection: clear all panel fields.
        self.radius_edit.setText("")
        self.x_edit.setText("")
        self.y_edit.setText("")
        self.channel_index_edit.setText("")
        self.contact_id_edit.setText("")
        self.contact_plane_axis_edit.setText("")
        self.shank_id_edit.setText("")
        self.shape_combo.setCurrentText("circle")


def run_app() -> None:
    """
    Application entry point.

    Creates QApplication, ElectrodeArrayEditorQt window, shows and runs event loop.
    """
    app = QApplication([])
    win = ElectrodeArrayEditorQt()
    win.show()
    win.raise_()
    win.activateWindow()
    app.exec()


if __name__ == "__main__":
    run_app()

