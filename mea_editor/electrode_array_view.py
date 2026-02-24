"""
Interactive viewport for the electrode scene.

Responsibilities:
- pan/zoom behavior and mouse interactions,
- add-mode click handling,
- drawing dynamic grid/axis overlays.
"""

from __future__ import annotations

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QPainter, QPen
    from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc

# Overlay axis band dimensions (in viewport pixels).
AXIS_BAND_HEIGHT = 24
AXIS_BAND_WIDTH = 52
# Min pixel distance between axis tick labels to avoid overlap.
GRID_MIN_LABEL_SPACING_PX = 44


class ElectrodeArrayView(QGraphicsView):
    """
    Interactive viewport for the electrode scene.

    Responsibilities:
    - pan/zoom behavior and mouse interactions,
    - add-mode click handling,
    - drawing dynamic grid/axis overlays.
    """

    def __init__(self, scene: QGraphicsScene) -> None:
        """
        Initialize the graphics view for the electrode scene.

        Args:
            scene: Qt scene containing items (electrodes, grid).
        """
        super().__init__(scene)
        # Antialiasing improves circle and text rendering quality.
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setFrameShape(QFrame.NoFrame)
        # Keep content centered when viewport is larger than scene.
        self.setAlignment(Qt.AlignCenter)
        # Rubber-band drag enables box selection on empty area.
        self.setDragMode(QGraphicsView.RubberBandDrag)
        # Limit repaint to changed regions for better performance.
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setBackgroundBrush(QColor("#11151a"))
        # Cartesian orientation for scene coordinates: Y grows upward.
        # Qt view Y is naturally downward; scale(1,-1) flips it.
        self.scale(1.0, -1.0)
        self._interaction_begin = lambda: None
        self._interaction_end = lambda: None
        self._is_add_mode = lambda: False
        self._add_electrode_at = lambda x, y: None
        self._on_delete = lambda: None
        self._on_view_transform_changed = lambda: None

    def set_interaction_callbacks(self, on_begin, on_end) -> None:
        """
        Register callbacks for the start and end of a drag interaction.

        These callbacks capture state before/after a move for undo/redo.

        Args:
            on_begin: Function called on mousePress (capture snapshot).
            on_end: Function called on mouseRelease (commit if changed).
        """
        self._interaction_begin = on_begin
        self._interaction_end = on_end

    def set_add_callbacks(self, is_add_mode, add_electrode_at) -> None:
        """
        Register callbacks for add-electrode mode.

        Args:
            is_add_mode: Function returning True if add mode is active.
            add_electrode_at: Function(x, y) creating an electrode at the given position.
        """
        self._is_add_mode = is_add_mode
        self._add_electrode_at = add_electrode_at

    def set_delete_callback(self, on_delete) -> None:
        """
        Register callback for delete-selected action (Suppr/Backspace).
        """
        self._on_delete = on_delete

    def set_view_transform_changed_callback(self, on_changed) -> None:
        """
        Register callback when view zoom/pan changes (for label layout refresh).
        """
        self._on_view_transform_changed = on_changed

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """
        Handle mouse click: add mode or start interaction for undo.
        """
        # Left button only.
        if event.button() == Qt.LeftButton:
            # In add mode, left-click creates an electrode at cursor position.
            if self._is_add_mode():
                scene_pos = self.mapToScene(event.pos())
                self._add_electrode_at(scene_pos.x(), scene_pos.y())
                event.accept()
                return
            # Otherwise, record state for potential undo on drag end.
            self._interaction_begin()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """
        On click release, finalize interaction (commit undo if needed).
        """
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            # Commit undo snapshot if something changed during drag.
            self._interaction_end()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """
        Handle Suppr/Backspace to delete selected electrodes when view has focus.
        """
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self._on_delete()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        """
        Zoom centered on cursor: the point under the mouse stays fixed.

        Store scene point under cursor, apply scale, then adjust scrollbars
        so that point remains under the cursor.
        """
        # event.position() is Qt6; event.pos() fallback for older APIs.
        try:
            mouse_pos = event.position().toPoint()
        except AttributeError:
            mouse_pos = event.pos()

        # Remember which scene point is under the cursor before scaling.
        scene_pos_before = self.mapToScene(mouse_pos)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

        # After scale, that scene point moved in viewport; adjust scrollbars
        # so it stays under the cursor (zoom appears centered on mouse).
        viewport_pos_after = self.mapFromScene(scene_pos_before)
        delta_view = viewport_pos_after - mouse_pos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta_view.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta_view.y())

        # Labels use ItemIgnoresTransformations; refresh their layout for new scale.
        self._on_view_transform_changed()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # type: ignore[override]
        """
        Force overlay repaint when panning with scrollbars.

        Without this, axis bands would stay fixed during scroll.
        """
        super().scrollContentsBy(dx, dy)
        scene = self.scene()
        if scene is not None:
            scene.invalidate(
                scene.sceneRect(),
                QGraphicsScene.BackgroundLayer | QGraphicsScene.ForegroundLayer,
            )
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect) -> None:  # type: ignore[override]
        """
        Draw grid lines in scene coordinates.

        X/Y positions come from electrodes via scene.get_axes().
        Vertical lines follow X values, horizontal lines follow Y values.
        """
        super().drawBackground(painter, rect)
        scene = self.scene()
        if scene is None or not hasattr(scene, "get_axes"):
            return
        # Axes come from unique electrode X/Y; grid follows electrode layout.
        xs, ys = scene.get_axes()  # type: ignore[attr-defined]
        if not xs and not ys:
            return
        grid_pen = QPen(QColor("#3b4f66"))
        grid_pen.setWidthF(0)  # Cosmetic width: 1 logical pixel.
        painter.setPen(grid_pen)
        for x in xs:
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in ys:
            painter.drawLine(rect.left(), y, rect.right(), y)

    def drawForeground(self, painter: QPainter, rect) -> None:  # type: ignore[override]
        """
        Draw fixed overlays (axis bands + numeric ticks).

        In viewport coordinates to stay fixed on screen during zoom/pan.
        """
        super().drawForeground(painter, rect)
        scene = self.scene()
        if scene is None or not hasattr(scene, "get_axes"):
            return

        xs, ys = scene.get_axes()  # type: ignore[attr-defined]
        if not xs and not ys:
            return

        painter.save()
        # Draw overlays in viewport coordinates (fixed on screen).
        painter.resetTransform()

        vp = self.viewport().rect()
        axis_h = AXIS_BAND_HEIGHT
        axis_w = AXIS_BAND_WIDTH

        # Dark bands for axis labels (top horizontal, left vertical).
        painter.fillRect(0, 0, vp.width(), axis_h, QColor("#0f1318"))
        painter.fillRect(0, 0, axis_w, vp.height(), QColor("#0f1318"))

        # Separator lines between axis bands and plot area.
        sep_pen = QPen(QColor("#3b4f66"))
        painter.setPen(sep_pen)
        painter.drawLine(axis_w, 0, axis_w, vp.height())
        painter.drawLine(0, axis_h, vp.width(), axis_h)

        # Axis labels: Y bottom-left, X top-left of plot area.
        painter.setPen(QColor("#9fb3c8"))
        baseline_y = vp.height() - 8
        painter.drawText(6, baseline_y, "Y")
        painter.drawText(axis_w + 6, 16, "X")

        # X ticks: skip if outside visible area or too close to previous label.
        min_px_spacing = GRID_MIN_LABEL_SPACING_PX
        last_x_px = -10_000
        for x in xs:
            px = self.mapFromScene(x, 0).x()
            if px < axis_w or px > vp.width() - 2:
                continue
            if px - last_x_px < min_px_spacing:
                continue
            last_x_px = px
            painter.setPen(QColor("#6e88a5"))
            painter.drawLine(px, axis_h - 6, px, axis_h)
            painter.setPen(QColor("#d3dbe4"))
            painter.drawText(px + 3, 16, f"{x:.1f}")

        # Y ticks: same logic; abs() needed because Y may increase upward or down.
        last_y_px = -10_000
        for y in ys:
            py = self.mapFromScene(0, y).y()
            if py < axis_h or py > vp.height() - 2:
                continue
            if abs(py - last_y_px) < min_px_spacing:
                continue
            last_y_px = py
            painter.setPen(QColor("#6e88a5"))
            painter.drawLine(axis_w - 6, py, axis_w, py)
            painter.setPen(QColor("#d3dbe4"))
            painter.drawText(4, py - 3, f"{y:.1f}")

        painter.restore()
