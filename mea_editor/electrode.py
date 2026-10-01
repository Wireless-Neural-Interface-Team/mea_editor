"""
Shared data structures for the electrode array editor.

This module intentionally stays minimal:
- one dataclass (`Electrode`) used by both GUI and I/O layers,
- a frozen snapshot type for undo/redo,
- no Qt dependency,
- no file-format dependency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

from .contact_shape import CONTACT_SHAPES, DEFAULT_ELECTRODE_SHAPE


DEFAULT_RADIUS = 12.0
DEFAULT_INTAN_ID = "A-000"
DEFAULT_MANUFACTURER_ID = ""
DEFAULT_SHAPE = DEFAULT_ELECTRODE_SHAPE
ELECTRODE_SHAPES = CONTACT_SHAPES
DEFAULT_PLANE_AXIS = (1.0, 0.0, 0.0, 1.0)
BUILTIN_ATTRIBUTE_KEYS = ("potentiostat_id", "intan_id", "manufacturer_id", "shank_id")
DEFAULT_MAP_LABEL_KEYS = ("potentiostat_id", "intan_id", "shank_id")
_CENTER_MAP_LABEL_KEYS = frozenset({"potentiostat_id", "shank_id"})
LABEL_POSITIONS = ("above", "below", "left", "right")
DEFAULT_LABEL_POSITION = "below"
LABEL_POSITION_GAP = 4.0
LABEL_POSITION_CAPTIONS = {
    "above": "Above",
    "below": "Below",
    "left": "Left",
    "right": "Right",
}
LABEL_ORIENTATIONS = (0, 90, 180, 270)
DEFAULT_LABEL_ORIENTATION = 0
LABEL_ORIENTATION_CAPTIONS = {
    0: "0°",
    90: "90°",
    180: "180°",
    270: "270°",
}
_LABEL_ORIENTATION_ALIASES = {
    "horizontal": 0,
    "vertical": 90,
}

AttrValue = str | int | float


def normalize_label_position(value: object) -> str:
    """Return a supported map-label side, or `below` when the value is unknown."""
    text = str(value).strip().lower() if value is not None else ""
    if text in LABEL_POSITIONS:
        return text
    return DEFAULT_LABEL_POSITION


def normalize_label_orientation(value: object) -> int:
    """Return 0 / 90 / 180 / 270 degrees, or 0 when the value is unknown."""
    if value is None or isinstance(value, bool):
        return DEFAULT_LABEL_ORIENTATION
    if isinstance(value, (int, float)):
        degrees = int(round(float(value))) % 360
        return degrees if degrees in LABEL_ORIENTATIONS else DEFAULT_LABEL_ORIENTATION
    text = str(value).strip().lower().replace("°", "")
    text = text.replace("degrees", "").replace("deg", "").strip()
    if text in _LABEL_ORIENTATION_ALIASES:
        return _LABEL_ORIENTATION_ALIASES[text]
    try:
        degrees = int(round(float(text))) % 360
    except (TypeError, ValueError):
        return DEFAULT_LABEL_ORIENTATION
    return degrees if degrees in LABEL_ORIENTATIONS else DEFAULT_LABEL_ORIENTATION


def rotated_label_item_aabb(
    text_w: float,
    text_h: float,
    orientation: int,
) -> tuple[float, float, float, float]:
    """
    Axis-aligned bounds of rotated map text in item coordinates (Y-up).

    Rotation is clockwise in screen space (ItemIgnoresTransformations).
    Returns (min_x, min_y, max_x, max_y) relative to the unrotated top-left.
    """
    degrees = normalize_label_orientation(orientation)
    rad = math.radians(degrees)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    xs: list[float] = []
    ys: list[float] = []
    for lx, ly in ((0.0, 0.0), (text_w, 0.0), (0.0, text_h), (text_w, text_h)):
        device_x = cos_a * lx - sin_a * ly
        device_y = sin_a * lx + cos_a * ly
        xs.append(device_x)
        ys.append(-device_y)
    return min(xs), min(ys), max(xs), max(ys)


def outside_label_gap(
    position: str,
    orientation: int = DEFAULT_LABEL_ORIENTATION,
    gap: float = LABEL_POSITION_GAP,
    space_w: float = 0.0,
) -> float:
    """
    Distance from the contact to the outside label AABB.

    Adds one space-character width when the text's long axis is parallel to
    the contact edge it sits against: left/right at 0° or 180°, and
    above/below at 90° or 270°.
    """
    side = normalize_label_position(position)
    degrees = normalize_label_orientation(orientation)
    extra = 0.0
    if space_w:
        if side in ("left", "right") and degrees in (0, 180):
            extra = space_w
        elif side in ("above", "below") and degrees in (90, 270):
            extra = space_w
    return gap + extra


def map_label_item_pos(
    position: str,
    half_x: float,
    half_y: float,
    text_w: float,
    text_h: float,
    gap: float = LABEL_POSITION_GAP,
    orientation: int = DEFAULT_LABEL_ORIENTATION,
    space_w: float = 0.0,
) -> tuple[float, float]:
    """
    Top-left of an outside map label in item coordinates.

    Scene Y grows up. Labels use ItemIgnoresTransformations, so unrotated text
    extends down on screen from this origin (toward -Y in the scene).
    `orientation` is clockwise degrees in screen space (0 / 90 / 180 / 270).
    `space_w` is the width of one space in the same units as `text_w`.
    """
    min_x, min_y, max_x, max_y = rotated_label_item_aabb(text_w, text_h, orientation)
    side = normalize_label_position(position)
    gap = outside_label_gap(side, orientation, gap, space_w)
    if side == "above":
        return (-(min_x + max_x) / 2.0, half_y + gap - min_y)
    if side == "left":
        return (-(half_x + gap) - max_x, -(min_y + max_y) / 2.0)
    if side == "right":
        return (half_x + gap - min_x, -(min_y + max_y) / 2.0)
    return (-(min_x + max_x) / 2.0, -(half_y + gap) - max_y)


def electrode_center_label(potentiostat_id: int, shank_id: str) -> str:
    """
    Compact identity used outside map views (combo boxes, etc.).

    Format:
    - with shank: "<shank>-<potentiostat 3 digits>" (example: "1-002")
    - without shank: "<potentiostat 3 digits>"
    """
    potentiostat = f"{int(potentiostat_id):03d}"
    shank = str(shank_id).strip()
    return f"{shank}-{potentiostat}" if shank else potentiostat


def format_map_label_value(key: str, value: AttrValue) -> str:
    """Format one electrode attribute for a map-view label."""
    if key == "potentiostat_id":
        try:
            return f"{int(value):03d}"
        except (TypeError, ValueError):
            return str(value).strip()
    return str(value).strip()


def electrode_map_view_labels(
    values: dict[str, AttrValue],
    visible_keys: Iterable[str] | None = None,
    schema_keys: Iterable[str] | None = None,
) -> tuple[str, str]:
    """
    Labels drawn on electrode and pad map items.

    Returns (center_text, below_text):
    - center: shank and/or potentiostat when those IDs are visible
    - below: other visible IDs in schema order (INTAN, manufacturer, extras)
    """
    visible = set(DEFAULT_MAP_LABEL_KEYS if visible_keys is None else visible_keys)
    order = list(BUILTIN_ATTRIBUTE_KEYS if schema_keys is None else schema_keys)
    for key in visible:
        if key not in order:
            order.append(key)

    center_parts: list[str] = []
    if "shank_id" in visible:
        shank = format_map_label_value("shank_id", values.get("shank_id", ""))
        if shank:
            center_parts.append(shank)
    if "potentiostat_id" in visible:
        center_parts.append(
            format_map_label_value("potentiostat_id", values.get("potentiostat_id", 0))
        )
    center = "-".join(center_parts)

    below_parts: list[str] = []
    for key in order:
        if key not in visible or key in _CENTER_MAP_LABEL_KEYS:
            continue
        text = format_map_label_value(key, values.get(key, ""))
        if not text and key == "intan_id":
            text = "?"
        if text:
            below_parts.append(text)
    return center, "\n".join(below_parts)


@dataclass(frozen=True, slots=True)
class ElectrodeSnapshot:
    """Immutable copy of editable electrode fields for undo/redo."""

    x: float
    y: float
    radius: float
    height: float
    potentiostat_id: int
    intan_id: str
    manufacturer_id: str
    contact_plane_axis: tuple[float, float, float, float]
    shank_id: str
    shape: str
    label_position: str
    label_orientation: int
    extra: dict[str, AttrValue]


@dataclass(slots=True)
class Electrode:
    """
    In-memory data model for one electrode/contact.

    Field groups:
    - geometry: x, y, radius, height
    - identification: potentiostat_id, intan_id, manufacturer_id, shank_id
    - extra attributes: file-defined key/value map (`extra`)
    - orientation metadata: contact_plane_axis (x0, x1, y0, y1)
    - editor display: label_position (above / below / left / right) and
      label_orientation (0 / 90 / 180 / 270 degrees)
    - editor state: duplicate flags

    Notes:
    - shape is a SpikeInterface contact shape: circle, square, or rect.
    - radius is the stored half-extent along X (true radius for a circle).
    - height is the stored half-extent along Y for rect; 0 means use radius.
    - Duplicate flags are computed by the editor and drive display color.
    - Built-in identifiers are always present; extra attributes live in `extra`
      and follow the file-level schema.
    - label_position and label_orientation are editor display only (native
      JSON); they are omitted from SpikeInterface and XLSX exports.
    """

    eid: int
    x: float
    y: float
    radius: float = DEFAULT_RADIUS
    height: float = 0.0
    potentiostat_id: int = 0
    intan_id: str = DEFAULT_INTAN_ID
    manufacturer_id: str = DEFAULT_MANUFACTURER_ID
    contact_plane_axis: tuple[float, float, float, float] = DEFAULT_PLANE_AXIS
    shank_id: str = ""
    shape: str = DEFAULT_SHAPE
    label_position: str = DEFAULT_LABEL_POSITION
    label_orientation: int = DEFAULT_LABEL_ORIENTATION
    extra: dict[str, AttrValue] = field(default_factory=dict)
    has_potentiostat_duplicate: bool = False
    has_intan_duplicate: bool = False
    has_manufacturer_duplicate: bool = False
    has_extra_duplicate: bool = False
    has_missing_pad: bool = False
    has_multiple_pads: bool = False

    def snapshot(self) -> ElectrodeSnapshot:
        """Return an immutable copy of editable fields."""
        return ElectrodeSnapshot(
            x=self.x,
            y=self.y,
            radius=self.radius,
            height=self.height,
            potentiostat_id=self.potentiostat_id,
            intan_id=self.intan_id,
            manufacturer_id=self.manufacturer_id,
            contact_plane_axis=self.contact_plane_axis,
            shank_id=self.shank_id,
            shape=self.shape,
            label_position=self.label_position,
            label_orientation=self.label_orientation,
            extra=dict(self.extra),
        )

    def restore(self, snap: ElectrodeSnapshot) -> None:
        """Apply a snapshot onto this model (keeps eid and duplicate flags)."""
        self.x = snap.x
        self.y = snap.y
        self.radius = snap.radius
        self.height = snap.height
        self.potentiostat_id = snap.potentiostat_id
        self.intan_id = snap.intan_id
        self.manufacturer_id = snap.manufacturer_id
        self.contact_plane_axis = snap.contact_plane_axis
        self.shank_id = snap.shank_id
        self.shape = snap.shape
        self.label_position = snap.label_position
        self.label_orientation = snap.label_orientation
        self.extra = dict(snap.extra)

    @classmethod
    def from_snapshot(cls, eid: int, snap: ElectrodeSnapshot) -> Electrode:
        """Build a new electrode from a snapshot."""
        return cls(
            eid=eid,
            x=snap.x,
            y=snap.y,
            radius=snap.radius,
            height=snap.height,
            potentiostat_id=snap.potentiostat_id,
            intan_id=snap.intan_id,
            manufacturer_id=snap.manufacturer_id,
            contact_plane_axis=snap.contact_plane_axis,
            shank_id=snap.shank_id,
            shape=snap.shape,
            label_position=snap.label_position,
            label_orientation=snap.label_orientation,
            extra=dict(snap.extra),
        )

    def get_attribute(self, key: str) -> AttrValue:
        """Read a built-in identifier or an extra attribute."""
        if key in BUILTIN_ATTRIBUTE_KEYS:
            return getattr(self, key)
        return self.extra.get(key, "")

    def set_attribute(self, key: str, value: AttrValue) -> None:
        """Write a built-in identifier or an extra attribute."""
        if key in BUILTIN_ATTRIBUTE_KEYS:
            setattr(self, key, value)
        else:
            self.extra[key] = value

    def map_center_label(self) -> str:
        """Compact identity: shank + potentiostat ID (combo boxes, etc.)."""
        return electrode_center_label(self.potentiostat_id, self.shank_id)

    def map_view_labels(
        self,
        visible_keys: Iterable[str] | None = None,
        schema_keys: Iterable[str] | None = None,
    ) -> tuple[str, str]:
        """Map-view labels from the visible electrode IDs."""
        order = list(BUILTIN_ATTRIBUTE_KEYS if schema_keys is None else schema_keys)
        keys = DEFAULT_MAP_LABEL_KEYS if visible_keys is None else visible_keys
        values: dict[str, AttrValue] = {key: self.get_attribute(key) for key in order}
        for key in keys:
            if key not in values:
                values[key] = self.get_attribute(key)
        return electrode_map_view_labels(values, keys, order)

    def has_any_duplicate(self) -> bool:
        """True if a pairing or identifier condition should highlight this electrode."""
        return (
            self.has_potentiostat_duplicate
            or self.has_intan_duplicate
            or self.has_manufacturer_duplicate
            or self.has_extra_duplicate
            or self.has_missing_pad
            or self.has_multiple_pads
        )
