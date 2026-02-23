from __future__ import annotations

import json
from typing import Any

import numpy as np

from .electrode_array_types import Electrode

"""
I/O layer for the electrode array editor.

Supported inputs:
1) probeinterface JSON (preferred)
2) legacy custom editor JSON

Output:
- probeinterface JSON only (for compatibility with the rest of the pipeline).
"""

DEFAULT_RADIUS = 12.0
MIN_RADIUS = 0.001
DEFAULT_CONTACT_ID = "A-000"
DEFAULT_SHAPE = "circle"
DEFAULT_PLANE_AXIS = (1.0, 0.0, 0.0, 1.0)
DEFAULT_UNITS = "um"


def _parse_contact_plane_axis(raw_value) -> tuple[float, float, float, float]:
    """
    Parse contact plane axis from generic input (list/tuple).

    Expected order: (plane_axis_x_0, plane_axis_x_1, plane_axis_y_0, plane_axis_y_1).
    Returns DEFAULT_PLANE_AXIS on invalid input (type, length, conversion).

    Args:
        raw_value: List or tuple of 4 numeric values.

    Returns:
        Tuple (x0, x1, y0, y1) or DEFAULT_PLANE_AXIS.
    """
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 4:
        return DEFAULT_PLANE_AXIS
    try:
        x0, x1, y0, y1 = (float(v) for v in raw_value)
    except (TypeError, ValueError):
        return DEFAULT_PLANE_AXIS
    return (x0, x1, y0, y1)


def _is_valid_value(value: Any) -> bool:
    """
    Check if value is valid (non-NaN).

    NaN != NaN in Python, so value == value returns False for NaN.
    Compatible with DataFrame scalar values.
    """
    return value == value


def load_electrodes_from_file(path: str) -> tuple[list[Electrode], str]:
    """
    Load electrodes from JSON file.

    Supported formats:
    1) probeinterface JSON (preferred)
    2) legacy custom editor JSON

    Args:
        path: Path to JSON file.

    Returns:
        (models, si_units): list of Electrode and distance unit.

    Raises:
        ValueError: unsupported format, missing dependency, or empty content.
    """
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # Format 1: probeinterface JSON (official parser).
    if (
        isinstance(data, dict)
        and data.get("specification") == "probeinterface"
        and isinstance(data.get("probes"), list)
        and data["probes"]
    ):
        try:
            import probeinterface as ProbeI
        except Exception as exc:
            raise ValueError("probeinterface is required to read probeinterface JSON files.") from exc

        # Official parser to stay robust to format evolution.
        probe = ProbeI.read_probeinterface(path)
        df = probe.to_dataframe(complete=True)
        si_units = str(getattr(probe, "si_units", DEFAULT_UNITS) or DEFAULT_UNITS)

        models: list[Electrode] = []
        for i, row in df.reset_index(drop=True).iterrows():
            # i = row index; row = Series with columns x, y, radius, etc.
            shape = DEFAULT_SHAPE
            radius = DEFAULT_RADIUS
            # Use radius only when column exists and value is valid.
            if "radius" in row and _is_valid_value(row["radius"]):
                radius = float(row["radius"])
            elif "width" in row or "height" in row:
                # Backward compatibility for files that carried square dimensions.
                width = float(row["width"]) if "width" in row and _is_valid_value(row["width"]) else 24.0
                height = float(row["height"]) if "height" in row and _is_valid_value(row["height"]) else 24.0
                radius = max(width, height) / 2.0

            channel_index = i
            if "device_channel_indices" in row and _is_valid_value(row["device_channel_indices"]):
                channel_index = int(row["device_channel_indices"])

            contact_id = DEFAULT_CONTACT_ID
            if "contact_ids" in row and _is_valid_value(row["contact_ids"]):
                contact_id = str(row["contact_ids"])

            shank_id = ""
            if "shank_ids" in row and _is_valid_value(row["shank_ids"]):
                shank_id = str(row["shank_ids"])

            plane_axis_x_0, plane_axis_x_1, plane_axis_y_0, plane_axis_y_1 = DEFAULT_PLANE_AXIS
            if "plane_axis_x_0" in row and _is_valid_value(row["plane_axis_x_0"]):
                plane_axis_x_0 = float(row["plane_axis_x_0"])
            if "plane_axis_x_1" in row and _is_valid_value(row["plane_axis_x_1"]):
                plane_axis_x_1 = float(row["plane_axis_x_1"])
            if "plane_axis_y_0" in row and _is_valid_value(row["plane_axis_y_0"]):
                plane_axis_y_0 = float(row["plane_axis_y_0"])
            if "plane_axis_y_1" in row and _is_valid_value(row["plane_axis_y_1"]):
                plane_axis_y_1 = float(row["plane_axis_y_1"])

            models.append(
                Electrode(
                    eid=i,
                    x=float(row["x"]),
                    y=float(row["y"]),
                    radius=max(radius, MIN_RADIUS),
                    enabled=True,
                    channel_index=channel_index,
                    contact_id=contact_id,
                    contact_plane_axis=(plane_axis_x_0, plane_axis_x_1, plane_axis_y_0, plane_axis_y_1),
                    shank_id=shank_id,
                    shape=shape,
                )
            )

        if not models:
            raise ValueError("No contacts found in probeinterface file.")
        return models, si_units

    # Format 2: legacy editor custom JSON.
    if isinstance(data, dict) and isinstance(data.get("electrodes"), list):
        si_units = str(data.get("si_units", DEFAULT_UNITS))
        models: list[Electrode] = []
        for i, el in enumerate(data["electrodes"]):
            if not isinstance(el, dict):
                continue
            models.append(
                Electrode(
                    eid=int(el.get("eid", i)),
                    x=float(el.get("x", 0.0)),
                    y=float(el.get("y", 0.0)),
                    radius=max(float(el.get("radius", DEFAULT_RADIUS)), MIN_RADIUS),
                    enabled=bool(el.get("enabled", True)),
                    channel_index=int(el.get("channel_index", i)),
                    contact_id=str(el.get("contact_id", DEFAULT_CONTACT_ID)),
                    contact_plane_axis=_parse_contact_plane_axis(el.get("contact_plane_axis")),
                    shank_id=str(el.get("shank_id", "")),
                    shape=DEFAULT_SHAPE,
                )
            )
        if not models:
            raise ValueError("No electrodes found in custom file.")
        return models, si_units

    raise ValueError("Unsupported file format.")


def save_electrodes_to_file(path: str, electrodes: list[Electrode], si_units: str) -> None:
    """
    Save electrodes in probeinterface JSON format.

    This function intentionally enforces probeinterface writing so saved files
    are consumable by downstream programs using `ProbeI.read_probeinterface`.
    """
    try:
        import probeinterface as ProbeI
    except Exception as exc:
        raise ValueError("probeinterface is required to save array files.") from exc

    # probeinterface expects contacts in deterministic order.
    # Sort by eid for deterministic order.
    ordered = sorted(electrodes, key=lambda m: m.eid)
    positions = np.array([[m.x, m.y] for m in ordered], dtype=float)
    shapes = ["circle" for _ in ordered]
    # shape_params: radius per contact, minimum MIN_RADIUS.
    shape_params = [{"radius": max(float(m.radius), MIN_RADIUS)} for m in ordered]
    plane_axes = np.array(
        [
            [
                [float(m.contact_plane_axis[0]), float(m.contact_plane_axis[1])],
                [float(m.contact_plane_axis[2]), float(m.contact_plane_axis[3])],
            ]
            for m in ordered
        ],
        dtype=float,
    )

    # Create 2D probe and assign contacts.
    probe = ProbeI.Probe(ndim=2, si_units=(si_units or DEFAULT_UNITS))
    probe.set_contacts(positions=positions, shapes=shapes, shape_params=shape_params, plane_axes=plane_axes)
    device_channel_indices = np.array([int(m.channel_index) for m in ordered], dtype=int)
    contact_ids = [str(m.contact_id) for m in ordered]
    shank_ids = [str(m.shank_id) for m in ordered]
    probe.set_device_channel_indices(device_channel_indices)
    probe.set_contact_ids(contact_ids)
    probe.set_shank_ids(shank_ids)
    ProbeI.write_probeinterface(path, probe)
