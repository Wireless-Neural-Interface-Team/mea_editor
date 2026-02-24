"""
Interactive graphics item bound to one Electrode model.

It owns:
- circular shape path,
- center label (channel_index),
- bottom label (contact_id).
"""

from __future__ import annotations

try:
    from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QTransform
    from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsSimpleTextItem
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc

from .electrode import Electrode


class ElectrodeView(QGraphicsPathItem):
    """
    Interactive graphics item bound to one `Electrode` model.

    It owns:
    - circular shape path,
    - center label (`channel_index`),
    - bottom label (`contact_id`).
    """

    def __init__(self, model: Electrode, on_change, on_selection_change) -> None:
        super().__init__()
        self.model = model
        self._on_change = on_change
        self._on_selection_change = on_selection_change
        # ItemSendsGeometryChanges required for ItemPositionHasChanged in itemChange.
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(10)  # Above grid lines.

        # Labels must exist before set_radius() (which calls _layout_labels).
        # ItemIgnoresTransformations keeps text at constant screen size when zooming.
        label_font = QFont()
        label_font.setPointSize(9)
        self.label = QGraphicsSimpleTextItem(str(model.channel_index), self)
        self.label.setBrush(QBrush(QColor("#e9edf2")))
        self.label.setFont(label_font)
        self.label.setTransform(QTransform.fromScale(1.0, 1.0))  # Readable in Cartesian Y.
        self.label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.contact_label = QGraphicsSimpleTextItem(str(model.contact_id), self)
        self.contact_label.setBrush(QBrush(QColor("#d3dbe4")))
        self.contact_label.setFont(label_font)
        self.contact_label.setTransform(QTransform.fromScale(1.0, 1.0))
        self.contact_label.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.set_radius(model.radius)
        self.setPos(model.x, model.y)
        self._layout_labels()
        self._refresh_style()

    def _refresh_label(self) -> None:
        """
        Sync label text from model and reposition labels.

        Updates channel_index (center) and contact_id (below circle).
        """
        self.label.setText(str(self.model.channel_index))
        self.contact_label.setText(str(self.model.contact_id))
        self._layout_labels()

    def _view_scale(self) -> float:
        """
        Get the view's scale factor (scene units per pixel) for label positioning.
        With ItemIgnoresTransformations, label dimensions are in pixels; we need
        to convert to scene units for correct positioning at any zoom level.
        """
        scene = self.scene()
        if scene is None:
            return 1.0
        views = scene.views()
        if not views:
            return 1.0
        t = views[0].transform()
        scale = abs(t.m11()) if t.m11() != 0 else 1.0
        return max(scale, 1e-6)  # Avoid division by zero

    def _layout_labels(self) -> None:
        """
        Position labels: channel_index at center, contact_id below circle.

        With ItemIgnoresTransformations, label bounding rects are in pixels;
        we convert to scene units using the view scale for correct placement.
        """
        scale = self._view_scale()
        # Channel index centered inside electrode (item coords: center at origin).
        br = self.label.boundingRect()
        # Convert pixel dimensions to scene units: scene = pixels / scale
        label_w, label_h = br.width() / scale, br.height() / scale
        self.label.setPos(-label_w / 2, label_h / 2)
        # contact_id displayed below each electrode with small gap.
        cbr = self.contact_label.boundingRect()
        contact_h = cbr.height() / scale
        y_offset = self.model.radius + contact_h + 4.0
        contact_w = cbr.width() / scale
        self.contact_label.setPos(-contact_w / 2, y_offset)

    def set_radius(self, radius: float) -> None:
        """
        Update model radius and path geometry (ellipse).
        """
        self.model.radius = radius
        path = QPainterPath()
        # Ellipse centered at item origin (0,0).
        path.addEllipse(-radius, -radius, 2 * radius, 2 * radius)
        self.setPath(path)
        # Guard: labels may not exist during early init.
        if hasattr(self, "label") and hasattr(self, "contact_label"):
            self._layout_labels()

    def _refresh_style(self) -> None:
        """
        Apply fill and outline colors based on state.

        Priority: duplicate (red) > selected (yellow) > enabled (blue) > disabled (gray).
        """
        # Duplicate state overrides selection and enabled for visibility.
        is_duplicate = self.model.has_channel_duplicate or self.model.has_contact_duplicate
        if is_duplicate:
            fill = QColor("#d44b4b")
            outline = QColor("#ffe0e0")
        elif self.isSelected():
            fill = QColor("#ffd447")
            outline = QColor("#f6f7f8")
        elif self.model.enabled:
            fill = QColor("#3da5ff")
            outline = QColor("#232b35")
        else:
            fill = QColor("#4f5761")
            outline = QColor("#232b35")
        self.setBrush(QBrush(fill))
        self.setPen(QPen(outline, 2))

    def itemChange(self, change, value):  # type: ignore[override]
        """
        Qt callback fired on item state/geometry changes.

        - ItemPositionHasChanged: copy x/y to model, notify controller.
        - ItemSelectedHasChanged: refresh style and side panel.
        """
        if change == QGraphicsItem.ItemPositionHasChanged:
            p = self.pos()
            self.model.x = p.x()
            self.model.y = p.y()
            self._on_change()
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            self._refresh_style()
            self._on_selection_change()
        return super().itemChange(change, value)

    def sync_from_model(self) -> None:
        """
        Apply model state to visual item.

        Updates: position, radius, label text, colors.
        """
        self.setPos(self.model.x, self.model.y)
        self.set_radius(self.model.radius)
        self._refresh_label()
        self._refresh_style()
