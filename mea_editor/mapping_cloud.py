"""One scene item that paints a whole electrode or pad map.

A QGraphicsItem per contact makes a large mapping take minutes to appear,
because Qt rebuilds its index on every insert and the window does not paint
until the last contact exists. The viewer draws every contact from this item
instead. The full editor still uses one item per contact.
"""

from __future__ import annotations

from typing import Callable

try:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen, QTransform
    from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem
except ImportError as exc:
    raise SystemExit("PySide6 is required. Install with: pip install PySide6") from exc

from .contact_shape import contact_half_extents, contact_path_box
from .view_style import cosmetic_pen, label_color_for_fill, outline_for_fill

# Same threshold as the per-contact overlay: skip text when a contact is a speck.
_LABEL_MIN_CONTACT_PX = 8.0
_ERROR_FILL = QColor("#d44b4b")
_ERROR_RIM = QColor("#ffe0e0")


class _LabelContact:
    """Stand-in for a graphics item, used only while painting map labels."""

    __slots__ = (
        "model",
        "_label_center",
        "_label_below",
        "_label_center_color",
        "_label_below_color",
        "_half",
    )

    def __init__(self, model, center: str, below: str, fill: QColor, half) -> None:
        self.model = model
        self._label_center = center
        self._label_below = below
        self._label_center_color = label_color_for_fill(fill)
        self._label_below_color = QColor("#ffffff")
        self._half = half

    def _label_half_extents(self):
        return self._half

    def mapToScene(self, point: QPointF) -> QPointF:
        """Map a point in contact-local coordinates to the scene."""
        return QPointF(self.model.x + point.x(), self.model.y + point.y())


def _identity_plane(plane) -> bool:
    if not plane or len(plane) != 4:
        return True
    return (
        abs(float(plane[0]) - 1.0) < 1e-9
        and abs(float(plane[1])) < 1e-9
        and abs(float(plane[2])) < 1e-9
        and abs(float(plane[3]) - 1.0) < 1e-9
    )


class MappingCloudItem(QGraphicsItem):
    """Paints every contact of one map (electrodes or pads) in a single item."""

    def __init__(
        self,
        models,
        *,
        shank_of: Callable,
        fill_for_shank: Callable[[str], QColor],
        label_for: Callable,
    ) -> None:
        super().__init__()
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._models = list(models)
        self._label_for = label_for
        self._max_span = 1.0
        self._bounds = QRectF(-1.0, -1.0, 2.0, 2.0)
        self._plain: list[tuple[QColor, QPen, list[tuple]]] = []
        self._rotated: list[tuple] = []
        self._build(shank_of, fill_for_shank)

    def boundingRect(self) -> QRectF:  # type: ignore[override]
        return self._bounds

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget=None) -> None:  # type: ignore[override]
        del widget
        # Antialiasing on tens of thousands of contacts is what makes the first
        # frame take seconds. Small maps keep it; large maps stay sharp enough.
        painter.setRenderHint(QPainter.Antialiasing, len(self._models) <= 2000)
        exposed = option.exposedRect
        left, right = exposed.left(), exposed.right()
        top, bottom = exposed.top(), exposed.bottom()
        for fill, pen, draws in self._plain:
            painter.setBrush(fill)
            painter.setPen(pen)
            for kind, x, y, w, h in draws:
                if x + w < left or x > right or y + h < top or y > bottom:
                    continue
                if kind == "ellipse":
                    painter.drawEllipse(x, y, w, h)
                else:
                    painter.drawRect(x, y, w, h)
        for kind, cx, cy, lx, ly, w, h, fill, pen, transform in self._rotated:
            if cx + w < left or cx - w > right or cy + h < top or cy - h > bottom:
                continue
            painter.save()
            painter.translate(cx, cy)
            painter.setTransform(transform, True)
            painter.setBrush(fill)
            painter.setPen(pen)
            if kind == "ellipse":
                painter.drawEllipse(lx, ly, w, h)
            else:
                painter.drawRect(lx, ly, w, h)
            painter.restore()

    def label_contacts(self, rect: QRectF, scale: float) -> list[_LabelContact]:
        """Label stand-ins for contacts large enough to read inside ``rect``."""
        if self._max_span * scale < _LABEL_MIN_CONTACT_PX:
            return []
        pad = self._max_span
        left = rect.left() - pad
        right = rect.right() + pad
        top = rect.top() - pad
        bottom = rect.bottom() + pad
        found: list[_LabelContact] = []
        for model, fill, half in self._label_sources:
            if model.x < left or model.x > right or model.y < top or model.y > bottom:
                continue
            center, below = self._label_for(model)
            found.append(_LabelContact(model, center, below, fill, half))
        return found

    def _build(self, shank_of: Callable, fill_for_shank: Callable[[str], QColor]) -> None:
        grouped: dict[str, tuple[QColor, QPen, list[tuple]]] = {}
        rotated: list[tuple] = []
        sources: list[tuple] = []
        min_x = min_y = 1e300
        max_x = max_y = -1e300
        max_span = 1.0
        error_pen = cosmetic_pen(_ERROR_RIM, 2.0)
        for model in self._models:
            half = contact_half_extents(model.shape, model.radius, model.height)
            span = 2.0 * max(half)
            if span > max_span:
                max_span = span
            min_x = min(min_x, model.x - half[0])
            max_x = max(max_x, model.x + half[0])
            min_y = min(min_y, model.y - half[1])
            max_y = max(max_y, model.y + half[1])
            if model.has_any_duplicate():
                fill = _ERROR_FILL
                pen = error_pen
            else:
                fill = fill_for_shank(str(shank_of(model) or ""))
                pen = None
            sources.append((model, fill, half))
            kind, lx, ly, w, h = contact_path_box(model.shape, model.radius, model.height)
            plane = getattr(model, "contact_plane_axis", None)
            if model.shape != "circle" and not _identity_plane(plane):
                transform = QTransform(plane[0], plane[1], plane[2], plane[3], 0.0, 0.0)
                rim = pen if pen is not None else cosmetic_pen(outline_for_fill(fill), 2.0)
                rotated.append((kind, model.x, model.y, lx, ly, w, h, fill, rim, transform))
                continue
            key = fill.name()
            batch = grouped.get(key)
            if batch is None:
                rim = pen if pen is not None else cosmetic_pen(outline_for_fill(fill), 2.0)
                batch = (QColor(fill), rim, [])
                grouped[key] = batch
            batch[2].append((kind, model.x + lx, model.y + ly, w, h))
        self._plain = list(grouped.values())
        self._rotated = rotated
        self._label_sources = sources
        self._max_span = max_span
        if min_x <= max_x and min_y <= max_y:
            pad = max(max_span, 1.0)
            self._bounds = QRectF(
                min_x - pad,
                min_y - pad,
                max(max_x - min_x, 1.0) + 2.0 * pad,
                max(max_y - min_y, 1.0) + 2.0 * pad,
            )
