"""
Qt standalone editor for electrode arrays.

Architecture overview
---------------------
- `ElectrodeArrayView`: custom QGraphicsView for interaction + overlays (electrode_array_view.py)
- `GridScene`: lightweight scene wrapper exposing dynamic X/Y axes (grid_scene.py)
- `ElectrodeView`: visual/interactive representation of one `Electrode` (electrode_view.py)
- `PadView`: visual/interactive representation of one `Pad` (pad_view.py)
- `OrientationMarkerView`: white fiducial (circle / square / rect), not linked to contacts (orientation_marker_view.py)
- `ElectrodeArrayEditorQt`: main window, business logic, file workflow (this file)
- `ElectrodeTableWindow`: non-modal table of all electrodes with search/filters
- `attribute_schema`: file-level extra electrode attributes (this file rebuilds the panel from it)
- `electrode_array_editor_io`: native mea_editor JSON + SpikeInterface / XLSX export

Electrodes and pads share the same scene, shown in two side-by-side
mapping views: the left view fits the electrodes, the right view fits the pads.
Each contact stores map-label text drawn by the mapping view overlay.
Each contact uses a SpikeInterface shape (circle, square, or rect).
Pads are interfaces toward other electronic systems and each pad is
linked to one electrode. Orientation markers are unlinked white fiducials (circle, square, or rect)
used to read the view orientation; they are not SpikeInterface contacts.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import threading

try:
    from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
    from PySide6.QtGui import QAction, QKeySequence
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QFrame,
        QGraphicsItem,
        QGraphicsView,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSplitter,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc

# Relative imports require this module to be loaded as part of the mea_editor package.
# Do NOT run this file directly (python electrode_array_editor_qt.py) - it will fail with
# ImportError: attempted relative import with no known parent package.
# Use instead: python run.py (from project root), or mea-editor (when installed).
from ._version import __version__
from .array_integrity import (
    ensure_unique_marker_ids,
    ensure_unique_model_ids,
    pairing_problems,
    refresh_status_flags,
)
from .attribute_schema import (
    AttributeSpec,
    default_schema,
    fill_electrode_extras,
    fill_electrodes_extras,
    parse_user_value,
)
from .contact_shape import (
    DEFAULT_PAD_SHAPE,
    contact_half_extents,
    effective_half_height,
    height_field_label,
    normalize_contact_shape,
    primary_size_field_label,
    shape_uses_height,
    size_field_from_stored_half,
    stored_half_from_size_field,
)
from .electrode_array_dialogs import AddAttributeDialog, NewArrayDialog, NewArrayParams
from .electrode_table_window import ElectrodeTableWindow
from .electrode_array_editor_io import (
    NATIVE_VERSION,
    export_array_xlsx,
    export_spikeinterface_json,
    format_intan_id,
    is_probeinterface_file,
    load_array_document,
    save_array_to_file,
)
from .electrode import (
    DEFAULT_LABEL_ORIENTATION,
    DEFAULT_LABEL_POSITION,
    DEFAULT_MAP_LABEL_KEYS,
    DEFAULT_RADIUS,
    DEFAULT_SHAPE,
    ELECTRODE_SHAPES,
    LABEL_ORIENTATION_CAPTIONS,
    LABEL_ORIENTATIONS,
    LABEL_POSITION_CAPTIONS,
    LABEL_POSITIONS,
    Electrode,
    ElectrodeSnapshot,
    normalize_label_orientation,
    normalize_label_position,
)
from .electrode_array_view import ElectrodeArrayView
from .electrode_view import ElectrodeView
from .grid_scene import GridScene
from .orientation_marker import (
    DEFAULT_MARKER_RADIUS,
    DEFAULT_MARKER_SHAPE,
    MARKER_SHAPES,
    OrientationMarker,
    OrientationMarkerSnapshot,
)
from .orientation_marker_view import OrientationMarkerView
from .pad import (
    DEFAULT_PAD_RADIUS,
    PAD_SHAPES,
    Pad,
    PadSnapshot,
)
from .pad_layout import layout_pads_around_electrodes
from .pad_view import PadView

# Extra scene space around electrodes to allow panning/scrollbars.
DEFAULT_SCENE_MARGIN = 100.0
APP_NAME = "Electrode Array Editor"
# Fit-view framing behavior.
FIT_PADDING_MIN = 80.0
FIT_PADDING_RATIO = 0.2
# Scene margin as a multiple of the array span, so a fitted view can zoom
# out and pan instead of sitting locked to sceneRect.
SCENE_FIT_GROW = 8.0
TAB_ELECTRODES = 0
TAB_PADS = 1
TAB_MARKERS = 2
MIXED_SHAPE_LABEL = "(mixed)"
XY_EDIT_TOOLTIP = (
    "Leave empty to keep this coordinate. A filled value is applied to every "
    "selected item (aligns them on that axis)."
)
NEW_ARRAY_WARN_COUNT = 1024
# Skip per-item inspector work when a rubber-band selects this many contacts.
LARGE_SELECTION_PANEL = 64


@dataclass(frozen=True)
class EditorState:
    """Full editor snapshot for undo/redo (electrodes, pads, markers, schema, labels, units, path)."""

    electrodes: dict[int, ElectrodeSnapshot]
    pads: dict[int, PadSnapshot]
    orientation_markers: dict[int, OrientationMarkerSnapshot]
    attribute_schema: tuple[AttributeSpec, ...]
    map_labels: tuple[str, ...]
    si_units: str
    current_file_path: str | None


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
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        self.resize(1600, 800)
        self.current_file_path: str | None = None
        self.is_dirty = False
        self.si_units = "um"
        self.is_add_mode = False
        self.is_add_pad_mode = False
        self.is_add_marker_mode = False

        # Canonical electrode models keyed by eid.
        self.electrodes: dict[int, Electrode] = {}
        # Scene items keyed by same eid for sync.
        self.items: dict[int, ElectrodeView] = {}
        # Canonical pad models keyed by pad_id.
        self.pads: dict[int, Pad] = {}
        self.pad_items: dict[int, PadView] = {}
        self.orientation_markers: dict[int, OrientationMarker] = {}
        self.marker_items: dict[int, OrientationMarkerView] = {}
        # File-level electrode attribute schema (built-ins + extras).
        self.attribute_schema: list[AttributeSpec] = default_schema()
        self.attribute_edits: dict[str, QLineEdit] = {}
        self.visible_map_label_keys: set[str] = set(DEFAULT_MAP_LABEL_KEYS)
        self._map_label_checks: dict[str, QCheckBox] = {}
        self._map_label_actions: dict[str, QAction] = {}
        self._view_labels_menu = None
        self._map_labels_layout: QVBoxLayout | None = None
        self.undo_stack: list[EditorState] = []
        self.redo_stack: list[EditorState] = []
        self._max_history = 200
        self._is_restoring_state = False
        self._is_mutating_scene = False
        self._is_syncing_selection = False
        self._auto_selected_electrode_eids: set[int] = set()
        self._auto_selected_pad_ids: set[int] = set()
        self._clean_state: EditorState | None = None
        self._electrode_table_window: ElectrodeTableWindow | None = None
        self._visuals_refresh_pending = False
        self._panel_refresh_pending = False
        self._axes_cache: dict[int, tuple[list[float], list[float]]] = {}
        self._pad_link_cache: list[tuple[float, float, float, float]] | None = None
        self._pad_combo_sig: tuple | None = None
        self._pad_add_combo_sig: tuple | None = None
        self._defer_rubber_band_selection = False

        self.scene = GridScene(self)
        self.scene.set_axes_provider(self._grid_axes)
        self.scene.set_pad_link_provider(self._pad_link_segments)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        self.electrode_view = self._create_map_view()
        self.pads_map_view = self._create_map_view()
        self.view = self.electrode_view
        self.scene.active_view = self.electrode_view
        self.scene.electrode_map_view = self.electrode_view
        self.scene.pad_map_view = self.pads_map_view
        self.electrode_view.set_activated_callback(lambda: self._set_active_map_view(self.electrode_view))
        self.pads_map_view.set_activated_callback(lambda: self._set_active_map_view(self.pads_map_view))

        self._build_ui()
        self._build_menu()
        self._clean_state = self._capture_state()
        self._startup_done = False
        self._preload_thread: threading.Thread | None = None
        self._preload_started = False

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """
        Prompt to save before closing if there are unsaved changes.
        """
        if self.is_dirty:
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

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """Escape leaves add mode when the window has focus."""
        if event.key() == Qt.Key_Escape and self._is_adding():
            self._stop_all_add_modes()
            event.accept()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        """
        On first show: run startup workflow, then fit view once viewport is sized.
        """
        super().showEvent(event)
        if not self._startup_done:
            self._startup_done = True
            QTimer.singleShot(0, self._startup_workflow)
        else:
            QTimer.singleShot(0, self._fit_all_views)

    def _create_map_view(self) -> ElectrodeArrayView:
        """Build a mapping viewport bound to the shared scene."""
        view = ElectrodeArrayView(self.scene)
        view.set_add_callbacks(
            self._is_adding,
            self._add_point_at,
            self._stop_all_add_modes,
        )
        view.set_delete_callback(self._delete_selected)
        view.set_view_transform_changed_callback(self._refresh_label_layouts)
        view.set_rubber_band_callbacks(
            self._on_rubber_band_started,
            self._on_rubber_band_finished,
        )
        view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return view

    def _build_ui(self) -> None:
        """
        Build interface: mapping views on the left, inspector on the right.

        The scene shows electrodes and pads together. Two cameras share it,
        side by side: Electrodes (left, fitted to the array) and Pads (right).
        The inspector is grouped by task: array settings, selection, then
        Electrodes / Pads / Orientation marker tabs.
        """
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter)

        self.map_splitter = QSplitter(Qt.Horizontal)
        self.map_splitter.setChildrenCollapsible(False)
        self.map_splitter.addWidget(self.electrode_view)
        self.map_splitter.addWidget(self.pads_map_view)
        self.map_splitter.setStretchFactor(0, 1)
        self.map_splitter.setStretchFactor(1, 1)
        self.map_splitter.setSizes([560, 560])
        splitter.addWidget(self.map_splitter)
        splitter.addWidget(self._build_side_panel())
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([1120, 340])

        self.statusBar().showMessage(
            "Wheel: zoom  |  Middle-drag: pan  |  Del: delete  |  Ctrl+Z: undo"
        )
        self.statusBar().addPermanentWidget(QLabel(f"v{__version__}"))

    def _build_side_panel(self) -> QWidget:
        """Inspector: array, selection, then electrode/pad/marker parameterization."""
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(8)

        self._array_group = self._build_array_group()
        self._map_labels_group = self._build_map_labels_group()
        self._selection_group = self._build_selection_group()
        layout.addWidget(self._array_group)
        layout.addWidget(self._map_labels_group)
        layout.addWidget(self._selection_group)

        self.point_tabs = QTabWidget()
        self.point_tabs.addTab(self._build_electrode_tab(), "Electrodes")
        self.point_tabs.addTab(self._build_pad_tab(), "Pads")
        self.point_tabs.addTab(self._build_marker_tab(), "Orientation marker")
        self.point_tabs.currentChanged.connect(self._on_point_tab_changed)
        layout.addWidget(self.point_tabs, stretch=1)
        return panel

    @staticmethod
    def _make_row(*widgets: QWidget) -> QWidget:
        """Place several widgets on one form row (field + button, X + Y, …)."""
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for widget in widgets:
            if isinstance(widget, QPushButton):
                widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                layout.addWidget(widget)
            else:
                layout.addWidget(widget, stretch=1)
        return row

    @staticmethod
    def _form_layout(parent: QWidget) -> QFormLayout:
        """Shared form metrics so inspector groups align."""
        form = QFormLayout(parent)
        form.setContentsMargins(8, 10, 8, 8)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        return form

    @staticmethod
    def _scroll_area(inner: QWidget) -> QScrollArea:
        """Vertical-only scroll wrapper for a tab's property groups."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    def _make_add_geometry_fields(
        self,
        form: QFormLayout,
        shapes: tuple[str, ...],
        default_shape: str,
        default_radius: float,
    ) -> tuple[QComboBox, QLabel, QLineEdit, QLabel, QLineEdit]:
        """Shape and size rows for creating new items (not bound to the selection)."""
        shape_combo = QComboBox()
        shape_combo.addItems(list(shapes))
        shape_combo.setCurrentText(default_shape)
        shape_combo.setToolTip("Geometry of items created with Add.")
        size_edit = QLineEdit(f"{size_field_from_stored_half(default_shape, default_radius):.2f}")
        size_edit.setToolTip(
            "Size of items created with Add. Radius for circle, side length for square, width for rect."
        )
        size_label = QLabel(primary_size_field_label(default_shape))
        height_edit = QLineEdit(f"{size_field_from_stored_half('rect', default_radius):.2f}")
        height_edit.setToolTip("Full height of items created with Add (rect only).")
        height_label = QLabel(height_field_label())
        form.addRow("Shape", shape_combo)
        form.addRow(size_label, size_edit)
        form.addRow(height_label, height_edit)
        self._set_height_row_visible(
            form, height_label, height_edit, shape_uses_height(default_shape)
        )
        return shape_combo, size_label, size_edit, height_label, height_edit

    def _build_array_group(self) -> QGroupBox:
        """File-level settings that do not depend on the current selection."""
        box = QGroupBox("Array")
        form = self._form_layout(box)
        self.si_units_edit = QLineEdit(self.si_units)
        self.si_units_edit.setPlaceholderText("um, mm, …")
        self.si_units_edit.setToolTip("Distance unit stored in the file.")
        b_units = QPushButton("Apply")
        b_units.setAutoDefault(False)
        b_units.clicked.connect(self._apply_si_units)
        b_fit = QPushButton("Fit View")
        b_fit.setAutoDefault(False)
        b_fit.setToolTip("Fit both mapping views: electrodes on the left, pads on the right.")
        b_fit.clicked.connect(self._fit_view)
        b_table = QPushButton("Electrode table")
        b_table.setAutoDefault(False)
        b_table.setToolTip("Open a table of all electrodes. The editor stays usable while it is open.")
        b_table.clicked.connect(self._show_electrode_table)
        form.addRow("si_units", self._make_row(self.si_units_edit, b_units))
        form.addRow(self._make_row(b_fit, b_table))
        return box

    def _build_map_labels_group(self) -> QGroupBox:
        """Choose which electrode IDs are drawn on both mapping views."""
        box = QGroupBox("Map labels")
        box.setToolTip(
            "Choose which electrode IDs are drawn on both mapping views. "
            "The list matches the attributes in the Electrodes tab."
        )
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(4)
        self._map_labels_layout = layout
        self._rebuild_map_label_checks()
        return box

    def _build_selection_group(self) -> QGroupBox:
        """Selection summary and group translation (electrodes, pads, markers)."""
        box = QGroupBox("Selection")
        form = self._form_layout(box)
        self.selected_count_label = QLabel("0 electrode(s), 0 pad(s), 0 marker(s)")
        self.dx_edit = QLineEdit("0")
        self.dy_edit = QLineEdit("0")
        self.dx_edit.setToolTip("Horizontal offset applied to the current selection.")
        self.dy_edit.setToolTip("Vertical offset applied to the current selection.")
        b_move = QPushButton("Move")
        b_move.setAutoDefault(False)
        b_move.clicked.connect(self._move_selection_by_delta)
        b_distribute_x = QPushButton("Along X")
        b_distribute_x.setAutoDefault(False)
        b_distribute_x.setToolTip(
            "Space selected electrodes, pads, and orientation markers evenly "
            "between the leftmost and rightmost item of each type. Items selected "
            "only because they are linked to the selection are left unchanged."
        )
        b_distribute_x.clicked.connect(lambda _checked=False: self._distribute_selection("x"))
        b_distribute_y = QPushButton("Along Y")
        b_distribute_y.setAutoDefault(False)
        b_distribute_y.setToolTip(
            "Space selected electrodes, pads, and orientation markers evenly "
            "between the items with the smallest and largest Y of each type. "
            "Items selected only because they are linked to the selection are left unchanged."
        )
        b_distribute_y.clicked.connect(lambda _checked=False: self._distribute_selection("y"))
        form.addRow("Selected", self.selected_count_label)
        form.addRow("dX / dY", self._make_row(self.dx_edit, self.dy_edit, b_move))
        form.addRow("Distribute", self._make_row(b_distribute_x, b_distribute_y))
        return box

    def _build_electrode_tab(self) -> QWidget:
        """Find, geometry, attributes, then add/delete actions with creation defaults."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        find_box = QGroupBox("Find")
        find_form = self._form_layout(find_box)
        self.attribute_find_edit = QLineEdit("")
        self.attribute_find_edit.setPlaceholderText("any attribute value")
        self.attribute_find_edit.setToolTip(
            "Search all electrode attributes (INTAN ID, potentiostat, manufacturer, shank, extras). "
            "Every matching electrode is selected."
        )
        self.attribute_find_edit.setClearButtonEnabled(True)
        b_find_attribute = QPushButton("Find")
        b_find_attribute.setAutoDefault(False)
        b_find_attribute.clicked.connect(self._find_by_attributes)
        self.attribute_find_edit.returnPressed.connect(self._find_by_attributes)
        find_form.addRow("Attributes", self._make_row(self.attribute_find_edit, b_find_attribute))
        self._electrode_find_box = find_box
        layout.addWidget(find_box)

        geom_box = QGroupBox("Geometry")
        e_form = self._form_layout(geom_box)
        self.radius_edit = QLineEdit("")
        self.height_edit = QLineEdit("")
        self.x_edit = QLineEdit("")
        self.y_edit = QLineEdit("")
        self.x_edit.setToolTip(XY_EDIT_TOOLTIP)
        self.y_edit.setToolTip(XY_EDIT_TOOLTIP)
        self.contact_plane_axis_edit = QLineEdit("")
        self.contact_plane_axis_edit.setPlaceholderText("x0, x1, y0, y1")
        self.shape_combo = QComboBox()
        self.shape_combo.addItems(list(ELECTRODE_SHAPES))
        self.electrode_size_label = QLabel(primary_size_field_label(DEFAULT_SHAPE))
        self.electrode_height_label = QLabel(height_field_label())
        self._electrode_size_shape = DEFAULT_SHAPE
        e_form.addRow("Shape", self.shape_combo)
        e_form.addRow(self.electrode_size_label, self.radius_edit)
        e_form.addRow(self.electrode_height_label, self.height_edit)
        e_form.addRow("X / Y", self._make_row(self.x_edit, self.y_edit))
        e_form.addRow("Contact plane", self.contact_plane_axis_edit)
        self.label_position_combo = self._make_label_position_combo()
        e_form.addRow("Label position", self.label_position_combo)
        self.label_orientation_combo = self._make_label_orientation_combo()
        e_form.addRow("Label orientation", self.label_orientation_combo)
        self._electrode_geom_form = e_form
        self.shape_combo.currentTextChanged.connect(self._on_electrode_shape_combo_changed)
        self._set_height_row_visible(
            e_form,
            self.electrode_height_label,
            self.height_edit,
            shape_uses_height(DEFAULT_SHAPE),
        )

        attributes_box = QGroupBox("Attributes")
        attributes_outer = QVBoxLayout(attributes_box)
        attributes_outer.setContentsMargins(8, 10, 8, 8)
        attributes_outer.setSpacing(6)
        self.attributes_form = QFormLayout()
        self.attributes_form.setContentsMargins(0, 0, 0, 0)
        self.attributes_form.setHorizontalSpacing(8)
        self.attributes_form.setVerticalSpacing(6)
        attributes_outer.addLayout(self.attributes_form)
        self.b_add_attribute = QPushButton("Add attribute")
        self.b_add_attribute.setAutoDefault(False)
        self.b_add_attribute.clicked.connect(self._add_attribute_interactive)
        attributes_outer.addWidget(self.b_add_attribute)
        self._rebuild_attribute_fields()

        self.b_apply_edits = QPushButton("Confirm electrode edits")
        self.b_apply_edits.setAutoDefault(False)
        self.b_apply_edits.clicked.connect(self._apply_pending_edits)

        scroll_inner = QWidget()
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        self._electrode_geom_box = geom_box
        self._electrode_attributes_box = attributes_box
        scroll_layout.addWidget(geom_box)
        scroll_layout.addWidget(attributes_box)
        scroll_layout.addStretch(1)
        layout.addWidget(self._scroll_area(scroll_inner), stretch=1)
        layout.addWidget(self.b_apply_edits)

        tools = QGroupBox("Actions")
        tools.setToolTip(
            "Defaults for newly created electrodes. Independent of the current selection."
        )
        tools_form = self._form_layout(tools)
        self._add_electrode_actions_form = tools_form
        (
            self.add_electrode_shape_combo,
            self.add_electrode_size_label,
            self.add_electrode_size_edit,
            self.add_electrode_height_label,
            self.add_electrode_height_edit,
        ) = self._make_add_geometry_fields(
            tools_form,
            ELECTRODE_SHAPES,
            DEFAULT_SHAPE,
            DEFAULT_RADIUS,
        )
        self._add_electrode_size_shape = DEFAULT_SHAPE
        self.add_electrode_shape_combo.currentTextChanged.connect(
            self._on_add_electrode_shape_changed
        )
        self.add_electrode_label_position_combo = self._make_label_position_combo()
        self.add_electrode_label_orientation_combo = self._make_label_orientation_combo()
        self.add_electrode_label_position_combo.setToolTip(
            "Map-label side of electrodes created with Add. Independent of the current selection."
        )
        self.add_electrode_label_orientation_combo.setToolTip(
            "Map-label rotation of electrodes created with Add. Independent of the current selection."
        )
        tools_form.addRow("Label position", self.add_electrode_label_position_combo)
        tools_form.addRow("Label orientation", self.add_electrode_label_orientation_combo)
        self.b_add_electrode = QPushButton("Add Electrode")
        self.b_add_electrode.setCheckable(True)
        self.b_add_electrode.setAutoDefault(False)
        self.b_add_electrode.toggled.connect(self._set_add_mode)
        b_delete = QPushButton("Delete selected")
        b_delete.setAutoDefault(False)
        b_delete.clicked.connect(self._delete_selected_electrodes)
        tools_form.addRow(self.b_add_electrode)
        tools_form.addRow(b_delete)
        self._electrode_actions_box = tools
        layout.addWidget(tools)
        return tab

    def _build_pad_tab(self) -> QWidget:
        """Find, properties, then add/delete actions with creation defaults."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        find_box = QGroupBox("Find")
        find_form = self._form_layout(find_box)
        self.pad_id_find_edit = QLineEdit("")
        self.pad_id_find_edit.setPlaceholderText("e.g. 3")
        self.pad_id_find_edit.setClearButtonEnabled(True)
        b_find_pad = QPushButton("Find")
        b_find_pad.setAutoDefault(False)
        b_find_pad.clicked.connect(self._find_by_pad_id)
        self.pad_id_find_edit.returnPressed.connect(self._find_by_pad_id)
        find_form.addRow("Pad ID", self._make_row(self.pad_id_find_edit, b_find_pad))
        self._pad_find_box = find_box
        layout.addWidget(find_box)

        pad_edit_box = QGroupBox("Properties")
        p_form = self._form_layout(pad_edit_box)
        self.pad_id_edit = QLineEdit("")
        self.pad_id_edit.setReadOnly(True)
        self.pad_id_edit.setToolTip("Editor-assigned identifier (like electrode ID). Not editable.")
        self.pad_radius_edit = QLineEdit("")
        self.pad_height_edit = QLineEdit("")
        self.pad_x_edit = QLineEdit("")
        self.pad_y_edit = QLineEdit("")
        self.pad_x_edit.setToolTip(XY_EDIT_TOOLTIP)
        self.pad_y_edit.setToolTip(XY_EDIT_TOOLTIP)
        self.pad_electrode_combo = QComboBox()
        self.pad_shape_combo = QComboBox()
        self.pad_shape_combo.addItems(list(PAD_SHAPES))
        self.pad_size_label = QLabel(primary_size_field_label(DEFAULT_PAD_SHAPE))
        self.pad_height_label = QLabel(height_field_label())
        self._pad_size_shape = DEFAULT_PAD_SHAPE
        p_form.addRow("Pad ID", self.pad_id_edit)
        p_form.addRow("Shape", self.pad_shape_combo)
        p_form.addRow(self.pad_size_label, self.pad_radius_edit)
        p_form.addRow(self.pad_height_label, self.pad_height_edit)
        p_form.addRow("X / Y", self._make_row(self.pad_x_edit, self.pad_y_edit))
        p_form.addRow("Associated electrode", self.pad_electrode_combo)
        self.pad_label_position_combo = self._make_label_position_combo()
        p_form.addRow("Label position", self.pad_label_position_combo)
        self.pad_label_orientation_combo = self._make_label_orientation_combo()
        p_form.addRow("Label orientation", self.pad_label_orientation_combo)
        self._pad_form = p_form
        self.pad_shape_combo.currentTextChanged.connect(self._on_pad_shape_combo_changed)
        self._set_height_row_visible(
            p_form,
            self.pad_height_label,
            self.pad_height_edit,
            shape_uses_height(DEFAULT_PAD_SHAPE),
        )

        self.b_apply_pad_edits = QPushButton("Confirm pad edits")
        self.b_apply_pad_edits.setAutoDefault(False)
        self.b_apply_pad_edits.clicked.connect(self._apply_pending_pad_edits)

        scroll_inner = QWidget()
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        self._pad_edit_box = pad_edit_box
        scroll_layout.addWidget(pad_edit_box)
        scroll_layout.addStretch(1)
        layout.addWidget(self._scroll_area(scroll_inner), stretch=1)
        layout.addWidget(self.b_apply_pad_edits)

        tools = QGroupBox("Actions")
        tools.setToolTip(
            "Defaults for newly created pads. Independent of the current selection."
        )
        tools_form = self._form_layout(tools)
        self._add_pad_actions_form = tools_form
        (
            self.add_pad_shape_combo,
            self.add_pad_size_label,
            self.add_pad_size_edit,
            self.add_pad_height_label,
            self.add_pad_height_edit,
        ) = self._make_add_geometry_fields(
            tools_form,
            PAD_SHAPES,
            DEFAULT_PAD_SHAPE,
            DEFAULT_PAD_RADIUS,
        )
        self._add_pad_size_shape = DEFAULT_PAD_SHAPE
        self.add_pad_shape_combo.currentTextChanged.connect(self._on_add_pad_shape_changed)
        self.add_pad_label_position_combo = self._make_label_position_combo()
        self.add_pad_label_orientation_combo = self._make_label_orientation_combo()
        self.add_pad_label_position_combo.setToolTip(
            "Map-label side of pads created with Add. Independent of the current selection."
        )
        self.add_pad_label_orientation_combo.setToolTip(
            "Map-label rotation of pads created with Add. Independent of the current selection."
        )
        tools_form.addRow("Label position", self.add_pad_label_position_combo)
        tools_form.addRow("Label orientation", self.add_pad_label_orientation_combo)
        self.pad_add_electrode_combo = QComboBox()
        self.pad_add_electrode_combo.setMaxVisibleItems(20)
        self.b_add_pad = QPushButton("Add Pad")
        self.b_add_pad.setCheckable(True)
        self.b_add_pad.setAutoDefault(False)
        self.b_add_pad.toggled.connect(self._set_add_pad_mode)
        b_delete_pad = QPushButton("Delete selected")
        b_delete_pad.setAutoDefault(False)
        b_delete_pad.clicked.connect(self._delete_selected_pads)
        tools_form.addRow("Electrode for new pad", self.pad_add_electrode_combo)
        tools_form.addRow(self.b_add_pad)
        tools_form.addRow(b_delete_pad)
        self._pad_actions_box = tools
        layout.addWidget(tools)
        return tab

    def _build_marker_tab(self) -> QWidget:
        """Find, properties, then add/delete actions with creation defaults."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.setSpacing(8)

        find_box = QGroupBox("Find")
        find_form = self._form_layout(find_box)
        self.marker_id_find_edit = QLineEdit("")
        self.marker_id_find_edit.setPlaceholderText("e.g. 0")
        self.marker_id_find_edit.setClearButtonEnabled(True)
        b_find_marker = QPushButton("Find")
        b_find_marker.setAutoDefault(False)
        b_find_marker.clicked.connect(self._find_by_marker_id)
        self.marker_id_find_edit.returnPressed.connect(self._find_by_marker_id)
        find_form.addRow("Marker ID", self._make_row(self.marker_id_find_edit, b_find_marker))
        self._marker_find_box = find_box
        layout.addWidget(find_box)

        marker_edit_box = QGroupBox("Properties")
        m_form = self._form_layout(marker_edit_box)
        self.marker_id_edit = QLineEdit("")
        self.marker_id_edit.setReadOnly(True)
        self.marker_id_edit.setToolTip("Editor-assigned identifier. Not editable.")
        self.marker_radius_edit = QLineEdit("")
        self.marker_height_edit = QLineEdit("")
        self.marker_x_edit = QLineEdit("")
        self.marker_y_edit = QLineEdit("")
        self.marker_x_edit.setToolTip(XY_EDIT_TOOLTIP)
        self.marker_y_edit.setToolTip(XY_EDIT_TOOLTIP)
        self.marker_shape_combo = QComboBox()
        self.marker_shape_combo.addItems(list(MARKER_SHAPES))
        self.marker_size_label = QLabel(primary_size_field_label(DEFAULT_MARKER_SHAPE))
        self.marker_height_label = QLabel(height_field_label())
        self._marker_size_shape = DEFAULT_MARKER_SHAPE
        m_form.addRow("Marker ID", self.marker_id_edit)
        m_form.addRow("Shape", self.marker_shape_combo)
        m_form.addRow(self.marker_size_label, self.marker_radius_edit)
        m_form.addRow(self.marker_height_label, self.marker_height_edit)
        m_form.addRow("X / Y", self._make_row(self.marker_x_edit, self.marker_y_edit))
        self._marker_form = m_form
        self.marker_shape_combo.currentTextChanged.connect(self._on_marker_shape_combo_changed)
        self._set_height_row_visible(
            m_form,
            self.marker_height_label,
            self.marker_height_edit,
            shape_uses_height(DEFAULT_MARKER_SHAPE),
        )

        self.b_apply_marker_edits = QPushButton("Confirm marker edits")
        self.b_apply_marker_edits.setAutoDefault(False)
        self.b_apply_marker_edits.clicked.connect(self._apply_pending_marker_edits)

        scroll_inner = QWidget()
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        self._marker_edit_box = marker_edit_box
        scroll_layout.addWidget(marker_edit_box)
        scroll_layout.addStretch(1)
        layout.addWidget(self._scroll_area(scroll_inner), stretch=1)
        layout.addWidget(self.b_apply_marker_edits)

        tools = QGroupBox("Actions")
        tools.setToolTip(
            "Defaults for newly created orientation markers. Independent of the current selection. "
            "Markers have no map label."
        )
        tools_form = self._form_layout(tools)
        self._add_marker_actions_form = tools_form
        (
            self.add_marker_shape_combo,
            self.add_marker_size_label,
            self.add_marker_size_edit,
            self.add_marker_height_label,
            self.add_marker_height_edit,
        ) = self._make_add_geometry_fields(
            tools_form,
            MARKER_SHAPES,
            DEFAULT_MARKER_SHAPE,
            DEFAULT_MARKER_RADIUS,
        )
        self._add_marker_size_shape = DEFAULT_MARKER_SHAPE
        self.add_marker_shape_combo.currentTextChanged.connect(self._on_add_marker_shape_changed)
        self.b_add_marker = QPushButton("Add Orientation Marker")
        self.b_add_marker.setCheckable(True)
        self.b_add_marker.setAutoDefault(False)
        self.b_add_marker.toggled.connect(self._set_add_marker_mode)
        b_delete_marker = QPushButton("Delete selected")
        b_delete_marker.setAutoDefault(False)
        b_delete_marker.clicked.connect(self._delete_selected_markers)
        tools_form.addRow(self.b_add_marker)
        tools_form.addRow(b_delete_marker)
        self._marker_actions_box = tools
        layout.addWidget(tools)
        return tab

    def _build_menu(self) -> None:
        """
        Create File, View, and Help menus.
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

        file_menu.addSeparator()

        act_export_si = QAction("Export for SpikeInterface...", self)
        act_export_si.triggered.connect(self._menu_export_spikeinterface)
        file_menu.addAction(act_export_si)

        act_export_xlsx = QAction("Export array as XLSX...", self)
        act_export_xlsx.triggered.connect(self._menu_export_matrix_xlsx)
        file_menu.addAction(act_export_xlsx)

        edit_menu = self.menuBar().addMenu("Edit")
        act_undo = QAction("Undo", self)
        act_undo.setShortcut(QKeySequence.Undo)
        act_undo.triggered.connect(self._undo)
        edit_menu.addAction(act_undo)
        act_redo = QAction("Redo", self)
        act_redo.setShortcut(QKeySequence.Redo)
        act_redo.triggered.connect(self._redo)
        edit_menu.addAction(act_redo)

        view_menu = self.menuBar().addMenu("View")
        act_fit = QAction("Fit View", self)
        act_fit.setShortcut(QKeySequence("Ctrl+0"))
        act_fit.triggered.connect(self._fit_view)
        view_menu.addAction(act_fit)
        act_table = QAction("Electrode table...", self)
        act_table.setShortcut(QKeySequence("Ctrl+T"))
        act_table.triggered.connect(self._show_electrode_table)
        view_menu.addAction(act_table)
        self._view_labels_menu = view_menu.addMenu("Map labels")
        self._rebuild_map_label_menu()

        help_menu = self.menuBar().addMenu("Help")
        act_shortcuts = QAction("Keyboard shortcuts...", self)
        act_shortcuts.triggered.connect(self._show_shortcuts)
        help_menu.addAction(act_shortcuts)
        help_menu.addSeparator()
        act_about = QAction("About...", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _show_shortcuts(self) -> None:
        """Show interaction shortcuts that used to occupy the side panel."""
        QMessageBox.information(
            self,
            "Keyboard shortcuts",
            "Click: select one\n"
            "Ctrl+Click: add/remove from selection\n"
            "Drag empty area: box selection\n"
            "Middle-drag: pan the view\n"
            "Wheel: zoom\n"
            "Move: X and/or Y on the selection (empty keeps that axis), or dX/dY\n"
            "Distribute Along X / Along Y: even spacing between the two extremes of each selected type\n"
            "Add Electrode: set shape/size/label in Actions, then click the scene\n"
            "Add Pad: set shape/size/label in Actions, choose an electrode, then click the scene\n"
            "Add Orientation Marker: set shape/size in Actions, then click the scene\n"
            "Escape: leave add mode\n"
            "Delete / Backspace: delete selected\n"
            "Ctrl+Z / Ctrl+Y: undo / redo\n"
            "Ctrl+0: fit both mapping views (electrodes and pads)\n"
            "Ctrl+T: electrode table\n"
            "View > Map labels: choose IDs drawn on both maps\n"
            "Label position: above / below / left / right of each item (native file only)\n"
            "Label orientation: 0° / 90° / 180° / 270° clockwise (native file only)",
        )

    def _show_about(self) -> None:
        """Show application name, version, and native file format."""
        QMessageBox.about(
            self,
            f"About {APP_NAME}",
            f"<h3>{APP_NAME} {__version__}</h3>"
            "<p>GUI and library to create and modify Multi-Electrode Arrays.</p>"
            f"<p>Native file format: mea_editor {NATIVE_VERSION}</p>"
            "<p>Keep native JSON as the source of truth. SpikeInterface and XLSX "
            "are exports. Orientation markers are saved natively and in Excel; "
            "they are omitted from SpikeInterface. Label position and "
            "orientation are native JSON only.</p>"
            "<p>License: MIT<br>"
            "Wireless Neural Interface Team</p>",
        )

    def _classified_selected_items(
        self,
    ) -> tuple[list[ElectrodeView], list[PadView], list[OrientationMarkerView]]:
        """One pass over the scene selection, split by item type."""
        electrodes: list[ElectrodeView] = []
        pads: list[PadView] = []
        markers: list[OrientationMarkerView] = []
        for item in self.scene.selectedItems():
            if isinstance(item, ElectrodeView):
                electrodes.append(item)
            elif isinstance(item, PadView):
                pads.append(item)
            elif isinstance(item, OrientationMarkerView):
                markers.append(item)
        return electrodes, pads, markers

    def _user_selected_classified_items(
        self,
    ) -> tuple[list[ElectrodeView], list[PadView], list[OrientationMarkerView]]:
        """Scene selection without pads/electrodes added only as associated counterparts."""
        electrodes, pads, markers = self._classified_selected_items()
        return (
            [item for item in electrodes if item.model.eid not in self._auto_selected_electrode_eids],
            [item for item in pads if item.model.pad_id not in self._auto_selected_pad_ids],
            markers,
        )

    def _selected_electrode_items(self) -> list[ElectrodeView]:
        """Return currently selected items, filtered to ElectrodeView."""
        return [it for it in self.scene.selectedItems() if isinstance(it, ElectrodeView)]

    def _selected_pad_items(self) -> list[PadView]:
        """Return currently selected items, filtered to PadView."""
        return [it for it in self.scene.selectedItems() if isinstance(it, PadView)]

    def _selected_marker_items(self) -> list[OrientationMarkerView]:
        """Return currently selected items, filtered to OrientationMarkerView."""
        return [it for it in self.scene.selectedItems() if isinstance(it, OrientationMarkerView)]

    def _on_scene_selection_changed(self) -> None:
        """Keep associated pads and electrodes selected together, then refresh the panel."""
        if self._is_mutating_scene or self._is_adding() or self._is_syncing_selection:
            return
        if self._defer_rubber_band_selection:
            return
        self._sync_associated_selection()
        self._schedule_panel_refresh()

    def _on_rubber_band_started(self) -> None:
        """Do not sync pads/electrodes or rebuild the inspector while the band grows."""
        self._defer_rubber_band_selection = True

    def _on_rubber_band_finished(self) -> None:
        """Apply associated selection and the inspector once the drag ends."""
        if not self._defer_rubber_band_selection:
            return
        self._defer_rubber_band_selection = False
        if self._is_mutating_scene or self._is_adding() or self._is_syncing_selection:
            return
        self._sync_associated_selection()
        self._schedule_panel_refresh()

    def _sync_associated_selection(self) -> None:
        """Select each pad's electrode and each electrode's pad; drop stale auto-selections."""
        if self._is_syncing_selection or self._is_restoring_state:
            return
        self._is_syncing_selection = True
        try:
            _electrodes, pads, _markers = self._classified_selected_items()
            self._sync_associated_electrodes_from_pads(pads)
            electrodes, _pads, _markers = self._classified_selected_items()
            self._sync_associated_pads_from_electrodes(electrodes)
        finally:
            self._is_syncing_selection = False

    def _sync_associated_electrodes_from_pads(self, pad_items: list[PadView] | None = None) -> None:
        """Select each pad's electrode; drop auto-selected electrodes that are no longer needed."""
        selected_pads = pad_items if pad_items is not None else self._selected_pad_items()
        needed = {
            item.model.electrode_eid
            for item in selected_pads
            if item.model.electrode_eid in self.items
        }
        stale = {eid for eid in self._auto_selected_electrode_eids if eid not in needed}
        to_add = {eid for eid in needed if not self.items[eid].isSelected()}
        for eid in stale:
            if eid in self.items:
                self.items[eid].setSelected(False)
        self._auto_selected_electrode_eids -= stale
        for eid in to_add:
            self.items[eid].setSelected(True)
            self._auto_selected_electrode_eids.add(eid)

    def _sync_associated_pads_from_electrodes(self, electrode_items: list[ElectrodeView] | None = None) -> None:
        """Select each electrode's pad; drop auto-selected pads that are no longer needed."""
        selected_eids = {
            item.model.eid
            for item in (electrode_items if electrode_items is not None else self._selected_electrode_items())
        }
        needed = {
            pad_id
            for pad_id, pad in self.pads.items()
            if pad.electrode_eid in selected_eids and pad_id in self.pad_items
        }
        stale = {pad_id for pad_id in self._auto_selected_pad_ids if pad_id not in needed}
        to_add = {pad_id for pad_id in needed if not self.pad_items[pad_id].isSelected()}
        for pad_id in stale:
            if pad_id in self.pad_items:
                self.pad_items[pad_id].setSelected(False)
        self._auto_selected_pad_ids -= stale
        for pad_id in to_add:
            self.pad_items[pad_id].setSelected(True)
            self._auto_selected_pad_ids.add(pad_id)

    def _on_point_tab_changed(self, index: int) -> None:
        """Stop the other add-mode when switching parameterization tabs."""
        if not hasattr(self, "b_add_pad") or not hasattr(self, "b_add_electrode"):
            return
        if index != TAB_ELECTRODES and self.b_add_electrode.isChecked():
            self.b_add_electrode.setChecked(False)
        if index != TAB_PADS and self.b_add_pad.isChecked():
            self.b_add_pad.setChecked(False)
        if hasattr(self, "b_add_marker") and index != TAB_MARKERS and self.b_add_marker.isChecked():
            self.b_add_marker.setChecked(False)

    def _set_active_map_view(self, view: ElectrodeArrayView) -> None:
        """Remember which mapping viewport last received interaction."""
        self.view = view
        self.scene.active_view = view

    def _show_electrode_table(self) -> None:
        """Open (or raise) the non-modal table of all electrodes."""
        if self._electrode_table_window is None:
            self._electrode_table_window = ElectrodeTableWindow(self)
            self._electrode_table_window.electrodes_chosen.connect(self._select_from_electrode_table)
        selected = {item.model.eid for item in self._selected_electrode_items()}
        self._electrode_table_window.reload(
            self.electrodes.values(),
            self.pads.values(),
            self.attribute_schema,
            selected_eids=selected,
            scroll_to_selection=True,
        )
        self._electrode_table_window.show()
        self._electrode_table_window.raise_()
        self._electrode_table_window.activateWindow()

    def _sync_electrode_table(self, *, reload_data: bool) -> None:
        """Keep the electrode table in sync with the current array and selection."""
        win = self._electrode_table_window
        if win is None or not win.isVisible():
            return
        selected = {item.model.eid for item in self._selected_electrode_items()}
        if reload_data:
            win.reload(
                self.electrodes.values(),
                self.pads.values(),
                self.attribute_schema,
                selected_eids=selected,
            )
            return
        win.set_selected_eids(selected)

    def _select_from_electrode_table(self, eids: list[int]) -> None:
        """Select table-chosen electrodes in both mapping views (pads follow)."""
        if self._is_syncing_selection or self._is_restoring_state or self._is_adding():
            return
        matches = [self.items[eid] for eid in eids if eid in self.items]
        self.scene.clearSelection()
        self._auto_selected_electrode_eids.clear()
        self._auto_selected_pad_ids.clear()
        for item in matches:
            item.setSelected(True)
        if not matches:
            return
        united = matches[0].sceneBoundingRect()
        for item in matches[1:]:
            united = united.united(item.sceneBoundingRect())
        pad = 40.0
        self.electrode_view.ensureVisible(united.adjusted(-pad, -pad, pad, pad), 80, 80)
        selected_eids = {item.model.eid for item in matches}
        pad_items = [
            item for item in self.pad_items.values() if item.model.electrode_eid in selected_eids
        ]
        if pad_items:
            pad_rect = pad_items[0].sceneBoundingRect()
            for item in pad_items[1:]:
                pad_rect = pad_rect.united(item.sceneBoundingRect())
            self.pads_map_view.ensureVisible(pad_rect.adjusted(-pad, -pad, pad, pad), 80, 80)

    def _find_by_pad_id(self) -> None:
        """
        Select the pad whose editor-assigned ID matches the find field and scroll to it.
        """
        query = self.pad_id_find_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Find Pad ID", "Enter a Pad ID to search.")
            return
        if not self.pad_items:
            QMessageBox.information(self, "Find Pad ID", "No pads in the current array.")
            return
        try:
            pad_id = int(query)
        except ValueError:
            QMessageBox.information(self, "Find Pad ID", "Pad ID must be an integer.")
            return

        item = self.pad_items.get(pad_id)
        if item is None:
            QMessageBox.information(
                self,
                "Pad ID not found",
                f"No pad has ID {pad_id}.",
            )
            return

        self.scene.clearSelection()
        item.setSelected(True)
        pad = 40.0
        united = item.sceneBoundingRect().adjusted(-pad, -pad, pad, pad)
        self.pads_map_view.ensureVisible(united, 80, 80)
        self.point_tabs.setCurrentIndex(TAB_PADS)
        self._refresh_panel_values()

    def _find_by_marker_id(self) -> None:
        """Select the orientation marker whose ID matches the find field and scroll to it."""
        query = self.marker_id_find_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Find Marker ID", "Enter a Marker ID to search.")
            return
        if not self.marker_items:
            QMessageBox.information(self, "Find Marker ID", "No orientation markers in the current array.")
            return
        try:
            marker_id = int(query)
        except ValueError:
            QMessageBox.information(self, "Find Marker ID", "Marker ID must be an integer.")
            return

        item = self.marker_items.get(marker_id)
        if item is None:
            QMessageBox.information(
                self,
                "Marker ID not found",
                f"No orientation marker has ID {marker_id}.",
            )
            return

        self.scene.clearSelection()
        item.setSelected(True)
        pad = 40.0
        united = item.sceneBoundingRect().adjusted(-pad, -pad, pad, pad)
        self.electrode_view.ensureVisible(united, 80, 80)
        self.pads_map_view.ensureVisible(united, 80, 80)
        self.point_tabs.setCurrentIndex(TAB_MARKERS)
        self._refresh_panel_values()

    def _electrode_attribute_texts(self, model: Electrode) -> list[str]:
        """String forms of every schema (and leftover extra) attribute on one electrode."""
        keys = [spec.key for spec in self.attribute_schema]
        seen = set(keys)
        for key in model.extra:
            if key not in seen:
                keys.append(key)
                seen.add(key)
        texts: list[str] = []
        for key in keys:
            texts.append(str(model.get_attribute(key)).strip())
        texts.append(f"{int(model.potentiostat_id):03d}")
        return texts

    def _find_by_attributes(self) -> None:
        """
        Select every electrode that has an attribute matching the find field, then scroll to them.

        Matching order: exact (after strip), then case-insensitive exact.
        Built-in identifiers and file-defined extra attributes are all searched.
        """
        query = self.attribute_find_edit.text().strip()
        if not query:
            QMessageBox.information(self, "Find attributes", "Enter a value to search in all attributes.")
            return
        if not self.items:
            QMessageBox.information(self, "Find attributes", "No electrodes in the current array.")
            return

        def matches_query(model: Electrode, *, ignore_case: bool) -> bool:
            needle = query.lower() if ignore_case else query
            for text in self._electrode_attribute_texts(model):
                haystack = text.lower() if ignore_case else text
                if haystack == needle:
                    return True
            return False

        matches = [it for it in self.items.values() if matches_query(it.model, ignore_case=False)]
        if not matches:
            matches = [it for it in self.items.values() if matches_query(it.model, ignore_case=True)]
        if not matches:
            QMessageBox.information(
                self,
                "Attribute not found",
                f"No electrode has an attribute equal to « {query} ».",
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
        self.electrode_view.ensureVisible(united, 80, 80)
        self.point_tabs.setCurrentIndex(TAB_ELECTRODES)
        self._refresh_panel_values()

    def _grid_axes(self, view=None) -> tuple[list[float], list[float]]:
        """Return sorted unique X/Y coordinates for grid and axes of one mapping view."""
        key = id(view)
        cached = self._axes_cache.get(key)
        if cached is not None:
            return cached
        if view is self.pads_map_view and (self.pads or self.orientation_markers):
            models = list(self.pads.values()) + list(self.orientation_markers.values())
        elif view is self.electrode_view and (self.electrodes or self.orientation_markers):
            models = list(self.electrodes.values()) + list(self.orientation_markers.values())
        else:
            models = (
                list(self.electrodes.values())
                + list(self.pads.values())
                + list(self.orientation_markers.values())
            )
        xs = sorted({round(model.x, 6) for model in models})
        ys = sorted({round(model.y, 6) for model in models})
        self._axes_cache[key] = (xs, ys)
        return xs, ys

    def _pad_link_segments(self) -> list[tuple[float, float, float, float]]:
        """Cached pad-to-electrode segments for the pad mapping overlay."""
        if self._pad_link_cache is not None:
            return self._pad_link_cache
        segments: list[tuple[float, float, float, float]] = []
        for pad in self.pads.values():
            electrode = self.electrodes.get(pad.electrode_eid)
            if electrode is None:
                continue
            segments.append((pad.x, pad.y, electrode.x, electrode.y))
        self._pad_link_cache = segments
        return segments

    def _invalidate_geometry_caches(self) -> None:
        """Drop axis and link caches after positions or membership change."""
        self._axes_cache.clear()
        self._pad_link_cache = None

    def _models_bounds_rect(self, models, margin: float = 0.0) -> QRectF:
        """Bounding rect of contact models (center + half-extents)."""
        extents: list[tuple[float, float, float, float]] = []
        for m in models:
            half_x, half_y = contact_half_extents(m.shape, m.radius, m.height)
            extents.append((m.x, m.y, half_x, half_y))
        if not extents:
            return QRectF(-1.0, -1.0, 2.0, 2.0)
        min_x = min(x - half_x for x, y, half_x, half_y in extents)
        max_x = max(x + half_x for x, y, half_x, half_y in extents)
        min_y = min(y - half_y for x, y, half_x, half_y in extents)
        max_y = max(y + half_y for x, y, half_x, half_y in extents)
        rect = QRectF(min_x, min_y, max(max_x - min_x, 1.0), max(max_y - min_y, 1.0))
        if margin > 0:
            rect = rect.adjusted(-margin, -margin, margin, margin)
        return rect

    def _array_bounds_rect(self, margin: float = 0.0) -> QRectF:
        """Bounding rect of all electrodes, pads, and orientation markers."""
        parts: list[QRectF] = []
        contacts = list(self.electrodes.values()) + list(self.pads.values())
        if contacts:
            parts.append(self._models_bounds_rect(contacts))
        if self.orientation_markers:
            parts.append(self._marker_bounds_rect())
        if not parts:
            rect = QRectF(-1.0, -1.0, 2.0, 2.0)
        else:
            rect = parts[0]
            for part in parts[1:]:
                rect = rect.united(part)
        if margin > 0:
            rect = rect.adjusted(-margin, -margin, margin, margin)
        return rect

    def _electrode_bounds_rect(self, margin: float = 0.0) -> QRectF:
        """Bounding rect of electrodes only."""
        return self._models_bounds_rect(self.electrodes.values(), margin=margin)

    def _pad_bounds_rect(self, margin: float = 0.0) -> QRectF:
        """Bounding rect of pads only."""
        return self._models_bounds_rect(self.pads.values(), margin=margin)

    def _marker_bounds_rect(self, margin: float = 0.0) -> QRectF:
        """Bounding rect of orientation markers (center + half-extents)."""
        return self._models_bounds_rect(self.orientation_markers.values(), margin=margin)

    def _capture_state(self) -> EditorState:
        """Capture full state snapshot for undo/redo."""
        return EditorState(
            electrodes={eid: m.snapshot() for eid, m in self.electrodes.items()},
            pads={pad_id: m.snapshot() for pad_id, m in self.pads.items()},
            orientation_markers={
                marker_id: m.snapshot() for marker_id, m in self.orientation_markers.items()
            },
            attribute_schema=tuple(self.attribute_schema),
            map_labels=tuple(sorted(self.visible_map_label_keys)),
            si_units=self.si_units,
            current_file_path=self.current_file_path,
        )

    def _mark_clean(self) -> None:
        """Remember the last saved/loaded state for the dirty flag."""
        self._clean_state = self._capture_state()
        self.is_dirty = False
        self._update_title()

    def _refresh_dirty_flag(self) -> None:
        """Set is_dirty from a comparison with the last clean snapshot."""
        if self._clean_state is None:
            self.is_dirty = True
        else:
            self.is_dirty = not self._states_equal(self._capture_state(), self._clean_state)
        self._update_title()

    def _set_array(
        self,
        models: list[Electrode],
        pads: list[Pad] | None = None,
        orientation_markers: list[OrientationMarker] | None = None,
        *,
        keep_pads: bool = False,
        keep_markers: bool = False,
    ) -> None:
        """
        Replace entire scene content with the given electrode, pad, and marker lists.
        """
        if pads is None:
            pads = list(self.pads.values()) if keep_pads else []
        if orientation_markers is None:
            orientation_markers = (
                list(self.orientation_markers.values()) if keep_markers else []
            )
        fill_electrodes_extras(models, self.attribute_schema, prune=False)
        eid_fixes, pad_id_fixes = ensure_unique_model_ids(models, pads)
        marker_id_fixes = ensure_unique_marker_ids(orientation_markers)
        if (eid_fixes or pad_id_fixes or marker_id_fixes) and not self._is_restoring_state:
            parts: list[str] = []
            if eid_fixes:
                parts.append(f"{eid_fixes} duplicate electrode ID(s) were reassigned.")
            if pad_id_fixes:
                parts.append(f"{pad_id_fixes} duplicate pad ID(s) were reassigned.")
            if marker_id_fixes:
                parts.append(f"{marker_id_fixes} duplicate orientation-marker ID(s) were reassigned.")
            if eid_fixes or pad_id_fixes:
                parts.append(
                    "Pads keep their stored electrode link: they stay on the electrode "
                    "that kept the original ID."
                )
            QMessageBox.warning(self, "Duplicate identifiers", "\n".join(parts))
        cameras = self._capture_map_cameras()
        visible = QRectF()
        for view in self._map_views():
            vis = view.visible_scene_rect()
            if vis.isValid() and not vis.isEmpty():
                visible = vis if visible.isNull() else visible.united(vis)
        self._auto_selected_electrode_eids.clear()
        self._auto_selected_pad_ids.clear()
        self._is_mutating_scene = True
        try:
            self.scene.clear()
            self.electrodes.clear()
            self.items.clear()
            self.pads.clear()
            self.pad_items.clear()
            self.orientation_markers.clear()
            self.marker_items.clear()
            for model in models:
                self._add_electrode_item(model)
            for pad in pads:
                self._add_pad_item(pad)
            for marker in orientation_markers:
                self._add_marker_item(marker)
            self.scene.has_orientation_markers = bool(self.orientation_markers)
            self._invalidate_geometry_caches()
            self._pad_combo_sig = None
            self._pad_add_combo_sig = None
            self._ensure_scene_rect(extra=visible if not visible.isNull() else None)
            self._restore_map_cameras(cameras)
        finally:
            self._is_mutating_scene = False
        self._update_duplicate_flags()
        self._refresh_pad_electrode_combo()
        self._refresh_pad_add_electrode_combo()
        self._refresh_panel_values()
        self.si_units_edit.setText(self.si_units)
        self._update_title()
        self._sync_electrode_table(reload_data=True)
        QTimer.singleShot(0, self._refresh_label_layouts)

    def _add_electrode_item(self, model: Electrode) -> ElectrodeView:
        """Add one electrode to the scene without rebuilding existing items."""
        item = ElectrodeView(
            model,
            self._on_scene_visuals_changed,
            self._schedule_panel_refresh,
            self._labels_for_electrode,
        )
        self.scene.addItem(item)
        self.electrodes[model.eid] = model
        self.items[model.eid] = item
        item.setFlag(QGraphicsItem.ItemIsSelectable, not self._is_adding())
        return item

    def _add_pad_item(self, pad: Pad) -> PadView:
        """Add one pad and its link line without rebuilding existing items."""
        item = PadView(
            pad,
            self._on_scene_visuals_changed,
            self._schedule_panel_refresh,
            self.electrodes.get,
            self._labels_for_electrode,
        )
        self.scene.addItem(item)
        self.pads[pad.pad_id] = pad
        self.pad_items[pad.pad_id] = item
        item.setFlag(QGraphicsItem.ItemIsSelectable, not self._is_adding())
        item.update_link()
        return item

    def _add_marker_item(self, marker: OrientationMarker) -> OrientationMarkerView:
        """Add one orientation marker without rebuilding existing items."""
        item = OrientationMarkerView(
            marker,
            self._on_scene_visuals_changed,
            self._schedule_panel_refresh,
        )
        self.scene.addItem(item)
        self.orientation_markers[marker.marker_id] = marker
        self.marker_items[marker.marker_id] = item
        self.scene.has_orientation_markers = True
        item.setFlag(QGraphicsItem.ItemIsSelectable, not self._is_adding())
        return item

    def _set_electrodes(self, models: list[Electrode]) -> None:
        """Replace scene electrodes while keeping current pads and markers."""
        self._set_array(models, keep_pads=True, keep_markers=True)

    def _next_unique_intan_id(self) -> str:
        """Return the first sequential INTAN ID not already used in the array."""
        existing = {str(model.intan_id).strip() for model in self.electrodes.values()}
        index = 0
        while True:
            candidate = format_intan_id(index)
            if candidate not in existing:
                return candidate
            index += 1

    def _next_unique_potentiostat_id(self) -> int:
        """Return the lowest unused potentiostat ID."""
        used = {model.potentiostat_id for model in self.electrodes.values()}
        next_id = 0
        while next_id in used:
            next_id += 1
        return next_id

    def _electrode_combo_label(self, model: Electrode) -> str:
        """Label used in the pad-to-electrode association combo (no pad/eid numbers)."""
        name = model.map_center_label()
        intan = str(model.intan_id).strip()
        return f"{name} · {intan}" if intan else name

    def _taken_electrode_eids(self, *, except_pad_ids: set[int] | None = None) -> set[int]:
        """Electrodes that already have at least one pad (optionally ignoring some pads)."""
        skip = except_pad_ids or set()
        return {pad.electrode_eid for pad in self.pads.values() if pad.pad_id not in skip}

    def _free_electrode_eids(self, *, extra: set[int] | None = None) -> list[int]:
        """Electrodes that have no pad yet, plus any eids in `extra` (still in the array)."""
        extra = extra or set()
        taken = self._taken_electrode_eids()
        return [
            eid
            for eid in sorted(self.electrodes)
            if eid not in taken or eid in extra
        ]

    def _refresh_pad_electrode_combo(
        self,
        selected_eid: int | None = None,
        mixed: bool = False,
        keep_eids: set[int] | None = None,
    ) -> None:
        """Rebuild the associated-electrode combo: none, free electrodes, current link(s)."""
        combo = self.pad_electrode_combo
        keep = set(keep_eids or ())
        if selected_eid is not None and selected_eid in self.electrodes:
            keep.add(selected_eid)
        eids = tuple(self._free_electrode_eids(extra=keep))
        sig = (eids, mixed)
        if sig == self._pad_combo_sig and combo.count() > 0:
            combo.blockSignals(True)
            if mixed:
                combo.setCurrentIndex(0)
            elif selected_eid is not None and selected_eid in self.electrodes:
                idx = combo.findData(selected_eid)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                combo.setCurrentIndex(combo.findData(-1))
            combo.blockSignals(False)
            return
        self._pad_combo_sig = sig
        combo.blockSignals(True)
        combo.clear()
        if mixed:
            combo.addItem("(mixed)", None)
        combo.addItem("(none)", -1)
        for eid in eids:
            combo.addItem(self._electrode_combo_label(self.electrodes[eid]), eid)
        if mixed:
            combo.setCurrentIndex(0)
        elif selected_eid is not None and selected_eid in self.electrodes:
            idx = combo.findData(selected_eid)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            combo.setCurrentIndex(combo.findData(-1))
        combo.blockSignals(False)

    def _refresh_pad_add_electrode_combo(self) -> None:
        """Rebuild the Add Pad list with electrodes that do not already have a pad."""
        combo = self.pad_add_electrode_combo
        eids = tuple(self._free_electrode_eids())
        if eids == self._pad_add_combo_sig and combo.count() == len(eids):
            return
        self._pad_add_combo_sig = eids
        current = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for eid in eids:
            combo.addItem(self._electrode_combo_label(self.electrodes[eid]), eid)
        if current is not None:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    @staticmethod
    def _set_height_row_visible(form: QFormLayout, label: QLabel, edit: QLineEdit, visible: bool) -> None:
        """Show or hide a Height row in a geometry form."""
        label.setVisible(visible)
        edit.setVisible(visible)
        form.setRowVisible(edit, visible)

    @staticmethod
    def _convert_size_edit(edit: QLineEdit, old_shape: str, new_shape: str) -> float | None:
        """Rewrite a size field so the stored half-extent stays the same. Return that half-extent."""
        text = edit.text().strip()
        if not text:
            return None
        try:
            stored = stored_half_from_size_field(old_shape, float(text))
            edit.setText(f"{size_field_from_stored_half(new_shape, stored):.2f}")
            return stored
        except ValueError:
            return None

    def _on_electrode_shape_combo_changed(self, shape: str) -> None:
        """Rename size fields and convert values so the drawn electrode keeps its extent."""
        if shape == MIXED_SHAPE_LABEL:
            return
        shape = normalize_contact_shape(shape, DEFAULT_SHAPE)
        if self._electrode_size_shape != MIXED_SHAPE_LABEL:
            stored = self._convert_size_edit(self.radius_edit, self._electrode_size_shape, shape)
        else:
            stored = None
        if shape_uses_height(shape):
            if stored is not None:
                self.height_edit.setText(f"{size_field_from_stored_half('rect', stored):.2f}")
            elif not self.height_edit.text().strip():
                self.height_edit.setText(self.radius_edit.text())
        self._set_electrode_size_label(shape)
        self._set_height_row_visible(
            self._electrode_geom_form,
            self.electrode_height_label,
            self.height_edit,
            shape_uses_height(shape),
        )

    def _set_electrode_size_label(self, shape: str) -> None:
        """Update the electrode size field caption without converting the current text."""
        if shape == MIXED_SHAPE_LABEL:
            return
        shape = normalize_contact_shape(shape, DEFAULT_SHAPE)
        self._electrode_size_shape = shape
        self.electrode_size_label.setText(primary_size_field_label(shape))

    def _on_pad_shape_combo_changed(self, shape: str) -> None:
        """Rename the size field and convert its value so the drawn pad keeps its extent."""
        if shape == MIXED_SHAPE_LABEL:
            return
        shape = normalize_contact_shape(shape, DEFAULT_PAD_SHAPE)
        if self._pad_size_shape != MIXED_SHAPE_LABEL:
            stored = self._convert_size_edit(self.pad_radius_edit, self._pad_size_shape, shape)
        else:
            stored = None
        if shape_uses_height(shape):
            if stored is not None:
                self.pad_height_edit.setText(f"{size_field_from_stored_half('rect', stored):.2f}")
            elif not self.pad_height_edit.text().strip():
                self.pad_height_edit.setText(self.pad_radius_edit.text())
        self._set_pad_size_label(shape)
        self._set_height_row_visible(
            self._pad_form,
            self.pad_height_label,
            self.pad_height_edit,
            shape_uses_height(shape),
        )

    def _set_pad_size_label(self, shape: str) -> None:
        """Update the pad size field caption without converting the current text."""
        if shape == MIXED_SHAPE_LABEL:
            return
        shape = normalize_contact_shape(shape, DEFAULT_PAD_SHAPE)
        self._pad_size_shape = shape
        self.pad_size_label.setText(primary_size_field_label(shape))

    def _on_marker_shape_combo_changed(self, shape: str) -> None:
        """Rename the size field and convert its value so the drawn marker keeps its extent."""
        if shape == MIXED_SHAPE_LABEL:
            return
        shape = normalize_contact_shape(shape, DEFAULT_MARKER_SHAPE)
        if self._marker_size_shape != MIXED_SHAPE_LABEL:
            stored = self._convert_size_edit(self.marker_radius_edit, self._marker_size_shape, shape)
        else:
            stored = None
        if shape_uses_height(shape):
            if stored is not None:
                self.marker_height_edit.setText(f"{size_field_from_stored_half('rect', stored):.2f}")
            elif not self.marker_height_edit.text().strip():
                self.marker_height_edit.setText(self.marker_radius_edit.text())
        self._set_marker_size_label(shape)
        self._set_height_row_visible(
            self._marker_form,
            self.marker_height_label,
            self.marker_height_edit,
            shape_uses_height(shape),
        )

    def _set_marker_size_label(self, shape: str) -> None:
        """Update the marker size field caption without converting the current text."""
        if shape == MIXED_SHAPE_LABEL:
            return
        shape = normalize_contact_shape(shape, DEFAULT_MARKER_SHAPE)
        self._marker_size_shape = shape
        self.marker_size_label.setText(primary_size_field_label(shape))

    def _apply_add_shape_change(
        self,
        shape: str,
        default_shape: str,
        old_shape: str,
        size_edit: QLineEdit,
        size_label: QLabel,
        height_label: QLabel,
        height_edit: QLineEdit,
        form: QFormLayout,
    ) -> str:
        """Convert add-mode size fields for a new shape and return the normalized shape."""
        shape = normalize_contact_shape(shape, default_shape)
        stored = self._convert_size_edit(size_edit, old_shape, shape)
        if shape_uses_height(shape):
            if stored is not None:
                height_edit.setText(f"{size_field_from_stored_half('rect', stored):.2f}")
            elif not height_edit.text().strip():
                height_edit.setText(size_edit.text())
        size_label.setText(primary_size_field_label(shape))
        self._set_height_row_visible(form, height_label, height_edit, shape_uses_height(shape))
        return shape

    def _on_add_electrode_shape_changed(self, shape: str) -> None:
        """Keep add-electrode size fields in sync with the chosen geometry."""
        self._add_electrode_size_shape = self._apply_add_shape_change(
            shape,
            DEFAULT_SHAPE,
            self._add_electrode_size_shape,
            self.add_electrode_size_edit,
            self.add_electrode_size_label,
            self.add_electrode_height_label,
            self.add_electrode_height_edit,
            self._add_electrode_actions_form,
        )

    def _on_add_pad_shape_changed(self, shape: str) -> None:
        """Keep add-pad size fields in sync with the chosen geometry."""
        self._add_pad_size_shape = self._apply_add_shape_change(
            shape,
            DEFAULT_PAD_SHAPE,
            self._add_pad_size_shape,
            self.add_pad_size_edit,
            self.add_pad_size_label,
            self.add_pad_height_label,
            self.add_pad_height_edit,
            self._add_pad_actions_form,
        )

    def _on_add_marker_shape_changed(self, shape: str) -> None:
        """Keep add-marker size fields in sync with the chosen geometry."""
        self._add_marker_size_shape = self._apply_add_shape_change(
            shape,
            DEFAULT_MARKER_SHAPE,
            self._add_marker_size_shape,
            self.add_marker_size_edit,
            self.add_marker_size_label,
            self.add_marker_height_label,
            self.add_marker_height_edit,
            self._add_marker_actions_form,
        )

    @staticmethod
    def _geometry_from_add_fields(
        shape_combo: QComboBox,
        size_edit: QLineEdit,
        height_edit: QLineEdit,
        default_shape: str,
        default_radius: float,
    ) -> tuple[str, float, float]:
        """Parse (shape, stored radius, stored height) from add-mode widgets."""
        shape = normalize_contact_shape(shape_combo.currentText(), default_shape)
        radius = default_radius
        size_text = size_edit.text().strip()
        if size_text:
            try:
                parsed = float(size_text)
                if parsed > 0:
                    radius = stored_half_from_size_field(shape, parsed)
            except ValueError:
                pass
        height = 0.0
        if shape_uses_height(shape):
            height_text = height_edit.text().strip()
            if height_text:
                try:
                    parsed_h = float(height_text)
                    if parsed_h > 0:
                        height = stored_half_from_size_field("rect", parsed_h)
                except ValueError:
                    pass
            if height <= 0:
                height = radius
        return shape, radius, height

    def _label_from_add_fields(
        self, position_combo: QComboBox, orientation_combo: QComboBox
    ) -> tuple[str, int]:
        """Parse label side and rotation from add-mode widgets."""
        position = self._label_position_from_combo(position_combo) or DEFAULT_LABEL_POSITION
        orientation = self._label_orientation_from_combo(orientation_combo)
        if orientation is None:
            orientation = DEFAULT_LABEL_ORIENTATION
        return position, orientation

    @staticmethod
    def _make_label_position_combo() -> QComboBox:
        """Combo for the editor-only map-label side (native JSON, not exported)."""
        combo = QComboBox()
        for value in LABEL_POSITIONS:
            combo.addItem(LABEL_POSITION_CAPTIONS[value], value)
        combo.setToolTip(
            "Where map text is drawn relative to this item. "
            "Saved in native JSON only; omitted from SpikeInterface and XLSX exports."
        )
        return combo

    @staticmethod
    def _set_label_position_combo(combo: QComboBox, value: str, mixed: bool) -> None:
        """Show a real side, or a mixed placeholder that Confirm will leave unchanged."""
        combo.blockSignals(True)
        if combo.findText(MIXED_SHAPE_LABEL) >= 0:
            combo.removeItem(combo.findText(MIXED_SHAPE_LABEL))
        if mixed:
            combo.insertItem(0, MIXED_SHAPE_LABEL)
            combo.setCurrentIndex(0)
        else:
            idx = combo.findData(normalize_label_position(value))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    @staticmethod
    def _label_position_from_combo(combo: QComboBox) -> str | None:
        """Return the chosen side, or None when the selection is mixed / empty."""
        if combo.currentText() == MIXED_SHAPE_LABEL:
            return None
        data = combo.currentData()
        if data is None:
            return None
        return normalize_label_position(data)

    @staticmethod
    def _make_label_orientation_combo() -> QComboBox:
        """Combo for the editor-only map-label rotation (native JSON, not exported)."""
        combo = QComboBox()
        for value in LABEL_ORIENTATIONS:
            combo.addItem(LABEL_ORIENTATION_CAPTIONS[value], value)
        combo.setToolTip(
            "Clockwise rotation of the outside map text. "
            "Saved in native JSON only; omitted from SpikeInterface and XLSX exports."
        )
        return combo

    @staticmethod
    def _set_label_orientation_combo(combo: QComboBox, value: int, mixed: bool) -> None:
        """Show a real rotation, or a mixed placeholder that Confirm will leave unchanged."""
        combo.blockSignals(True)
        if combo.findText(MIXED_SHAPE_LABEL) >= 0:
            combo.removeItem(combo.findText(MIXED_SHAPE_LABEL))
        if mixed:
            combo.insertItem(0, MIXED_SHAPE_LABEL)
            combo.setCurrentIndex(0)
        else:
            idx = combo.findData(normalize_label_orientation(value))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    @staticmethod
    def _label_orientation_from_combo(combo: QComboBox) -> int | None:
        """Return the chosen rotation, or None when the selection is mixed / empty."""
        if combo.currentText() == MIXED_SHAPE_LABEL:
            return None
        data = combo.currentData()
        if data is None:
            return None
        return normalize_label_orientation(data)

    @staticmethod
    def _set_shape_combo(combo: QComboBox, shapes: tuple[str, ...], value: str, mixed: bool) -> None:
        """Show a real shape, or a mixed placeholder that Confirm will leave unchanged."""
        combo.blockSignals(True)
        if combo.findText(MIXED_SHAPE_LABEL) >= 0:
            combo.removeItem(combo.findText(MIXED_SHAPE_LABEL))
        if mixed:
            combo.insertItem(0, MIXED_SHAPE_LABEL)
            combo.setCurrentIndex(0)
        else:
            if value in shapes:
                combo.setCurrentText(value)
            else:
                combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _new_pad_electrode_eid(self) -> int | None:
        """Electrode chosen in the Add Pad list, if it still exists."""
        eid = self.pad_add_electrode_combo.currentData()
        if eid is None or eid not in self.electrodes:
            return None
        return int(eid)

    def _is_adding(self) -> bool:
        """True while one-click electrode, pad, or orientation-marker creation is active."""
        return self.is_add_mode or self.is_add_pad_mode or self.is_add_marker_mode

    def _active_add_button(self) -> QPushButton | None:
        """The Stop Adding button for the current add mode, if any."""
        if self.is_add_pad_mode:
            return self.b_add_pad
        if self.is_add_mode:
            return self.b_add_electrode
        if self.is_add_marker_mode:
            return self.b_add_marker
        return None

    def _stop_all_add_modes(self) -> None:
        """Leave electrode, pad, and orientation-marker add modes."""
        if self.b_add_electrode.isChecked():
            self.b_add_electrode.setChecked(False)
        if self.b_add_pad.isChecked():
            self.b_add_pad.setChecked(False)
        if self.b_add_marker.isChecked():
            self.b_add_marker.setChecked(False)

    def _set_scene_items_selectable(self, selectable: bool) -> None:
        """Allow or block click/rubber-band selection on scene contacts."""
        for item in (*self.items.values(), *self.pad_items.values(), *self.marker_items.values()):
            item.setFlag(QGraphicsItem.ItemIsSelectable, selectable)

    def _set_inspector_locked(self, locked: bool) -> None:
        """
        Disable the inspector, menus, and electrode table while placing a new item.

        Mapping views stay usable. The active Stop Adding button stays clickable.
        """
        enabled = not locked
        for widget in (
            self._array_group,
            self._map_labels_group,
            self._selection_group,
            self._electrode_find_box,
            self._electrode_geom_box,
            self._electrode_attributes_box,
            self.b_apply_edits,
            self._pad_find_box,
            self._pad_edit_box,
            self.b_apply_pad_edits,
            self._marker_find_box,
            self._marker_edit_box,
            self.b_apply_marker_edits,
        ):
            widget.setEnabled(enabled)
        self.point_tabs.tabBar().setEnabled(enabled)
        keep = self._active_add_button() if locked else None
        for group in (
            self._electrode_actions_box,
            self._pad_actions_box,
            self._marker_actions_box,
        ):
            for child in group.findChildren(QWidget):
                stay_on = keep is not None and (child is keep or keep.isAncestorOf(child))
                child.setEnabled(enabled or stay_on)
        self.menuBar().setEnabled(enabled)
        if self._electrode_table_window is not None:
            self._electrode_table_window.setEnabled(enabled)

    def _update_add_pad_target_highlight(self) -> None:
        """Highlight the electrode that the next pad will be linked to."""
        target = self._new_pad_electrode_eid() if self.is_add_pad_mode else None
        for eid, item in self.items.items():
            item.set_add_target(eid == target)
        if target is None or target not in self.items:
            return
        item = self.items[target]
        pad = 40.0
        self.electrode_view.ensureVisible(
            item.sceneBoundingRect().adjusted(-pad, -pad, pad, pad), 80, 80
        )

    def _sync_add_mode_ui(self) -> None:
        """Cursors, inspector lock, selection block, and pad-target highlight."""
        adding = self._is_adding()
        self._sync_add_cursors()
        self._set_inspector_locked(adding)
        self._set_scene_items_selectable(not adding)
        drag = QGraphicsView.NoDrag if adding else QGraphicsView.RubberBandDrag
        for view in (self.electrode_view, self.pads_map_view):
            view.setDragMode(drag)
        if adding:
            self._is_mutating_scene = True
            try:
                self.scene.clearSelection()
                self._auto_selected_electrode_eids.clear()
                self._auto_selected_pad_ids.clear()
            finally:
                self._is_mutating_scene = False
        self._update_add_pad_target_highlight()
        if not adding:
            self._sync_associated_selection()
            self._refresh_panel_values()

    def _set_add_mode(self, enabled: bool) -> None:
        """Toggle one-click electrode creation mode."""
        self.is_add_mode = enabled
        if enabled:
            if self.b_add_pad.isChecked():
                self.b_add_pad.setChecked(False)
            if self.b_add_marker.isChecked():
                self.b_add_marker.setChecked(False)
            self.b_add_electrode.setText("Stop Adding")
        else:
            self.b_add_electrode.setText("Add Electrode")
        self._sync_add_mode_ui()

    def _set_add_pad_mode(self, enabled: bool) -> None:
        """Toggle one-click pad creation mode (electrode chosen from the list)."""
        if enabled:
            if not self.electrodes:
                QMessageBox.information(
                    self,
                    "Add Pad",
                    "No electrodes in the array. Create an electrode first.",
                )
                self.b_add_pad.blockSignals(True)
                self.b_add_pad.setChecked(False)
                self.b_add_pad.blockSignals(False)
                self.is_add_pad_mode = False
                return
            self._refresh_pad_add_electrode_combo()
            if self._new_pad_electrode_eid() is None:
                QMessageBox.information(
                    self,
                    "Add Pad",
                    "Every electrode already has a pad. Each electrode can be linked to only one pad.",
                )
                self.b_add_pad.blockSignals(True)
                self.b_add_pad.setChecked(False)
                self.b_add_pad.blockSignals(False)
                self.is_add_pad_mode = False
                return
            self.is_add_pad_mode = True
            if self.b_add_electrode.isChecked():
                self.b_add_electrode.setChecked(False)
            if self.b_add_marker.isChecked():
                self.b_add_marker.setChecked(False)
            self.b_add_pad.setText("Stop Adding")
        else:
            self.is_add_pad_mode = False
            self.b_add_pad.setText("Add Pad")
        self._sync_add_mode_ui()

    def _set_add_marker_mode(self, enabled: bool) -> None:
        """Toggle one-click orientation-marker creation mode."""
        if enabled:
            self.is_add_marker_mode = True
            if self.b_add_electrode.isChecked():
                self.b_add_electrode.setChecked(False)
            if self.b_add_pad.isChecked():
                self.b_add_pad.setChecked(False)
            self.b_add_marker.setText("Stop Adding")
        else:
            self.is_add_marker_mode = False
            self.b_add_marker.setText("Add Orientation Marker")
        self._sync_add_mode_ui()

    def _sync_add_cursors(self) -> None:
        """Show a crosshair on both mapping views while add-mode is active."""
        adding = self.is_add_mode or self.is_add_pad_mode or self.is_add_marker_mode
        for view in (self.electrode_view, self.pads_map_view):
            if adding:
                view.viewport().setCursor(Qt.CrossCursor)
            else:
                view.viewport().unsetCursor()

    def _add_point_at(self, x: float, y: float) -> None:
        """Dispatch scene click to electrode, pad, or orientation-marker creation."""
        if self.is_add_pad_mode:
            self._add_pad_at(x, y)
        elif self.is_add_marker_mode:
            self._add_marker_at(x, y)
        else:
            self._add_electrode_at(x, y)

    def _add_electrode_at(self, x: float, y: float) -> None:
        """Create a new electrode at (x, y) and select it. No pad is created."""
        before = self._capture_state()
        next_eid = max(self.electrodes.keys(), default=-1) + 1
        shape, radius, height = self._geometry_from_add_fields(
            self.add_electrode_shape_combo,
            self.add_electrode_size_edit,
            self.add_electrode_height_edit,
            DEFAULT_SHAPE,
            DEFAULT_RADIUS,
        )
        label_position, label_orientation = self._label_from_add_fields(
            self.add_electrode_label_position_combo,
            self.add_electrode_label_orientation_combo,
        )
        model = Electrode(
            eid=next_eid,
            x=x,
            y=y,
            radius=radius,
            height=height,
            shape=shape,
            potentiostat_id=self._next_unique_potentiostat_id(),
            intan_id=self._next_unique_intan_id(),
            label_position=label_position,
            label_orientation=label_orientation,
        )
        fill_electrode_extras(model, self.attribute_schema)
        self._is_mutating_scene = True
        try:
            item = self._add_electrode_item(model)
        finally:
            self._is_mutating_scene = False
        self._update_duplicate_flags()
        self._refresh_pad_electrode_combo()
        self._refresh_pad_add_electrode_combo()
        self.scene.clearSelection()
        item.setSelected(True)
        self._on_scene_visuals_changed()
        self._commit_if_changed(before)

    def _add_pad_at(self, x: float, y: float) -> None:
        """Create a new pad at (x, y) linked to a free electrode chosen in the list."""
        target_eid = self._new_pad_electrode_eid()
        if target_eid is None:
            QMessageBox.information(
                self,
                "Add Pad",
                "Every electrode already has a pad. Each electrode can be linked to only one pad.",
            )
            self.b_add_pad.setChecked(False)
            return
        if target_eid in self._taken_electrode_eids():
            QMessageBox.information(
                self,
                "Add Pad",
                "That electrode already has a pad. Choose an electrode without a pad.",
            )
            self._refresh_pad_add_electrode_combo()
            if self._new_pad_electrode_eid() is None:
                self.b_add_pad.setChecked(False)
            return
        before = self._capture_state()
        next_pad_id = max(self.pads.keys(), default=-1) + 1
        shape, radius, height = self._geometry_from_add_fields(
            self.add_pad_shape_combo,
            self.add_pad_size_edit,
            self.add_pad_height_edit,
            DEFAULT_PAD_SHAPE,
            DEFAULT_PAD_RADIUS,
        )
        label_position, label_orientation = self._label_from_add_fields(
            self.add_pad_label_position_combo,
            self.add_pad_label_orientation_combo,
        )
        pad = Pad(
            pad_id=next_pad_id,
            electrode_eid=target_eid,
            x=x,
            y=y,
            radius=radius,
            height=height,
            shape=shape,
            label_position=label_position,
            label_orientation=label_orientation,
        )
        self._is_mutating_scene = True
        try:
            item = self._add_pad_item(pad)
        finally:
            self._is_mutating_scene = False
        self._update_duplicate_flags()
        self._refresh_pad_electrode_combo()
        self._refresh_pad_add_electrode_combo()
        last_free = self._new_pad_electrode_eid() is None
        if last_free and self.is_add_pad_mode:
            self.b_add_pad.setChecked(False)
        self.scene.clearSelection()
        if last_free:
            item.setSelected(True)
        else:
            self._update_add_pad_target_highlight()
        self._on_scene_visuals_changed()
        self._commit_if_changed(before)

    def _add_marker_at(self, x: float, y: float) -> None:
        """Create a new orientation marker at (x, y) and select it."""
        before = self._capture_state()
        next_id = max(self.orientation_markers.keys(), default=-1) + 1
        shape, radius, height = self._geometry_from_add_fields(
            self.add_marker_shape_combo,
            self.add_marker_size_edit,
            self.add_marker_height_edit,
            DEFAULT_MARKER_SHAPE,
            DEFAULT_MARKER_RADIUS,
        )
        marker = OrientationMarker(
            marker_id=next_id,
            x=x,
            y=y,
            radius=radius,
            height=height,
            shape=shape,
        )
        self._is_mutating_scene = True
        try:
            item = self._add_marker_item(marker)
        finally:
            self._is_mutating_scene = False
        self.scene.clearSelection()
        item.setSelected(True)
        self.point_tabs.blockSignals(True)
        self.point_tabs.setCurrentIndex(TAB_MARKERS)
        self.point_tabs.blockSignals(False)
        self._on_scene_visuals_changed()
        self._commit_if_changed(before)

    def _apply_si_units(self) -> None:
        """Apply distance unit (si_units) at array level."""
        units = self.si_units_edit.text().strip()
        if not units:
            QMessageBox.information(self, "No values", "Fill si_units before applying.")
            self.si_units_edit.setText(self.si_units)
            return
        if units == self.si_units:
            return
        before = self._capture_state()
        self.si_units = units
        self.si_units_edit.setText(self.si_units)
        self._commit_if_changed(before)

    def _update_title(self) -> None:
        """Update window title with version, file path, and asterisk if modified."""
        dirty_suffix = " *" if self.is_dirty else ""
        versioned_name = f"{APP_NAME} v{__version__}"
        if self.current_file_path:
            self.setWindowTitle(f"{versioned_name} - {self.current_file_path}{dirty_suffix}")
        else:
            self.setWindowTitle(f"{versioned_name}{dirty_suffix}")

    def _startup_workflow(self) -> None:
        """On startup, show dialog: open or create array."""
        self._start_dependency_preload()
        msg = QMessageBox(self)
        msg.setWindowTitle(APP_NAME)
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
        """Open new-matrix dialog and generate grid if accepted."""
        self._start_dependency_preload()
        dialog = NewArrayDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return False
        params = dialog.values()
        n_contacts = params.rows * params.cols
        if n_contacts > NEW_ARRAY_WARN_COUNT:
            confirm = QMessageBox.question(
                self,
                "Large array",
                f"This will create {n_contacts} electrodes and {n_contacts} pads. "
                "The editor may become slow. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return False
        self.si_units = params.si_units
        self._generate_aligned_grid(params)
        self.current_file_path = None
        self._refresh_dirty_flag()
        self._fit_all_views()
        self.raise_()
        self.activateWindow()
        return True

    def _prompt_open_array_file(self) -> bool:
        """Prompt for JSON path via dialog and load array."""
        self._start_dependency_preload()
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
        self._mark_clean()
        self._fit_all_views()
        self.raise_()
        self.activateWindow()
        return True

    def _start_dependency_preload(self) -> None:
        """Preload optional heavy dependencies in background (XLSX export)."""
        if self._preload_started:
            return
        self._preload_started = True

        def _preload() -> None:
            for module_name in ("openpyxl",):
                try:
                    importlib.import_module(module_name)
                except Exception:
                    pass

        self._preload_thread = threading.Thread(target=_preload, daemon=True, name="dependency-preload")
        self._preload_thread.start()

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

    def _menu_export_spikeinterface(self) -> None:
        """Menu handler for SpikeInterface / probeinterface JSON export."""
        if not self.electrodes:
            QMessageBox.information(self, "Export SpikeInterface", "No array to export.")
            return
        if not self._confirm_pairing_before_export():
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export SpikeInterface JSON",
            "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            export_spikeinterface_json(
                path,
                list(self.electrodes.values()),
                self.si_units,
                pads=list(self.pads.values()),
                electrode_attributes=self.attribute_schema,
                map_labels=self.visible_map_label_keys,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export SpikeInterface", f"Could not export JSON:\n{exc}")
            return
        QMessageBox.information(
            self,
            "Export SpikeInterface",
            "Probeinterface JSON exported for SpikeInterface.\n"
            "Channel ID comes from INTAN ID; Contact ID comes from Manufacturer ID "
            "(or INTAN ID if Manufacturer ID is unused).\n"
            "Native IDs, extra attributes, and the linked pad (id + geometry) "
            "are stored in contact_annotations.\n"
            "The attribute schema and map labels are kept in probe annotations.",
        )

    def _menu_export_matrix_xlsx(self) -> None:
        """Menu handler for array export as XLSX."""
        if not self.electrodes:
            QMessageBox.information(self, "Export XLSX", "No array to export.")
            return
        if not self._confirm_pairing_before_export():
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
        QMessageBox.information(
            self,
            "Export XLSX",
            "Workbook exported successfully (electrodes, pads, orientation markers, and attribute schema).",
        )

    def _confirm_pairing(self, title: str, question: str) -> bool:
        """Warn when the 1:1 electrode/pad pairing is incomplete."""
        problems = pairing_problems(self.electrodes.values(), self.pads.values())
        if not problems:
            return True
        confirm = QMessageBox.question(
            self,
            title,
            "The array has pairing issues:\n- "
            + "\n- ".join(problems)
            + f"\n\n{question}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return confirm == QMessageBox.Yes

    def _confirm_pairing_before_save(self) -> bool:
        """Warn when the 1:1 electrode/pad pairing is incomplete."""
        return self._confirm_pairing("Pairing issues", "Save anyway?")

    def _confirm_pairing_before_export(self) -> bool:
        """Warn when exporting an array that is not 1:1 paired."""
        return self._confirm_pairing("Pairing issues", "Export anyway?")

    def _save_current_array(self, show_success: bool = False) -> bool:
        """Save to current path. If no path, open Save As dialog."""
        if not self.electrodes:
            QMessageBox.information(self, "Save array", "No array to save.")
            return False
        if not self.current_file_path:
            return self._save_current_array_as(show_success=show_success)
        if is_probeinterface_file(self.current_file_path):
            QMessageBox.information(
                self,
                "Save array",
                "The opened file is a probeinterface JSON.\n"
                "Native save uses the mea_editor format. Choose a new path.\n"
                "Use File > Export for SpikeInterface... to write a probeinterface JSON.",
            )
            return self._save_current_array_as(show_success=show_success)
        if not self._confirm_pairing_before_save():
            return False
        try:
            self._save_array_to_file(self.current_file_path)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", f"Could not save file:\n{exc}")
            return False
        self._mark_clean()
        if show_success:
            QMessageBox.information(self, "Save array", "Array saved successfully.")
        return True

    def _save_current_array_as(self, show_success: bool = False) -> bool:
        """Save with explicit file selection dialog."""
        if not self.electrodes:
            QMessageBox.information(self, "Save array", "No array to save.")
            return False
        if not self._confirm_pairing_before_save():
            return False
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save array JSON",
            self.current_file_path or "",
            "JSON files (*.json);;All files (*.*)",
        )
        if not path:
            return False
        if not path.lower().endswith(".json"):
            path += ".json"
        if is_probeinterface_file(path):
            confirm = QMessageBox.question(
                self,
                "Replace probeinterface file",
                "This file is a probeinterface JSON. Saving will replace it with the native mea_editor format.\n"
                "Use File > Export for SpikeInterface... if you want a probeinterface JSON.\nContinue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return False
        try:
            self._save_array_to_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Save error", f"Could not save file:\n{exc}")
            return False
        self.current_file_path = path
        self._mark_clean()
        if show_success:
            QMessageBox.information(self, "Save array", "Array saved successfully.")
        return True

    def _confirm_before_replace(self, action_label: str) -> bool:
        """Prompt save/discard/cancel before replacing content."""
        if self.is_dirty:
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
        """Persist current models in native mea_editor JSON format."""
        save_array_to_file(
            path,
            list(self.electrodes.values()),
            self.si_units,
            pads=list(self.pads.values()),
            electrode_attributes=self.attribute_schema,
            map_labels=self.visible_map_label_keys,
            orientation_markers=list(self.orientation_markers.values()),
        )

    def _load_array_from_file(self, path: str) -> None:
        """Load models from file and update si_units in memory."""
        document = load_array_document(path)
        self.si_units = document.si_units
        self.visible_map_label_keys = set(document.map_labels)
        self._set_attribute_schema(document.electrode_attributes, prune=False)
        self._set_array(document.electrodes, document.pads, document.orientation_markers)

    def _export_matrix_to_xlsx(self, path: str) -> None:
        """Export electrodes, pads, orientation markers, and the attribute schema into an XLSX workbook."""
        export_array_xlsx(
            path,
            list(self.electrodes.values()),
            pads=list(self.pads.values()),
            electrode_attributes=self.attribute_schema,
            si_units=self.si_units,
            orientation_markers=list(self.orientation_markers.values()),
        )

    def _update_duplicate_flags(self) -> None:
        """Recompute identifier and pairing flags, then refresh colors."""
        refresh_status_flags(self.electrodes.values(), self.pads.values(), self.attribute_schema)
        self._invalidate_geometry_caches()
        self._pad_combo_sig = None
        self._pad_add_combo_sig = None
        for item in self.items.values():
            item._refresh_style()
        for item in self.pad_items.values():
            item._refresh_style()
            item._refresh_label()

    def _states_equal(self, a: EditorState, b: EditorState) -> bool:
        """Compare two snapshots with tolerance on floats."""
        if a.attribute_schema != b.attribute_schema:
            return False
        if a.map_labels != b.map_labels:
            return False
        if a.si_units != b.si_units or a.current_file_path != b.current_file_path:
            return False
        if a.electrodes.keys() != b.electrodes.keys() or a.pads.keys() != b.pads.keys():
            return False
        if a.orientation_markers.keys() != b.orientation_markers.keys():
            return False
        tol = 1e-9
        for eid in a.electrodes:
            left = a.electrodes[eid]
            right = b.electrodes[eid]
            if (
                left.potentiostat_id != right.potentiostat_id
                or left.intan_id != right.intan_id
                or left.manufacturer_id != right.manufacturer_id
                or left.shank_id != right.shank_id
                or left.shape != right.shape
                or left.label_position != right.label_position
                or left.label_orientation != right.label_orientation
                or left.extra != right.extra
            ):
                return False
            if any(abs(av - bv) > tol for av, bv in zip(left.contact_plane_axis, right.contact_plane_axis)):
                return False
            if abs(left.x - right.x) > tol or abs(left.y - right.y) > tol or abs(left.radius - right.radius) > tol:
                return False
            if abs(left.height - right.height) > tol:
                return False
        for pad_id in a.pads:
            left = a.pads[pad_id]
            right = b.pads[pad_id]
            if left.electrode_eid != right.electrode_eid or left.shape != right.shape:
                return False
            if left.label_position != right.label_position:
                return False
            if left.label_orientation != right.label_orientation:
                return False
            if abs(left.x - right.x) > tol or abs(left.y - right.y) > tol or abs(left.radius - right.radius) > tol:
                return False
            if abs(left.height - right.height) > tol:
                return False
        for marker_id in a.orientation_markers:
            left = a.orientation_markers[marker_id]
            right = b.orientation_markers[marker_id]
            if left.shape != right.shape:
                return False
            if abs(left.x - right.x) > tol or abs(left.y - right.y) > tol:
                return False
            if abs(left.radius - right.radius) > tol:
                return False
            if abs(left.height - right.height) > tol:
                return False
            if left.label_position != right.label_position:
                return False
            if left.label_orientation != right.label_orientation:
                return False
        return True

    def _restore_state(self, state: EditorState) -> None:
        """Restore snapshot into scene (undo/redo)."""
        self._is_restoring_state = True
        try:
            self.si_units = state.si_units
            self.current_file_path = state.current_file_path
            self.visible_map_label_keys = set(state.map_labels)
            self._set_attribute_schema(list(state.attribute_schema), prune=True)
            models = [
                Electrode.from_snapshot(eid, snap)
                for eid, snap in sorted(state.electrodes.items(), key=lambda kv: kv[0])
            ]
            pads = [
                Pad.from_snapshot(pad_id, snap)
                for pad_id, snap in sorted(state.pads.items(), key=lambda kv: kv[0])
            ]
            markers = [
                OrientationMarker.from_snapshot(marker_id, snap)
                for marker_id, snap in sorted(state.orientation_markers.items(), key=lambda kv: kv[0])
            ]
            self._set_array(models, pads, markers)
        finally:
            self._is_restoring_state = False
        self._on_scene_visuals_changed()

    def _push_undo(self, before_state: EditorState) -> None:
        """Push state onto undo stack and clear redo stack."""
        self.undo_stack.append(before_state)
        if len(self.undo_stack) > self._max_history:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def _commit_if_changed(self, before_state: EditorState) -> None:
        """Record undo entry only when state actually changed."""
        after_state = self._capture_state()
        if not self._states_equal(before_state, after_state):
            self._push_undo(before_state)
            self._refresh_dirty_flag()

    def _on_scene_visuals_changed(self) -> None:
        """Refresh panel and overlays when geometry/selection changes."""
        if self._is_restoring_state or self._is_mutating_scene:
            return
        if self._visuals_refresh_pending:
            return
        self._visuals_refresh_pending = True
        QTimer.singleShot(0, self._flush_scene_visuals)

    def _flush_scene_visuals(self) -> None:
        """Apply one batched scene/panel refresh after geometry changes."""
        if not self._visuals_refresh_pending:
            return
        self._visuals_refresh_pending = False
        self._panel_refresh_pending = False
        if self._is_restoring_state or self._is_mutating_scene:
            return
        self._invalidate_geometry_caches()
        self._refresh_panel_values()
        self._ensure_scene_rect()
        self._sync_electrode_table(reload_data=True)
        self.electrode_view.viewport().update()
        self.pads_map_view.viewport().update()

    def _schedule_panel_refresh(self) -> None:
        """Rebuild the inspector once after a burst of selection changes."""
        if (
            self._is_restoring_state
            or self._is_mutating_scene
            or self._is_adding()
            or self._defer_rubber_band_selection
        ):
            return
        if self._panel_refresh_pending:
            return
        self._panel_refresh_pending = True
        QTimer.singleShot(0, self._flush_panel_refresh)

    def _flush_panel_refresh(self) -> None:
        if not self._panel_refresh_pending:
            return
        self._panel_refresh_pending = False
        if self._is_restoring_state or self._is_mutating_scene or self._is_adding():
            return
        self._refresh_panel_values()

    def _undo_line_edit_if_focused(self) -> bool:
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            focus.undo()
            return True
        return False

    def _redo_line_edit_if_focused(self) -> bool:
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            focus.redo()
            return True
        return False

    def _undo(self) -> None:
        """Undo: restore previous state and put current into redo."""
        if self._undo_line_edit_if_focused():
            return
        if not self.undo_stack:
            return
        current = self._capture_state()
        previous = self.undo_stack.pop()
        self.redo_stack.append(current)
        self._restore_state(previous)
        self._refresh_dirty_flag()

    def _redo(self) -> None:
        """Redo: restore next state and put current back into undo."""
        if self._redo_line_edit_if_focused():
            return
        if not self.redo_stack:
            return
        current = self._capture_state()
        nxt = self.redo_stack.pop()
        self.undo_stack.append(current)
        self._restore_state(nxt)
        self._refresh_dirty_flag()

    def _generate_aligned_grid(self, params: NewArrayParams) -> None:
        """Create an electrode grid and a matching pad rectangle around it."""
        self.visible_map_label_keys = set(DEFAULT_MAP_LABEL_KEYS)
        self._set_attribute_schema(default_schema(), prune=True)
        models: list[Electrode] = []
        eid = 0
        for r in range(params.rows):
            for c in range(params.cols):
                model = Electrode(
                    eid=eid,
                    x=c * params.pitch,
                    y=r * params.pitch,
                    potentiostat_id=eid,
                    intan_id=format_intan_id(eid),
                    shape=params.electrode_shape,
                )
                fill_electrode_extras(model, self.attribute_schema)
                models.append(model)
                eid += 1
        pads = layout_pads_around_electrodes(
            models,
            pad_rows=params.pad_rows,
            pad_spacing=params.pad_spacing,
            pad_size=params.pad_size,
            pad_shape=params.pad_shape,
            pad_height=params.pad_height,
        )
        self._set_array(models, pads)

    def _create_new_array_interactive(self) -> None:
        """Handler for File > New: confirm replacement, open dialog, create grid."""
        if not self._confirm_before_replace("create a new array"):
            return
        before = self._capture_state()
        if self._prompt_new_array_parameters():
            self._commit_if_changed(before)

    def _refresh_label_layouts(self, view=None) -> None:
        """Redraw overlay labels after zoom, pan, or a fit-view."""
        if view is not None:
            view.viewport().update()
            return
        self.electrode_view.viewport().update()
        self.pads_map_view.viewport().update()

    def _fit_target_rect(self, index: int) -> QRectF:
        """Bounds used to frame a mapping view (electrodes left, pads right)."""
        if index == TAB_PADS:
            if self.pads:
                base = self._pad_bounds_rect()
            elif self.electrodes:
                base = self._electrode_bounds_rect()
            else:
                base = self._array_bounds_rect()
        elif self.electrodes:
            base = self._electrode_bounds_rect()
        else:
            base = self._array_bounds_rect()
        if self.orientation_markers:
            base = base.united(self._marker_bounds_rect())
        return base

    def _map_views(self) -> tuple[ElectrodeArrayView, ElectrodeArrayView]:
        """Left (electrodes) and right (pads) mapping cameras."""
        return self.electrode_view, self.pads_map_view

    def _capture_map_cameras(self) -> list[tuple[ElectrodeArrayView, QPointF]]:
        """Remember each mapping view's scene point at the viewport center."""
        return [(view, view.capture_camera()) for view in self._map_views()]

    def _restore_map_cameras(self, cameras: list[tuple[ElectrodeArrayView, QPointF]]) -> None:
        """Put each mapping view back on the scene point it showed before."""
        for view, scene_center in cameras:
            view.restore_camera(scene_center)

    def _ensure_scene_rect(self, extra: QRectF | None = None) -> None:
        """Keep enough scene margin so the pad view can pan to true center.

        Recalculating the scene rect recenters Qt's AlignCenter cameras, so
        the current view is restored afterwards. Visible regions are kept in
        the rect so restoring is not clamped after a shrink.
        """
        needed = self._array_bounds_rect(margin=DEFAULT_SCENE_MARGIN)
        if extra is not None:
            needed = needed.united(extra)
        current = self.scene.sceneRect()
        if current.isValid() and not current.isEmpty() and current.contains(needed):
            return
        array_rect = self._array_bounds_rect(margin=0.0)
        span = max(array_rect.width(), array_rect.height(), 1.0)
        margin = max(DEFAULT_SCENE_MARGIN, FIT_PADDING_MIN * 2.0, span * SCENE_FIT_GROW)
        rect = self._array_bounds_rect(margin=margin)
        if extra is not None:
            rect = rect.united(extra)
        cameras = self._capture_map_cameras()
        for view in self._map_views():
            visible = view.visible_scene_rect()
            if visible.isValid() and not visible.isEmpty():
                rect = rect.united(visible)
        self.scene.setSceneRect(rect)
        self._restore_map_cameras(cameras)

    def _united_item_rect(self, items, margin: float = 40.0) -> QRectF | None:
        """Scene bounds of graphics items, expanded by `margin` scene units."""
        if not items:
            return None
        united = items[0].sceneBoundingRect()
        for item in items[1:]:
            united = united.united(item.sceneBoundingRect())
        return united.adjusted(-margin, -margin, margin, margin)

    def _reveal_confirmed_items(self, items, *views: ElectrodeArrayView) -> None:
        """Scroll mapping views to the confirmed items and redraw overlays now."""
        self._invalidate_geometry_caches()
        rect = self._united_item_rect(items)
        self._ensure_scene_rect(extra=rect)
        if rect is not None:
            for view in views:
                view.ensureVisible(rect, 80, 80)
        self._refresh_label_layouts()

    def _fit_graphics_view(self, view: ElectrodeArrayView, base_rect: QRectF) -> None:
        """Fit one mapping viewport to a scene rect, centered in the plot area."""
        fit_padding = max(FIT_PADDING_MIN, FIT_PADDING_RATIO * max(base_rect.width(), base_rect.height()))
        fit_rect = base_rect.adjusted(-fit_padding, -fit_padding, fit_padding, fit_padding)
        grow = max(fit_rect.width(), fit_rect.height()) * SCENE_FIT_GROW
        self._ensure_scene_rect(extra=fit_rect.adjusted(-grow, -grow, grow, grow))
        view.fit_scene_rect(fit_rect)

    def _fit_view(self) -> None:
        """Fit both mapping views: electrodes on the left, pads on the right."""
        self._fit_all_views()

    def _fit_all_views(self) -> None:
        """Fit each mapping viewport to its target now that both are visible."""
        if not self.electrodes and not self.pads and not self.orientation_markers:
            return
        self._fit_graphics_view(self.electrode_view, self._fit_target_rect(TAB_ELECTRODES))
        self._fit_graphics_view(self.pads_map_view, self._fit_target_rect(TAB_PADS))
        self._refresh_label_layouts()

    def _parse_contact_plane_axis_text(self, text: str) -> tuple[float, float, float, float] | None:
        """Parse axis text: "x0,x1,y0,y1" or space-separated values."""
        parts = [p for p in text.replace(",", " ").split() if p]
        if len(parts) != 4:
            return None
        try:
            x0, x1, y0, y1 = (float(p) for p in parts)
        except ValueError:
            return None
        return x0, x1, y0, y1

    def _labels_for_electrode(self, model: Electrode) -> tuple[str, str]:
        """Build map-view label text from the IDs currently checked."""
        return model.map_view_labels(
            self.visible_map_label_keys,
            [spec.key for spec in self.attribute_schema],
        )

    def _refresh_all_map_labels(self) -> None:
        """Redraw electrode and pad labels after a visibility change."""
        for item in self.items.values():
            item._refresh_label()
        for item in self.pad_items.values():
            item._refresh_label()
        self._refresh_label_layouts()

    def _rebuild_map_label_controls(self) -> None:
        """Rebuild checkbox and View-menu entries from the current schema."""
        valid_keys = {spec.key for spec in self.attribute_schema}
        self.visible_map_label_keys &= valid_keys
        self._rebuild_map_label_checks()
        self._rebuild_map_label_menu()

    def _rebuild_map_label_checks(self) -> None:
        """Rebuild the Map labels checkboxes (same IDs as the Electrodes tab)."""
        layout = self._map_labels_layout
        if layout is None:
            return
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()
        self._map_label_checks.clear()
        for spec in self.attribute_schema:
            check = QCheckBox(spec.label)
            check.setChecked(spec.key in self.visible_map_label_keys)
            check.setToolTip("Show this ID on the electrode and pad views.")
            check.toggled.connect(
                lambda checked, key=spec.key: self._set_map_label_visible(key, checked)
            )
            self._map_label_checks[spec.key] = check
            layout.addWidget(check)

    def _rebuild_map_label_menu(self) -> None:
        """Rebuild View > Map labels checkable actions."""
        menu = self._view_labels_menu
        if menu is None:
            return
        menu.clear()
        self._map_label_actions.clear()
        for spec in self.attribute_schema:
            action = QAction(spec.label, self)
            action.setCheckable(True)
            action.setChecked(spec.key in self.visible_map_label_keys)
            action.toggled.connect(
                lambda checked, key=spec.key: self._set_map_label_visible(key, checked)
            )
            menu.addAction(action)
            self._map_label_actions[spec.key] = action

    def _set_map_label_visible(self, key: str, visible: bool) -> None:
        """Check or uncheck one map-view ID and refresh both views."""
        already = key in self.visible_map_label_keys
        if already == bool(visible):
            return
        before = None if self._is_restoring_state else self._capture_state()
        if visible:
            self.visible_map_label_keys.add(key)
        else:
            self.visible_map_label_keys.discard(key)
        check = self._map_label_checks.get(key)
        if check is not None and check.isChecked() != visible:
            check.blockSignals(True)
            check.setChecked(visible)
            check.blockSignals(False)
        action = self._map_label_actions.get(key)
        if action is not None and action.isChecked() != visible:
            action.blockSignals(True)
            action.setChecked(visible)
            action.blockSignals(False)
        self._refresh_all_map_labels()
        if before is not None:
            self._commit_if_changed(before)

    def _rebuild_attribute_fields(self) -> None:
        """Rebuild identifier/extra attribute editors from the current file schema."""
        layout = self.attributes_form
        while layout.rowCount() > 0:
            layout.removeRow(0)
        self.attribute_edits.clear()
        for spec in self.attribute_schema:
            edit = QLineEdit("")
            self.attribute_edits[spec.key] = edit
            if spec.builtin:
                layout.addRow(spec.label, edit)
                continue
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(edit)
            remove_btn = QPushButton("×")
            remove_btn.setFixedWidth(28)
            remove_btn.setToolTip("Remove this attribute from the file")
            remove_btn.clicked.connect(lambda _checked=False, key=spec.key: self._remove_attribute(key))
            row_layout.addWidget(remove_btn)
            layout.addRow(spec.label, row)

    def _set_attribute_schema(self, schema: list[AttributeSpec], *, prune: bool) -> None:
        """Replace the file-level schema and rebuild the electrode attribute panel."""
        self.attribute_schema = list(schema)
        fill_electrodes_extras(self.electrodes.values(), self.attribute_schema, prune=prune)
        self._rebuild_attribute_fields()
        self._rebuild_map_label_controls()
        self._refresh_panel_values()
        self._sync_electrode_table(reload_data=True)
        self._refresh_all_map_labels()

    def _add_attribute_interactive(self) -> None:
        """Open the dialog to add a file-level extra electrode attribute."""
        dialog = AddAttributeDialog(self.attribute_schema, self)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.spec()
        if spec is None:
            QMessageBox.information(self, "Add attribute", "Enter a name for the new attribute.")
            return
        if any(existing.key == spec.key for existing in self.attribute_schema):
            QMessageBox.information(self, "Add attribute", f"Attribute « {spec.label} » already exists.")
            return
        before = self._capture_state()
        schema = list(self.attribute_schema) + [spec]
        self._set_attribute_schema(schema, prune=False)
        self._commit_if_changed(before)

    def _remove_attribute(self, key: str) -> None:
        """Remove a file-level extra attribute from the schema and all electrodes."""
        spec = next((item for item in self.attribute_schema if item.key == key), None)
        if spec is None or spec.builtin:
            return
        confirm = QMessageBox.question(
            self,
            "Remove attribute",
            f"Remove attribute « {spec.label} » from this file?\nValues on all electrodes will be deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        before = self._capture_state()
        schema = [item for item in self.attribute_schema if item.key != key]
        self._set_attribute_schema(schema, prune=True)
        self._commit_if_changed(before)

    @staticmethod
    def _common_coord_text(values: list[float]) -> str:
        """Format a shared coordinate, or empty when values differ."""
        if not values:
            return ""
        if max(values) - min(values) < 1e-9:
            return f"{values[0]:.2f}"
        return ""

    def _set_xy_edits_from_items(self, x_edit: QLineEdit, y_edit: QLineEdit, items) -> None:
        """Fill X/Y fields from one or many items; mixed axes stay empty."""
        x_edit.setText(self._common_coord_text([it.model.x for it in items]))
        y_edit.setText(self._common_coord_text([it.model.y for it in items]))

    def _parse_optional_xy(self, x_text: str, y_text: str) -> tuple[float | None, float | None] | None:
        """Parse X and/or Y. Empty means unchanged. None means invalid input."""
        x_value: float | None = None
        y_value: float | None = None
        if x_text:
            try:
                x_value = float(x_text)
            except ValueError:
                QMessageBox.critical(self, "Invalid X/Y", "X must be a numeric value.")
                return None
        if y_text:
            try:
                y_value = float(y_text)
            except ValueError:
                QMessageBox.critical(self, "Invalid X/Y", "Y must be a numeric value.")
                return None
        return x_value, y_value

    def _apply_xy_to_items(self, items, x_value: float | None, y_value: float | None) -> None:
        """Set X and/or Y on every item. None leaves that axis unchanged."""
        if x_value is None and y_value is None:
            return
        self._is_mutating_scene = True
        try:
            for item in items:
                pos = item.pos()
                item.setPos(
                    pos.x() if x_value is None else x_value,
                    pos.y() if y_value is None else y_value,
                )
        finally:
            self._is_mutating_scene = False

    def _apply_pending_edits(self) -> None:
        """
        Apply all non-empty edit-panel fields in one confirmation action.

        Empty text fields are treated as "no change". X and Y can be set
        independently: a filled axis is applied to every selected electrode.
        """
        selected = self._selected_electrode_items()
        if not selected:
            return
        radius_text = self.radius_edit.text().strip()
        height_text = self.height_edit.text().strip()
        x_text = self.x_edit.text().strip()
        y_text = self.y_edit.text().strip()
        plane_text = self.contact_plane_axis_edit.text().strip()
        shape_text = self.shape_combo.currentText()
        apply_shape = shape_text != MIXED_SHAPE_LABEL
        shape_value = (
            normalize_contact_shape(shape_text, DEFAULT_SHAPE) if apply_shape else None
        )

        parsed_attributes: dict[str, str | int | float] = {}
        single = len(selected) == 1
        for spec in self.attribute_schema:
            edit = self.attribute_edits.get(spec.key)
            if edit is None:
                continue
            raw = edit.text()
            if raw == "":
                # Single selection: empty string fields clear the value.
                # Multi-selection: empty still means "leave unchanged".
                if single and spec.value_type == "str":
                    parsed_attributes[spec.key] = ""
                continue
            try:
                parsed_attributes[spec.key] = parse_user_value(spec, raw)
            except ValueError:
                QMessageBox.critical(
                    self,
                    f"Invalid {spec.label}",
                    f"{spec.label} must be a valid {spec.value_type}.",
                )
                return

        parsed_xy = self._parse_optional_xy(x_text, y_text)
        if parsed_xy is None:
            return
        x_value, y_value = parsed_xy

        before = self._capture_state()

        radius_field: float | None = None
        if radius_text:
            try:
                radius_field = float(radius_text)
                if radius_field <= 0:
                    raise ValueError
            except ValueError:
                size_name = primary_size_field_label(shape_value or DEFAULT_SHAPE)
                QMessageBox.critical(
                    self,
                    f"Invalid {size_name.lower()}",
                    f"{size_name} must be a positive number.",
                )
                return

        height_field: float | None = None
        if height_text:
            try:
                height_field = float(height_text)
                if height_field <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.critical(self, "Invalid height", "Height must be a positive number.")
                return

        plane_value: tuple[float, float, float, float] | None = None
        if plane_text:
            plane_value = self._parse_contact_plane_axis_text(plane_text)
            if plane_value is None:
                QMessageBox.critical(self, "Invalid contact plane axis", "Use 4 values: x0, x1, y0, y1.")
                return

        label_position = self._label_position_from_combo(self.label_position_combo)
        label_orientation = self._label_orientation_from_combo(self.label_orientation_combo)

        for item in selected:
            item_shape = (
                shape_value
                if apply_shape
                else normalize_contact_shape(item.model.shape, DEFAULT_SHAPE)
            )
            if apply_shape:
                item.model.shape = item_shape
            if radius_field is not None:
                item.set_radius(stored_half_from_size_field(item_shape, radius_field))
            if plane_value is not None:
                item.model.contact_plane_axis = plane_value
            if label_position is not None:
                item.model.label_position = label_position
            if label_orientation is not None:
                item.model.label_orientation = label_orientation
            for key, value in parsed_attributes.items():
                item.model.set_attribute(key, value)
            if shape_uses_height(item_shape):
                if height_field is not None:
                    item.set_height(stored_half_from_size_field("rect", height_field))
                elif item.model.height <= 0:
                    item.set_height(item.model.radius)
            item.sync_from_model()

        self._apply_xy_to_items(selected, x_value, y_value)

        self._update_duplicate_flags()
        self._refresh_pad_electrode_combo()
        self._refresh_pad_add_electrode_combo()
        self._reveal_confirmed_items(selected, self.electrode_view)
        self._refresh_panel_values()
        self._sync_electrode_table(reload_data=True)
        self._commit_if_changed(before)

    def _move_selection_by_delta(self) -> None:
        """Move selected electrodes, pads, and orientation markers by (dX, dY)."""
        electrodes, pads, markers = self._user_selected_classified_items()
        if not electrodes and not pads and not markers:
            return
        before = self._capture_state()
        try:
            dx = float(self.dx_edit.text())
            dy = float(self.dy_edit.text())
        except ValueError:
            QMessageBox.critical(self, "Invalid dX/dY", "dX and dY must be numeric values.")
            return
        self._is_mutating_scene = True
        try:
            for item in electrodes + pads + markers:
                p = item.pos()
                item.setPos(p.x() + dx, p.y() + dy)
        finally:
            self._is_mutating_scene = False
        self._on_scene_visuals_changed()
        self._commit_if_changed(before)

    def _distribute_selection(self, axis: str) -> None:
        """Evenly space each selected type between its two extremes along X or Y."""
        electrodes, pads, markers = self._user_selected_classified_items()
        if not electrodes and not pads and not markers:
            return
        groups = [group for group in (electrodes, pads, markers) if len(group) >= 3]
        if not groups:
            QMessageBox.information(
                self,
                "Selection too small",
                "Distribute needs at least three selected electrodes, pads, or "
                "orientation markers of the same type.",
            )
            return
        before = self._capture_state()
        self._is_mutating_scene = True
        try:
            for group in groups:
                self._distribute_items_along_axis(group, axis)
        finally:
            self._is_mutating_scene = False
        self._on_scene_visuals_changed()
        self._commit_if_changed(before)

    @staticmethod
    def _distribute_items_along_axis(items, axis: str) -> None:
        """Keep the two extreme items fixed and space the others evenly on one axis."""
        if axis == "x":
            ordered = sorted(items, key=lambda item: (item.pos().x(), item.pos().y()))
            start = ordered[0].pos().x()
            end = ordered[-1].pos().x()
        else:
            ordered = sorted(items, key=lambda item: (item.pos().y(), item.pos().x()))
            start = ordered[0].pos().y()
            end = ordered[-1].pos().y()
        if start == end:
            return
        step = (end - start) / (len(ordered) - 1)
        for index, item in enumerate(ordered[1:-1], start=1):
            pos = item.pos()
            value = start + index * step
            if axis == "x":
                item.setPos(value, pos.y())
            else:
                item.setPos(pos.x(), value)

    def _delete_selected_electrodes(self) -> None:
        """Delete selected electrodes and the pads associated with them."""
        selected = self._selected_electrode_items()
        if not selected:
            return
        before = self._capture_state()
        selected_eids = {item.model.eid for item in selected}
        models = [m for m in self.electrodes.values() if m.eid not in selected_eids]
        pads = [p for p in self.pads.values() if p.electrode_eid not in selected_eids]
        self._set_array(models, pads, keep_markers=True)
        self._commit_if_changed(before)

    def _delete_selected_pads(self) -> None:
        """Delete selected pads only."""
        selected = self._selected_pad_items()
        if not selected:
            return
        before = self._capture_state()
        selected_pad_ids = {item.model.pad_id for item in selected}
        pads = [p for p in self.pads.values() if p.pad_id not in selected_pad_ids]
        self._set_array(list(self.electrodes.values()), pads, keep_markers=True)
        self._commit_if_changed(before)

    def _delete_selected_markers(self) -> None:
        """Delete selected orientation markers only."""
        selected = self._selected_marker_items()
        if not selected:
            return
        before = self._capture_state()
        selected_ids = {item.model.marker_id for item in selected}
        markers = [m for m in self.orientation_markers.values() if m.marker_id not in selected_ids]
        self._set_array(
            list(self.electrodes.values()),
            list(self.pads.values()),
            markers,
        )
        self._commit_if_changed(before)

    def _delete_selected(self) -> None:
        """Delete selected electrodes (and their pads), selected pads, and markers.

        Items selected only because their associated counterpart is selected
        are not deleted on their own. Orientation markers are never auto-selected.
        """
        if self._is_adding():
            return
        electrodes, pads, markers = self._user_selected_classified_items()
        if not electrodes and not pads and not markers:
            return
        before = self._capture_state()
        selected_eids = {item.model.eid for item in electrodes}
        selected_pad_ids = {item.model.pad_id for item in pads}
        selected_marker_ids = {item.model.marker_id for item in markers}
        models = [m for m in self.electrodes.values() if m.eid not in selected_eids]
        remaining_pads = [
            p
            for p in self.pads.values()
            if p.pad_id not in selected_pad_ids and p.electrode_eid not in selected_eids
        ]
        remaining_markers = [
            m for m in self.orientation_markers.values() if m.marker_id not in selected_marker_ids
        ]
        self._set_array(models, remaining_pads, remaining_markers)
        self._commit_if_changed(before)

    def _apply_pending_pad_edits(self) -> None:
        """
        Apply all non-empty pad-panel fields in one confirmation action.

        Empty text fields are treated as "no change". X and Y can be set
        independently: a filled axis is applied to every selected pad.
        """
        selected = self._selected_pad_items()
        if not selected:
            return

        radius_text = self.pad_radius_edit.text().strip()
        height_text = self.pad_height_edit.text().strip()
        x_text = self.pad_x_edit.text().strip()
        y_text = self.pad_y_edit.text().strip()
        electrode_eid = self.pad_electrode_combo.currentData()
        shape_text = self.pad_shape_combo.currentText()
        apply_shape = shape_text != MIXED_SHAPE_LABEL
        shape_value = (
            normalize_contact_shape(shape_text, DEFAULT_PAD_SHAPE) if apply_shape else None
        )

        parsed_xy = self._parse_optional_xy(x_text, y_text)
        if parsed_xy is None:
            return
        x_value, y_value = parsed_xy

        if electrode_eid is not None and electrode_eid != -1 and electrode_eid not in self.electrodes:
            QMessageBox.critical(self, "Invalid electrode", "The associated electrode does not exist.")
            return
        if electrode_eid is not None and electrode_eid != -1:
            selected_pad_ids = {item.model.pad_id for item in selected}
            if len(selected) > 1:
                QMessageBox.information(
                    self,
                    "Unique pad pairing",
                    "Each electrode can be linked to only one pad. "
                    "Select a single pad to change its associated electrode.",
                )
                return
            taken = self._taken_electrode_eids(except_pad_ids=selected_pad_ids)
            if electrode_eid in taken:
                QMessageBox.information(
                    self,
                    "Unique pad pairing",
                    "That electrode already has a pad. Choose an electrode without a pad.",
                )
                return

        before = self._capture_state()

        radius_field: float | None = None
        if radius_text:
            try:
                radius_field = float(radius_text)
                if radius_field <= 0:
                    raise ValueError
            except ValueError:
                size_name = primary_size_field_label(shape_value or DEFAULT_PAD_SHAPE)
                QMessageBox.critical(
                    self,
                    f"Invalid {size_name.lower()}",
                    f"{size_name} must be a positive number.",
                )
                return

        height_field: float | None = None
        if height_text:
            try:
                height_field = float(height_text)
                if height_field <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.critical(self, "Invalid height", "Height must be a positive number.")
                return

        label_position = self._label_position_from_combo(self.pad_label_position_combo)
        label_orientation = self._label_orientation_from_combo(self.pad_label_orientation_combo)

        for item in selected:
            item_shape = (
                shape_value
                if apply_shape
                else normalize_contact_shape(item.model.shape, DEFAULT_PAD_SHAPE)
            )
            if electrode_eid is not None:
                item.model.electrode_eid = int(electrode_eid)
            if apply_shape:
                item.model.shape = item_shape
            if radius_field is not None:
                item.set_radius(stored_half_from_size_field(item_shape, radius_field))
            if label_position is not None:
                item.model.label_position = label_position
            if label_orientation is not None:
                item.model.label_orientation = label_orientation
            if shape_uses_height(item_shape):
                if height_field is not None:
                    item.set_height(stored_half_from_size_field("rect", height_field))
                elif item.model.height <= 0:
                    item.set_height(item.model.radius)
            item.sync_from_model()

        self._apply_xy_to_items(selected, x_value, y_value)

        self._update_duplicate_flags()
        self._refresh_pad_add_electrode_combo()
        self._reveal_confirmed_items(selected, self.pads_map_view)
        self._refresh_panel_values()
        self._sync_electrode_table(reload_data=True)
        self._commit_if_changed(before)

    def _apply_pending_marker_edits(self) -> None:
        """
        Apply all non-empty orientation-marker fields in one confirmation action.

        Empty text fields are treated as "no change". X and Y can be set
        independently: a filled axis is applied to every selected marker.
        """
        selected = self._selected_marker_items()
        if not selected:
            return

        radius_text = self.marker_radius_edit.text().strip()
        height_text = self.marker_height_edit.text().strip()
        x_text = self.marker_x_edit.text().strip()
        y_text = self.marker_y_edit.text().strip()
        shape_text = self.marker_shape_combo.currentText()
        apply_shape = shape_text != MIXED_SHAPE_LABEL
        shape_value = (
            normalize_contact_shape(shape_text, DEFAULT_MARKER_SHAPE) if apply_shape else None
        )

        parsed_xy = self._parse_optional_xy(x_text, y_text)
        if parsed_xy is None:
            return
        x_value, y_value = parsed_xy

        before = self._capture_state()

        radius_field: float | None = None
        if radius_text:
            try:
                radius_field = float(radius_text)
                if radius_field <= 0:
                    raise ValueError
            except ValueError:
                size_name = primary_size_field_label(shape_value or DEFAULT_MARKER_SHAPE)
                QMessageBox.critical(
                    self,
                    f"Invalid {size_name.lower()}",
                    f"{size_name} must be a positive number.",
                )
                return

        height_field: float | None = None
        if height_text:
            try:
                height_field = float(height_text)
                if height_field <= 0:
                    raise ValueError
            except ValueError:
                QMessageBox.critical(self, "Invalid height", "Height must be a positive number.")
                return

        for item in selected:
            item_shape = (
                shape_value
                if apply_shape
                else normalize_contact_shape(item.model.shape, DEFAULT_MARKER_SHAPE)
            )
            if apply_shape:
                item.model.shape = item_shape
            if radius_field is not None:
                item.set_radius(stored_half_from_size_field(item_shape, radius_field))
            if shape_uses_height(item_shape):
                if height_field is not None:
                    item.set_height(stored_half_from_size_field("rect", height_field))
                elif item.model.height <= 0:
                    item.set_height(item.model.radius)
            item.sync_from_model()

        self._apply_xy_to_items(selected, x_value, y_value)

        self._reveal_confirmed_items(selected, self.electrode_view, self.pads_map_view)
        self._refresh_panel_values()
        self._commit_if_changed(before)

    def _refresh_panel_values(self) -> None:
        """
        Update side panel fields according to selection.

        Electrode, pad, and orientation-marker tabs are filled independently.
        A homogeneous selection switches to the matching parameterization tab.
        """
        electrodes, pads, markers = self._classified_selected_items()
        self.selected_count_label.setText(
            f"{len(electrodes)} electrode(s), {len(pads)} pad(s), {len(markers)} marker(s)"
        )

        user_electrodes, user_pads, _user_markers = self._user_selected_classified_items()
        if (
            not self._is_restoring_state
            and not self.is_add_pad_mode
            and not self.is_add_mode
            and not self.is_add_marker_mode
        ):
            if user_pads and self.point_tabs.currentIndex() != TAB_PADS:
                self.point_tabs.blockSignals(True)
                self.point_tabs.setCurrentIndex(TAB_PADS)
                self.point_tabs.blockSignals(False)
            elif user_electrodes and not user_pads and self.point_tabs.currentIndex() != TAB_ELECTRODES:
                self.point_tabs.blockSignals(True)
                self.point_tabs.setCurrentIndex(TAB_ELECTRODES)
                self.point_tabs.blockSignals(False)
            elif markers and not user_pads and not user_electrodes and self.point_tabs.currentIndex() != TAB_MARKERS:
                self.point_tabs.blockSignals(True)
                self.point_tabs.setCurrentIndex(TAB_MARKERS)
                self.point_tabs.blockSignals(False)

        self._fill_electrode_panel(electrodes)
        self._fill_pad_panel(pads)
        self._fill_marker_panel(markers)
        self._sync_electrode_table(reload_data=False)

    def _fill_attribute_edits(self, models: list[Electrode]) -> None:
        """Fill schema-driven attribute editors from one or many electrodes."""
        if not models:
            for edit in self.attribute_edits.values():
                edit.setText("")
            return
        if len(models) == 1:
            model = models[0]
            for spec in self.attribute_schema:
                edit = self.attribute_edits.get(spec.key)
                if edit is None:
                    continue
                edit.setText(str(model.get_attribute(spec.key)))
            return
        for spec in self.attribute_schema:
            edit = self.attribute_edits.get(spec.key)
            if edit is None:
                continue
            values = [model.get_attribute(spec.key) for model in models]
            edit.setText(str(values[0]) if all(value == values[0] for value in values) else "")

    def _fill_electrode_panel(self, selected: list[ElectrodeView]) -> None:
        """Fill electrode parameterization fields from the current selection."""
        if len(selected) == 1:
            m = selected[0].model
            shape = normalize_contact_shape(m.shape, DEFAULT_SHAPE)
            self._set_shape_combo(self.shape_combo, ELECTRODE_SHAPES, shape, mixed=False)
            self._set_electrode_size_label(shape)
            self.radius_edit.setText(f"{size_field_from_stored_half(shape, m.radius):.2f}")
            half_h = effective_half_height(shape, m.radius, m.height)
            self.height_edit.setText(f"{size_field_from_stored_half('rect', half_h):.2f}")
            self._set_height_row_visible(
                self._electrode_geom_form,
                self.electrode_height_label,
                self.height_edit,
                shape_uses_height(shape),
            )
            self._set_xy_edits_from_items(self.x_edit, self.y_edit, selected)
            x0, x1, y0, y1 = m.contact_plane_axis
            self.contact_plane_axis_edit.setText(f"{x0:g}, {x1:g}, {y0:g}, {y1:g}")
            self._set_label_position_combo(self.label_position_combo, m.label_position, mixed=False)
            self._set_label_orientation_combo(
                self.label_orientation_combo, m.label_orientation, mixed=False
            )
            self._fill_attribute_edits([m])
            return

        if len(selected) > LARGE_SELECTION_PANEL:
            self.radius_edit.setText("")
            self.height_edit.setText("")
            self._set_xy_edits_from_items(self.x_edit, self.y_edit, selected)
            self.contact_plane_axis_edit.setText("")
            self._set_shape_combo(self.shape_combo, ELECTRODE_SHAPES, DEFAULT_SHAPE, mixed=True)
            self._electrode_size_shape = MIXED_SHAPE_LABEL
            self.electrode_size_label.setText("Size")
            self._set_label_position_combo(
                self.label_position_combo, DEFAULT_LABEL_POSITION, mixed=True
            )
            self._set_label_orientation_combo(
                self.label_orientation_combo, DEFAULT_LABEL_ORIENTATION, mixed=True
            )
            self._set_height_row_visible(
                self._electrode_geom_form,
                self.electrode_height_label,
                self.height_edit,
                False,
            )
            self._fill_attribute_edits([])
            return

        if len(selected) > 1:
            shapes = [normalize_contact_shape(it.model.shape, DEFAULT_SHAPE) for it in selected]
            mixed_shape = not all(s == shapes[0] for s in shapes)
            common_shape = shapes[0] if not mixed_shape else DEFAULT_SHAPE
            sizes = [size_field_from_stored_half(it.model.shape, it.model.radius) for it in selected]
            axes = [it.model.contact_plane_axis for it in selected]
            self._set_shape_combo(self.shape_combo, ELECTRODE_SHAPES, common_shape, mixed=mixed_shape)
            if mixed_shape:
                self._electrode_size_shape = MIXED_SHAPE_LABEL
                self.electrode_size_label.setText("Size")
            else:
                self._set_electrode_size_label(common_shape)
            self.radius_edit.setText(f"{sizes[0]:.2f}" if max(sizes) - min(sizes) < 1e-9 else "")
            if not mixed_shape and shape_uses_height(common_shape):
                heights = [
                    size_field_from_stored_half(
                        "rect",
                        effective_half_height(it.model.shape, it.model.radius, it.model.height),
                    )
                    for it in selected
                ]
                self.height_edit.setText(f"{heights[0]:.2f}" if max(heights) - min(heights) < 1e-9 else "")
            else:
                self.height_edit.setText("")
            self._set_height_row_visible(
                self._electrode_geom_form,
                self.electrode_height_label,
                self.height_edit,
                (not mixed_shape) and shape_uses_height(common_shape),
            )
            if all(a == axes[0] for a in axes):
                x0, x1, y0, y1 = axes[0]
                self.contact_plane_axis_edit.setText(f"{x0:g}, {x1:g}, {y0:g}, {y1:g}")
            else:
                self.contact_plane_axis_edit.setText("")
            self._set_xy_edits_from_items(self.x_edit, self.y_edit, selected)
            positions = [normalize_label_position(it.model.label_position) for it in selected]
            mixed_position = not all(p == positions[0] for p in positions)
            self._set_label_position_combo(self.label_position_combo, positions[0], mixed=mixed_position)
            orientations = [normalize_label_orientation(it.model.label_orientation) for it in selected]
            mixed_orientation = not all(o == orientations[0] for o in orientations)
            self._set_label_orientation_combo(
                self.label_orientation_combo, orientations[0], mixed=mixed_orientation
            )
            self._fill_attribute_edits([it.model for it in selected])
            return

        self.radius_edit.setText("")
        self.height_edit.setText("")
        self.x_edit.setText("")
        self.y_edit.setText("")
        self.contact_plane_axis_edit.setText("")
        self._set_shape_combo(self.shape_combo, ELECTRODE_SHAPES, DEFAULT_SHAPE, mixed=False)
        self._set_electrode_size_label(DEFAULT_SHAPE)
        self._set_label_position_combo(self.label_position_combo, DEFAULT_LABEL_POSITION, mixed=False)
        self._set_label_orientation_combo(
            self.label_orientation_combo, DEFAULT_LABEL_ORIENTATION, mixed=False
        )
        self._set_height_row_visible(
            self._electrode_geom_form,
            self.electrode_height_label,
            self.height_edit,
            False,
        )
        self._fill_attribute_edits([])

    def _fill_pad_panel(self, selected: list[PadView]) -> None:
        """Fill pad parameterization fields from the current selection."""
        if len(selected) == 1:
            m = selected[0].model
            shape = normalize_contact_shape(m.shape, DEFAULT_PAD_SHAPE)
            self._set_shape_combo(self.pad_shape_combo, PAD_SHAPES, shape, mixed=False)
            self._set_pad_size_label(shape)
            self.pad_radius_edit.setText(f"{size_field_from_stored_half(shape, m.radius):.2f}")
            half_h = effective_half_height(shape, m.radius, m.height)
            self.pad_height_edit.setText(f"{size_field_from_stored_half('rect', half_h):.2f}")
            self._set_height_row_visible(
                self._pad_form,
                self.pad_height_label,
                self.pad_height_edit,
                shape_uses_height(shape),
            )
            self._set_xy_edits_from_items(self.pad_x_edit, self.pad_y_edit, selected)
            self.pad_id_edit.setText(str(m.pad_id))
            self._set_label_position_combo(
                self.pad_label_position_combo, m.label_position, mixed=False
            )
            self._set_label_orientation_combo(
                self.pad_label_orientation_combo, m.label_orientation, mixed=False
            )
            self._refresh_pad_electrode_combo(
                selected_eid=m.electrode_eid,
                mixed=False,
                keep_eids={m.electrode_eid},
            )
            return

        if len(selected) > LARGE_SELECTION_PANEL:
            self.pad_radius_edit.setText("")
            self.pad_height_edit.setText("")
            self._set_xy_edits_from_items(self.pad_x_edit, self.pad_y_edit, selected)
            self.pad_id_edit.setText("")
            self._set_shape_combo(self.pad_shape_combo, PAD_SHAPES, DEFAULT_PAD_SHAPE, mixed=True)
            self._pad_size_shape = MIXED_SHAPE_LABEL
            self.pad_size_label.setText("Size")
            self._set_label_position_combo(
                self.pad_label_position_combo, DEFAULT_LABEL_POSITION, mixed=True
            )
            self._set_label_orientation_combo(
                self.pad_label_orientation_combo, DEFAULT_LABEL_ORIENTATION, mixed=True
            )
            self._set_height_row_visible(
                self._pad_form,
                self.pad_height_label,
                self.pad_height_edit,
                False,
            )
            combo = self.pad_electrode_combo
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(mixed)", None)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
            self._pad_combo_sig = None
            return

        if len(selected) > 1:
            sizes = [size_field_from_stored_half(it.model.shape, it.model.radius) for it in selected]
            eids = [it.model.electrode_eid for it in selected]
            pad_ids = [it.model.pad_id for it in selected]
            shapes = [normalize_contact_shape(it.model.shape, DEFAULT_PAD_SHAPE) for it in selected]
            mixed_eid = not all(eid == eids[0] for eid in eids)
            mixed_shape = not all(s == shapes[0] for s in shapes)
            common_shape = shapes[0] if not mixed_shape else DEFAULT_PAD_SHAPE
            self._set_shape_combo(self.pad_shape_combo, PAD_SHAPES, common_shape, mixed=mixed_shape)
            if mixed_shape:
                self._pad_size_shape = MIXED_SHAPE_LABEL
                self.pad_size_label.setText("Size")
            else:
                self._set_pad_size_label(common_shape)
            self.pad_radius_edit.setText(f"{sizes[0]:.2f}" if max(sizes) - min(sizes) < 1e-9 else "")
            if not mixed_shape and shape_uses_height(common_shape):
                heights = [
                    size_field_from_stored_half(
                        "rect",
                        effective_half_height(it.model.shape, it.model.radius, it.model.height),
                    )
                    for it in selected
                ]
                self.pad_height_edit.setText(f"{heights[0]:.2f}" if max(heights) - min(heights) < 1e-9 else "")
            else:
                self.pad_height_edit.setText("")
            self._set_height_row_visible(
                self._pad_form,
                self.pad_height_label,
                self.pad_height_edit,
                (not mixed_shape) and shape_uses_height(common_shape),
            )
            self.pad_id_edit.setText(
                str(pad_ids[0]) if all(value == pad_ids[0] for value in pad_ids) else ""
            )
            self._set_xy_edits_from_items(self.pad_x_edit, self.pad_y_edit, selected)
            positions = [normalize_label_position(it.model.label_position) for it in selected]
            mixed_position = not all(p == positions[0] for p in positions)
            self._set_label_position_combo(
                self.pad_label_position_combo, positions[0], mixed=mixed_position
            )
            orientations = [normalize_label_orientation(it.model.label_orientation) for it in selected]
            mixed_orientation = not all(o == orientations[0] for o in orientations)
            self._set_label_orientation_combo(
                self.pad_label_orientation_combo, orientations[0], mixed=mixed_orientation
            )
            self._refresh_pad_electrode_combo(
                selected_eid=None if mixed_eid else eids[0],
                mixed=mixed_eid,
                keep_eids=set(eids),
            )
            return

        self.pad_radius_edit.setText("")
        self.pad_height_edit.setText("")
        self.pad_x_edit.setText("")
        self.pad_y_edit.setText("")
        self.pad_id_edit.setText("")
        self._set_shape_combo(self.pad_shape_combo, PAD_SHAPES, DEFAULT_PAD_SHAPE, mixed=False)
        self._set_pad_size_label(DEFAULT_PAD_SHAPE)
        self._set_label_position_combo(
            self.pad_label_position_combo, DEFAULT_LABEL_POSITION, mixed=False
        )
        self._set_label_orientation_combo(
            self.pad_label_orientation_combo, DEFAULT_LABEL_ORIENTATION, mixed=False
        )
        self._set_height_row_visible(
            self._pad_form,
            self.pad_height_label,
            self.pad_height_edit,
            False,
        )
        self._refresh_pad_electrode_combo()

    def _fill_marker_panel(self, selected: list[OrientationMarkerView]) -> None:
        """Fill orientation-marker parameterization fields from the current selection."""
        if len(selected) == 1:
            m = selected[0].model
            shape = normalize_contact_shape(m.shape, DEFAULT_MARKER_SHAPE)
            self._set_shape_combo(self.marker_shape_combo, MARKER_SHAPES, shape, mixed=False)
            self._set_marker_size_label(shape)
            self.marker_radius_edit.setText(f"{size_field_from_stored_half(shape, m.radius):.2f}")
            half_h = effective_half_height(shape, m.radius, m.height)
            self.marker_height_edit.setText(f"{size_field_from_stored_half('rect', half_h):.2f}")
            self._set_height_row_visible(
                self._marker_form,
                self.marker_height_label,
                self.marker_height_edit,
                shape_uses_height(shape),
            )
            self.marker_id_edit.setText(str(m.marker_id))
            self._set_xy_edits_from_items(self.marker_x_edit, self.marker_y_edit, selected)
            return

        if len(selected) > LARGE_SELECTION_PANEL:
            self.marker_radius_edit.setText("")
            self.marker_height_edit.setText("")
            self._set_xy_edits_from_items(self.marker_x_edit, self.marker_y_edit, selected)
            self.marker_id_edit.setText("")
            self._set_shape_combo(
                self.marker_shape_combo, MARKER_SHAPES, DEFAULT_MARKER_SHAPE, mixed=True
            )
            self._marker_size_shape = MIXED_SHAPE_LABEL
            self.marker_size_label.setText("Size")
            self._set_height_row_visible(
                self._marker_form,
                self.marker_height_label,
                self.marker_height_edit,
                False,
            )
            return

        if len(selected) > 1:
            sizes = [size_field_from_stored_half(it.model.shape, it.model.radius) for it in selected]
            marker_ids = [it.model.marker_id for it in selected]
            shapes = [normalize_contact_shape(it.model.shape, DEFAULT_MARKER_SHAPE) for it in selected]
            mixed_shape = not all(s == shapes[0] for s in shapes)
            common_shape = shapes[0] if not mixed_shape else DEFAULT_MARKER_SHAPE
            self._set_shape_combo(self.marker_shape_combo, MARKER_SHAPES, common_shape, mixed=mixed_shape)
            if mixed_shape:
                self._marker_size_shape = MIXED_SHAPE_LABEL
                self.marker_size_label.setText("Size")
            else:
                self._set_marker_size_label(common_shape)
            self.marker_radius_edit.setText(f"{sizes[0]:.2f}" if max(sizes) - min(sizes) < 1e-9 else "")
            if not mixed_shape and shape_uses_height(common_shape):
                heights = [
                    size_field_from_stored_half(
                        "rect",
                        effective_half_height(it.model.shape, it.model.radius, it.model.height),
                    )
                    for it in selected
                ]
                self.marker_height_edit.setText(
                    f"{heights[0]:.2f}" if max(heights) - min(heights) < 1e-9 else ""
                )
            else:
                self.marker_height_edit.setText("")
            self._set_height_row_visible(
                self._marker_form,
                self.marker_height_label,
                self.marker_height_edit,
                (not mixed_shape) and shape_uses_height(common_shape),
            )
            self.marker_id_edit.setText(
                str(marker_ids[0]) if all(value == marker_ids[0] for value in marker_ids) else ""
            )
            self._set_xy_edits_from_items(self.marker_x_edit, self.marker_y_edit, selected)
            return

        self.marker_radius_edit.setText("")
        self.marker_height_edit.setText("")
        self.marker_x_edit.setText("")
        self.marker_y_edit.setText("")
        self.marker_id_edit.setText("")
        self._set_shape_combo(self.marker_shape_combo, MARKER_SHAPES, DEFAULT_MARKER_SHAPE, mixed=False)
        self._set_marker_size_label(DEFAULT_MARKER_SHAPE)
        self._set_height_row_visible(
            self._marker_form,
            self.marker_height_label,
            self.marker_height_edit,
            False,
        )


def run_app() -> None:
    """
    Application entry point.

    Creates QApplication, ElectrodeArrayEditorQt window, shows and runs event loop.
    """
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("Wireless Neural Interface Team")
    win = ElectrodeArrayEditorQt()
    win.show()
    win.raise_()
    win.activateWindow()
    app.exec()


if __name__ == "__main__":
    run_app()
