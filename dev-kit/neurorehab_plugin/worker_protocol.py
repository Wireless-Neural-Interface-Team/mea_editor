"""JSON protocol between the GUI host and a plugin worker subprocess.

Provides (de)serialization helpers converting the immutable dataclasses in
:mod:`neurorehab_plugin.context` to and from plain JSON-safe dicts, so the
host application and the plugin worker subprocess (see
:mod:`neurorehab_plugin.worker_main`) can exchange a
:class:`~neurorehab_plugin.context.PluginContext` — and therefore the
record access scope it encodes — over their line-delimited JSON stdio
protocol.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from neurorehab_plugin.context import PluginContext, PluginRecord


def _path_to_json(value: Path | None) -> str | None:
    """Convert a ``Path`` to its string form for JSON encoding, or ``None``."""
    if value is None:
        return None
    return str(value)


def _path_from_json(value: str | None) -> Path | None:
    """Convert a JSON string back into a ``Path``, or ``None`` if falsy."""
    if not value:
        return None
    return Path(value)


def serialize_record(record: PluginRecord) -> dict[str, Any]:
    """Convert a :class:`PluginRecord` into a plain JSON-safe dict.

    Args:
        record: The record to serialize.

    Returns:
        A dict with the record's fields, safe to pass through ``json.dumps``.
    """
    return {
        "id": int(record.id),
        "entity_id": int(record.entity_id),
        "display_label": str(record.display_label),
        "data": dict(record.data or {}),
        "variant_id": int(record.variant_id) if record.variant_id is not None else None,
        "variant_key": str(record.variant_key or ""),
        "variant_label": str(record.variant_label or ""),
    }


def deserialize_record(payload: dict[str, Any]) -> PluginRecord:
    """Reconstruct a :class:`PluginRecord` from a dict produced by :func:`serialize_record`.

    Args:
        payload: Dict with (at least) ``id``, ``entity_id`` keys and
            optionally ``display_label``, ``data``, ``variant_id``,
            ``variant_key``, ``variant_label``.

    Returns:
        The reconstructed :class:`PluginRecord`.
    """
    variant_id = payload.get("variant_id")
    return PluginRecord(
        id=int(payload["id"]),
        entity_id=int(payload["entity_id"]),
        display_label=str(payload.get("display_label") or ""),
        data=dict(payload.get("data") or {}),
        variant_id=int(variant_id) if variant_id is not None else None,
        variant_key=str(payload.get("variant_key") or ""),
        variant_label=str(payload.get("variant_label") or ""),
    )


def serialize_context(context: PluginContext) -> dict[str, Any]:
    """Convert a :class:`PluginContext` into a plain JSON-safe dict.

    This is how the record access scope (``selected_records``, and
    therefore ``selected_record_ids``/``allowed_record_ids``) is
    transmitted from the host application to the plugin worker subprocess
    for a given invocation.

    Args:
        context: The context to serialize.

    Returns:
        A dict with the context's fields, safe to pass through ``json.dumps``.
    """
    return {
        "entity_id": int(context.entity_id),
        "entity_key": str(context.entity_key),
        "entity_label": str(context.entity_label),
        "entity_label_plural": str(context.entity_label_plural),
        "username": str(context.username),
        "selected_records": [
            serialize_record(record) for record in context.selected_records
        ],
        "applicable_records": [
            serialize_record(record) for record in context.applicable_records
        ],
        "primary_variant_key": str(context.primary_variant_key or ""),
        "primary_variant_label": str(context.primary_variant_label or ""),
        "plugin_id": str(context.plugin_id or ""),
        "plugin_root": _path_to_json(context.plugin_root),
        "plugin_python": _path_to_json(context.plugin_python),
    }


def deserialize_context(payload: dict[str, Any]) -> PluginContext:
    """Reconstruct a :class:`PluginContext` from a dict produced by :func:`serialize_context`.

    Used by the plugin worker (see
    :meth:`~neurorehab_plugin.worker_main.PluginWorkerRuntime._api`) to
    rebuild the exact record access scope the host granted for a given
    request, before constructing a :class:`~neurorehab_plugin.api.PluginApi`.

    Args:
        payload: Dict with (at least) ``entity_id``, ``entity_key``,
            ``entity_label``, ``entity_label_plural`` keys, as produced by
            :func:`serialize_context`.

    Returns:
        The reconstructed :class:`PluginContext`.
    """
    return PluginContext(
        entity_id=int(payload["entity_id"]),
        entity_key=str(payload["entity_key"]),
        entity_label=str(payload["entity_label"]),
        entity_label_plural=str(payload["entity_label_plural"]),
        username=str(payload.get("username") or ""),
        selected_records=[
            deserialize_record(item)
            for item in list(payload.get("selected_records") or [])
        ],
        applicable_records=[
            deserialize_record(item)
            for item in list(payload.get("applicable_records") or [])
        ],
        primary_variant_key=str(payload.get("primary_variant_key") or ""),
        primary_variant_label=str(payload.get("primary_variant_label") or ""),
        plugin_id=str(payload.get("plugin_id") or ""),
        plugin_root=_path_from_json(payload.get("plugin_root")) or Path("."),
        plugin_python=_path_from_json(payload.get("plugin_python")),
    )


def json_ready(value: Any) -> Any:
    """Recursively convert a value into a JSON-serializable form.

    Handles dataclass instances (via ``dataclasses.asdict``, then
    recursively normalized), ``Path`` objects (converted to ``str``),
    dicts, and lists/tuples; any other value is returned unchanged.

    Args:
        value: The value to normalize.

    Returns:
        A JSON-serializable equivalent of ``value``.
    """
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value
