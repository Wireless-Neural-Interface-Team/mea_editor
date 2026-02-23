from __future__ import annotations

from dataclasses import dataclass

"""
Shared data structures for the electrode array editor.

This module intentionally stays minimal:
- one dataclass (`Electrode`) used by both GUI and I/O layers,
- no Qt dependency,
- no file-format dependency.

Keeping this module isolated makes state serialization and testing easier.
"""


@dataclass(slots=True)
class Electrode:
    """
    In-memory data model for one electrode/contact.

    Field groups:
    - geometry: x, y, radius (position and circle size)
    - identification: channel_index, contact_id, shank_id
    - orientation metadata: contact_plane_axis (x0,x1,y0,y1)
    - editor state: has_channel_duplicate, has_contact_duplicate, enabled

    Notes:
    - shape is currently constrained to "circle" in UI, kept as string
      for forward compatibility.
    - Duplicate flags are computed by editor and drive display color.
    """

    eid: int  # Unique editor id; electrodes dict key.
    x: float  # Center abscissa (scene coordinates).
    y: float  # Center ordinate (scene coordinates).
    radius: float = 12.0  # Circle radius in si_units.
    enabled: bool = True  # Electrode active or disabled.
    channel_index: int = 0  # Channel index (device).
    contact_id: str = "A-000"  # Contact identifier (e.g. "A-001").
    # Plane axis: (plane_axis_x_0, plane_axis_x_1, plane_axis_y_0, plane_axis_y_1).
    contact_plane_axis: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    shank_id: str = ""  # Shank identifier if applicable.
    shape: str = "circle"  # Shape: "circle" only for now.
    has_channel_duplicate: bool = False  # True if channel_index is duplicated.
    has_contact_duplicate: bool = False  # True if contact_id is duplicated.
