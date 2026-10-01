"""
Interactive viewport for the electrode scene.

Responsibilities:
- pan/zoom behavior and mouse interactions,
- add-mode click handling,
- drawing dynamic grid/axis overlays.
"""

from __future__ import annotations

from typing import NamedTuple

try:
    from PySide6.QtCore import QPointF, QRect, QRectF, Qt
    from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
    from PySide6.QtWidgets import (
        QFrame,
        QGraphicsScene,
        QGraphicsView,
        QStyle,
        QStyleOptionGraphicsItem,
    )
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc

from .contact_shape import contact_half_extents
from .electrode import (
    DEFAULT_LABEL_ORIENTATION,
    DEFAULT_LABEL_POSITION,
    map_label_item_pos,
    normalize_label_orientation,
    normalize_label_position,
)

# Overlay axis band dimensions (in viewport pixels).
AXIS_BAND_HEIGHT = 24
AXIS_BAND_WIDTH = 52
# Min pixel distance between axis tick labels to avoid overlap.
GRID_MIN_LABEL_SPACING_PX = 44
# Min pixel distance between grid lines (tighter than tick labels).
GRID_MIN_LINE_SPACING_PX = 8
# Hide map labels when the contact is smaller than this on screen.
LABEL_MIN_CONTACT_PX = 8.0
MAP_LABEL_FONT_POINT = 9
# Skip antialiasing when the view transform is this small.
AA_MIN_LOD = 0.35
# Keep contact labels inside the plot area when fitting.
FIT_LABEL_MARGIN_PX = 42.0
# Absolute zoom floor/ceiling (scene units per pixel). The floor must stay
# below a typical pad-view fit scale, otherwise wheel zoom is a no-op in both
# directions (new_scale stays < min). Pads surround the array so they fit
# smaller than electrodes.
ZOOM_MIN_SCALE = 1e-4
ZOOM_MAX_SCALE = 250.0
_IDLE_VIEWPORT_UPDATE = QGraphicsView.BoundingRectViewportUpdate


def clamp_zoom_factor(current: float, factor: float) -> float | None:
    """Keep `current * factor` inside [ZOOM_MIN_SCALE, ZOOM_MAX_SCALE].

    If the view is already outside the range (a fitted pad camera can sit
    below a previous min), still allow a step that moves back toward it.
    Return None only when that direction is fully blocked.
    """
    if current <= 0 or factor == 1.0:
        return None
    if factor > 1.0:
        if current >= ZOOM_MAX_SCALE:
            return None
        return min(factor, ZOOM_MAX_SCALE / current)
    if current <= ZOOM_MIN_SCALE:
        return None
    return max(factor, ZOOM_MIN_SCALE / current)


def grow_scene_rect_to_include(scene: QGraphicsScene | None, rect: QRectF) -> None:
    """Union `rect` into the shared scene rect without jumping other cameras.

    QGraphicsView clamps pan/zoom-to-cursor to sceneRect. Growing it lets a
    mapping view zoom out past the fitted content. setSceneRect recenters
    AlignCenter cameras, so each view's scene point at the viewport center
    is restored afterwards.
    """
    if scene is None or not rect.isValid() or rect.isEmpty():
        return
    current = scene.sceneRect()
    if current.isValid() and not current.isEmpty() and current.contains(rect):
        return
    cameras = []
    for view in scene.views():
        capture = getattr(view, "capture_camera", None)
        if capture is not None:
            cameras.append((view, capture()))
    scene.setSceneRect(current.united(rect) if current.isValid() and not current.isEmpty() else rect)
    for view, center in cameras:
        restore = getattr(view, "restore_camera", None)
        if restore is not None:
            restore(center)


def subsample_axis_positions(
    values,
    map_px,
    min_spacing_px: float,
    lo: float | None = None,
    hi: float | None = None,
) -> list:
    """Keep increasing coordinates whose projected pixels stay `min_spacing_px` apart."""
    kept = []
    last_px = None
    for value in values:
        if lo is not None and value < lo:
            continue
        if hi is not None and value > hi:
            continue
        px = map_px(value)
        if last_px is not None and abs(px - last_px) < min_spacing_px:
            continue
        kept.append(value)
        last_px = px
    return kept


class OverlayLabelPart(NamedTuple):
    """One map label in contact item coordinates, sized in viewport pixels."""

    item_pos: QPointF
    pixel_w: float
    pixel_h: float
    degrees: int
    text: str
    contrast: bool
    is_center: bool


def overlay_label_parts(item, scale: float, metrics: QFontMetrics) -> list[OverlayLabelPart]:
    """Layout center/outside map text for overlay painting (no scene items)."""
    center = str(getattr(item, "_label_center", "") or "")
    below = str(getattr(item, "_label_below", "") or "")
    if not center and not below:
        return []
    half_fn = getattr(item, "_label_half_extents", None)
    if half_fn is None:
        return []
    half_x, half_y = half_fn()
    if max(half_x, half_y) * 2.0 * scale < LABEL_MIN_CONTACT_PX:
        return []
    model = item.model
    position = normalize_label_position(
        getattr(model, "label_position", DEFAULT_LABEL_POSITION)
    )
    orientation = normalize_label_orientation(
        getattr(model, "label_orientation", DEFAULT_LABEL_ORIENTATION)
    )
    parts: list[OverlayLabelPart] = []
    flags = int(Qt.AlignLeft | Qt.AlignTop | Qt.TextDontClip)
    if center:
        br = metrics.boundingRect(QRect(0, 0, 400, 200), flags, center)
        pw, ph = float(br.width()), float(br.height())
        parts.append(
            OverlayLabelPart(
                QPointF(-pw / (2.0 * scale), ph / (2.0 * scale)),
                pw,
                ph,
                0,
                center,
                False,
                True,
            )
        )
    if below:
        br = metrics.boundingRect(QRect(0, 0, 400, 400), flags, below)
        pw, ph = float(br.width()), float(br.height())
        degrees = orientation
        space_w = float(max(0, metrics.horizontalAdvance(" "))) / scale
        x, y = map_label_item_pos(
            position,
            half_x,
            half_y,
            pw / scale,
            ph / scale,
            orientation=degrees,
            space_w=space_w,
        )
        parts.append(OverlayLabelPart(QPointF(x, y), pw, ph, degrees, below, True, False))
    return parts


def _option_without_qt_selection(option):
    """Copy a paint option without Qt's default selection overlay.

    QGraphicsPathItem / QGraphicsSimpleTextItem otherwise draw a dashed
    rectangle around exposedRect. With ItemIgnoresTransformations labels
    or a rubber-band update region, that rect can cover a whole column
    and show up as a white bar on the dark canvas.
    """
    opt = QStyleOptionGraphicsItem(option)
    opt.state &= ~QStyle.State_Selected
    return opt


class PerViewContactLabels:
    """
    Map-label text stored on the contact (drawn by the mapping view overlay).

    Labels are not QGraphicsItems: thousands of ItemIgnoresTransformations
    children made rubber-band selection and pan unusable.
    """

    def _init_view_labels(self) -> None:
        self._label_center = ""
        self._label_below = ""
        self._label_center_color = QColor("#e9edf2")
        self._label_below_color = QColor("#ffffff")

    def _set_label_text(self, center: str, below: str) -> None:
        self._label_center = center
        self._label_below = below

    def _label_half_extents(self) -> tuple[float, float]:
        return contact_half_extents(self.model.shape, self.model.radius, self.model.height)

    def _layout_labels(self, view_attr: str | None = None, **_kwargs) -> None:
        return

    def mark_label_layout_dirty(self, view_attr: str, current_scale: float) -> None:
        return

    def paint(self, painter, option, widget=None) -> None:  # type: ignore[override]
        lod = QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        if lod < AA_MIN_LOD:
            painter.setRenderHint(QPainter.Antialiasing, False)
        super().paint(painter, _option_without_qt_selection(option), widget)


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
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setFrameShape(QFrame.NoFrame)
        # Keep content centered when the transformed scene is smaller than the view.
        self.setAlignment(Qt.AlignCenter)
        # Rubber-band drag enables box selection on empty area.
        self.setDragMode(QGraphicsView.RubberBandDrag)
        # Partial updates: overlay labels are not scene items, so a full
        # redraw is no longer required to avoid rubber-band artifacts.
        self.setViewportUpdateMode(_IDLE_VIEWPORT_UPDATE)
        self.setBackgroundBrush(QColor("#11151a"))
        # Cartesian orientation for scene coordinates: Y grows upward.
        # Qt view Y is naturally downward; scale(1,-1) flips it.
        self.scale(1.0, -1.0)
        # Pan is middle-drag; hiding scrollbars keeps the viewport size
        # stable so fit/center is not shifted by a late scrollbar.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._is_add_mode = lambda: False
        self._add_at = lambda x, y: None
        self._cancel_add = lambda: None
        self._on_delete = lambda: None
        self._on_view_transform_changed = lambda view=None: None
        self._on_rubber_band_started = lambda: None
        self._on_rubber_band_finished = lambda: None
        self._on_activated = lambda: None
        self._is_middle_panning = False
        self._last_pan_pos = None
        self._map_label_font = QFont()
        self._map_label_font.setPointSize(MAP_LABEL_FONT_POINT)

    def set_add_callbacks(self, is_add_mode, add_at, cancel_add=None) -> None:
        """
        Register callbacks for add-point mode (electrode, pad, or marker).

        Args:
            is_add_mode: Function returning True if add mode is active.
            add_at: Function(x, y) creating a point at the given position.
            cancel_add: Function leaving add mode (Escape).
        """
        self._is_add_mode = is_add_mode
        self._add_at = add_at
        self._cancel_add = cancel_add or (lambda: None)

    def set_delete_callback(self, on_delete) -> None:
        """
        Register callback for delete-selected action (Suppr/Backspace).
        """
        self._on_delete = on_delete

    def set_view_transform_changed_callback(self, on_changed) -> None:
        """
        Register callback when view zoom/pan changes (for overlay redraw).
        """
        self._on_view_transform_changed = on_changed

    def set_rubber_band_callbacks(self, on_started, on_finished) -> None:
        """Register callbacks around a left-button rubber-band / click select."""
        self._on_rubber_band_started = on_started
        self._on_rubber_band_finished = on_finished

    def set_activated_callback(self, on_activated) -> None:
        """Register callback when this viewport is clicked or zoomed."""
        self._on_activated = on_activated

    def capture_camera(self) -> QPointF:
        """Scene point currently shown at the viewport center."""
        return self.mapToScene(self.viewport().rect().center())

    def restore_camera(self, scene_center: QPointF) -> None:
        """Keep `scene_center` at the viewport center after a scene-rect change."""
        current = self.mapFromScene(scene_center)
        target = self.viewport().rect().center()
        self.horizontalScrollBar().setValue(
            int(round(self.horizontalScrollBar().value() + current.x() - target.x()))
        )
        self.verticalScrollBar().setValue(
            int(round(self.verticalScrollBar().value() + current.y() - target.y()))
        )

    def visible_scene_rect(self) -> QRectF:
        """Axis-aligned scene rect currently shown in this viewport."""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def fit_scene_rect(self, rect: QRectF) -> None:
        """
        Frame `rect` in the plot area (viewport minus axis bands), Y-up.

        `QGraphicsView.fitInView` uses the full viewport, then a scrollbar
        nudge for the axis bands. That nudge is clamped when the framed
        rect is almost as large as the scene (typical for pads), so the
        view ends up off-center. This fits and centers in the usable area.
        """
        if rect.width() <= 0 or rect.height() <= 0:
            return

        prev_size = None
        for _ in range(4):
            vp = self.viewport().rect()
            size = (vp.width(), vp.height())
            if size[0] <= 1 or size[1] <= 1:
                return
            if size == prev_size:
                break
            prev_size = size

            axis_w = float(AXIS_BAND_WIDTH)
            axis_h = float(AXIS_BAND_HEIGHT)
            usable_w = max(vp.width() - axis_w, 1.0)
            usable_h = max(vp.height() - axis_h, 1.0)

            def scale_to_fit(framed: QRectF) -> float:
                return min(
                    usable_w / max(framed.width(), 1e-9),
                    usable_h / max(framed.height(), 1e-9),
                )

            scale = scale_to_fit(rect)
            label_pad = FIT_LABEL_MARGIN_PX / max(scale, 1e-9)
            framed = rect.adjusted(-label_pad, -label_pad, label_pad, label_pad)
            scale = scale_to_fit(framed)

            self.resetTransform()
            self.scale(scale, -scale)
            target = QPointF(axis_w + usable_w / 2.0, axis_h + usable_h / 2.0)
            current = self.mapFromScene(framed.center())
            self.horizontalScrollBar().setValue(
                int(round(self.horizontalScrollBar().value() + current.x() - target.x()))
            )
            self.verticalScrollBar().setValue(
                int(round(self.verticalScrollBar().value() + current.y() - target.y()))
            )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """
        Handle mouse click: add mode, pan, or selection.
        """
        self._on_activated()
        # Middle button drag pans the view.
        if event.button() == Qt.MiddleButton:
            self._is_middle_panning = True
            self._last_pan_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        # Left button only.
        if event.button() == Qt.LeftButton:
            # In add mode, left-click creates an electrode, pad, or orientation marker.
            if self._is_add_mode():
                scene_pos = self.mapToScene(event.pos())
                self._add_at(scene_pos.x(), scene_pos.y())
                event.accept()
                return
            self._on_rubber_band_started()
            self.setRenderHint(QPainter.Antialiasing, False)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """
        While middle button is held, pan by translating scrollbars.
        """
        if self._is_middle_panning and self._last_pan_pos is not None:
            delta = event.pos() - self._last_pan_pos
            self._last_pan_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """
        End middle-button pan, then let Qt finish the click (selection).
        """
        if event.button() == Qt.MiddleButton and self._is_middle_panning:
            self._is_middle_panning = False
            self._last_pan_pos = None
            self.unsetCursor()
            event.accept()
            return

        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton:
            self.setRenderHint(QPainter.Antialiasing, True)
            self._on_rubber_band_finished()
            self.viewport().update()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        """
        Handle Suppr/Backspace to delete selected electrodes when view has focus.
        """
        if event.key() == Qt.Key_Escape and self._is_add_mode():
            self._cancel_add()
            event.accept()
            return
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
        self._on_activated()
        # event.position() is Qt6; event.pos() fallback for older APIs.
        try:
            mouse_pos = event.position().toPoint()
        except AttributeError:
            mouse_pos = event.pos()

        # Remember which scene point is under the cursor before scaling.
        scene_pos_before = self.mapToScene(mouse_pos)
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            delta_y = event.pixelDelta().y()
        if delta_y == 0:
            event.ignore()
            return
        factor = clamp_zoom_factor(
            abs(self.transform().m11()),
            1.15 if delta_y > 0 else 1 / 1.15,
        )
        if factor is None:
            event.accept()
            return
        if factor < 1.0:
            # Zoom-out shows more scene; grow sceneRect first so scrollbars
            # are not clamped and the cursor-centered adjust can run.
            visible = self.visible_scene_rect()
            inv = 1.0 / factor
            extra_w = visible.width() * inv
            extra_h = visible.height() * inv
            grow_scene_rect_to_include(
                self.scene(),
                visible.adjusted(-extra_w, -extra_h, extra_w, extra_h),
            )
        self.scale(factor, factor)

        # After scale, that scene point moved in viewport; adjust scrollbars
        # so it stays under the cursor (zoom appears centered on mouse).
        viewport_pos_after = self.mapFromScene(scene_pos_before)
        delta_view = viewport_pos_after - mouse_pos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + delta_view.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + delta_view.y())

        # Relayout this camera's label copies only; the other view is unchanged.
        self._on_view_transform_changed(self)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # type: ignore[override]
        """
        Force overlay repaint when panning with scrollbars.

        Without this, axis bands would stay fixed during scroll.
        """
        super().scrollContentsBy(dx, dy)
        self.viewport().update()
        if dx or dy:
            self._on_view_transform_changed(self)

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
        xs, ys = scene.get_axes(self)  # type: ignore[attr-defined]
        if not xs and not ys:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        grid_pen = QPen(QColor("#3b4f66"))
        grid_pen.setWidthF(0)  # Cosmetic width: 1 logical pixel.
        painter.setPen(grid_pen)
        map_x = lambda value: self.mapFromScene(value, 0).x()
        map_y = lambda value: self.mapFromScene(0, value).y()
        for x in subsample_axis_positions(
            xs, map_x, GRID_MIN_LINE_SPACING_PX, rect.left(), rect.right()
        ):
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in subsample_axis_positions(
            ys, map_y, GRID_MIN_LINE_SPACING_PX, rect.top(), rect.bottom()
        ):
            painter.drawLine(rect.left(), y, rect.right(), y)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect) -> None:  # type: ignore[override]
        """
        Draw fixed overlays (axis bands + numeric ticks).

        In viewport coordinates to stay fixed on screen during zoom/pan.
        """
        super().drawForeground(painter, rect)
        scene = self.scene()
        if scene is None or not hasattr(scene, "get_axes"):
            return

        self._draw_pad_links(painter, rect)
        self._draw_contact_labels(painter)

        xs, ys = scene.get_axes(self)  # type: ignore[attr-defined]
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
        for x in subsample_axis_positions(
            xs, lambda value: self.mapFromScene(value, 0).x(), min_px_spacing, None, None
        ):
            px = self.mapFromScene(x, 0).x()
            if px < axis_w or px > vp.width() - 2:
                continue
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

    def _draw_contact_labels(self, painter: QPainter) -> None:
        """Paint map text in viewport pixels for visible contacts only.

        Labels are not QGraphicsItems: thousands of ItemIgnoresTransformations
        children made rubber-band selection and pan unusable.
        """
        scale = abs(self.transform().m11())
        if scale <= 0:
            return
        contacts = [
            item
            for item in self.items(self.viewport().rect())
            if getattr(item, "_label_half_extents", None) is not None
        ]
        if not contacts:
            return
        font = self._map_label_font
        metrics = QFontMetrics(font)
        flags = int(Qt.AlignLeft | Qt.AlignTop | Qt.TextDontClip)
        scene = self.scene()
        contrast_ok = bool(scene is None or getattr(scene, "has_orientation_markers", False))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.resetTransform()
        painter.setFont(font)
        painter.setBrush(Qt.NoBrush)
        for item in contacts:
            parts = overlay_label_parts(item, scale, metrics)
            if not parts:
                continue
            for part in parts:
                origin = self.mapFromScene(item.mapToScene(part.item_pos))
                painter.save()
                painter.translate(origin.x(), origin.y())
                if part.degrees:
                    painter.rotate(part.degrees)
                if part.contrast and contrast_ok:
                    painter.setCompositionMode(QPainter.CompositionMode_Difference)
                    painter.setPen(QColor("#ffffff"))
                elif part.is_center:
                    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                    painter.setPen(
                        getattr(item, "_label_center_color", QColor("#e9edf2"))
                    )
                else:
                    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
                    painter.setPen(
                        getattr(item, "_label_below_color", QColor("#ffffff"))
                    )
                painter.drawText(QRectF(0.0, 0.0, part.pixel_w, part.pixel_h), flags, part.text)
                painter.restore()
        painter.restore()

    def _draw_pad_links(self, painter: QPainter, rect) -> None:
        """Dashed pad-to-electrode lines, only in the pad mapping camera."""
        scene = self.scene()
        if scene is None or self is not getattr(scene, "pad_map_view", None):
            return
        getter = getattr(scene, "pad_link_segments", None)
        if getter is None:
            return
        segments = getter()
        if not segments:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(QColor("#9fb3c8"), 1, Qt.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        left, right, top, bottom = rect.left(), rect.right(), rect.top(), rect.bottom()
        for x1, y1, x2, y2 in segments:
            if max(x1, x2) < left or min(x1, x2) > right:
                continue
            if max(y1, y2) < top or min(y1, y2) > bottom:
                continue
            painter.drawLine(x1, y1, x2, y2)
        painter.restore()
