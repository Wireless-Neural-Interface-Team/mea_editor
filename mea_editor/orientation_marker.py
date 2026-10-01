"""
Shared data structures for orientation markers.

An orientation marker is a fabrication / layout fiducial used to read the
orientation of the array. It is not an electrode or a pad, is not linked to
either, and is not a SpikeInterface contact.

Geometry uses the same SpikeInterface shapes as electrodes and pads
(circle, square, rect). It is persisted in native JSON and written to the
Excel workbook. SpikeInterface export omits it. Map-label side
and rotation are native JSON only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contact_shape import CONTACT_SHAPES
from .electrode import DEFAULT_LABEL_ORIENTATION, DEFAULT_LABEL_POSITION

DEFAULT_MARKER_RADIUS = 10.0
DEFAULT_MARKER_SHAPE = "square"
MARKER_SHAPES = CONTACT_SHAPES


@dataclass(frozen=True, slots=True)
class OrientationMarkerSnapshot:
    """Immutable copy of editable orientation-marker fields for undo/redo."""

    x: float
    y: float
    radius: float
    height: float
    shape: str
    label_position: str
    label_orientation: int


@dataclass(slots=True)
class OrientationMarker:
    """
    In-memory data model for one orientation marker.

    Field groups:
    - identity: marker_id (editor-assigned, like electrode eid / pad_id)
    - geometry: x, y, radius, height, shape

    Notes:
    - shape is a SpikeInterface contact shape: circle, square, or rect.
    - radius is the stored half-extent along X (true radius for a circle).
    - height is the stored half-extent along Y for rect; 0 means use radius.
    - There is no electrode or pad association.
    - No map label is drawn. label_position and label_orientation are kept
      for native JSON compatibility with older files; they are omitted from
      SpikeInterface and XLSX.
    """

    marker_id: int
    x: float
    y: float
    radius: float = DEFAULT_MARKER_RADIUS
    height: float = 0.0
    shape: str = DEFAULT_MARKER_SHAPE
    label_position: str = DEFAULT_LABEL_POSITION
    label_orientation: int = DEFAULT_LABEL_ORIENTATION

    def snapshot(self) -> OrientationMarkerSnapshot:
        """Return an immutable copy of editable fields."""
        return OrientationMarkerSnapshot(
            x=self.x,
            y=self.y,
            radius=self.radius,
            height=self.height,
            shape=self.shape,
            label_position=self.label_position,
            label_orientation=self.label_orientation,
        )

    def restore(self, snap: OrientationMarkerSnapshot) -> None:
        """Apply a snapshot onto this model (keeps marker_id)."""
        self.x = snap.x
        self.y = snap.y
        self.radius = snap.radius
        self.height = snap.height
        self.shape = snap.shape
        self.label_position = snap.label_position
        self.label_orientation = snap.label_orientation

    @classmethod
    def from_snapshot(cls, marker_id: int, snap: OrientationMarkerSnapshot) -> OrientationMarker:
        """Build a new marker from a snapshot."""
        return cls(
            marker_id=marker_id,
            x=snap.x,
            y=snap.y,
            radius=snap.radius,
            height=snap.height,
            shape=snap.shape,
            label_position=snap.label_position,
            label_orientation=snap.label_orientation,
        )
