"""Context passed from the host application to the plugin.

These immutable dataclasses describe, at the moment a plugin runs, which
table (entity) is active and which records the user has selected.

Record identifiers exposed here are **table-local** (``local_id`` / the ``#N``
shown in the UI), never the database-wide primary key. The host mints the
plugin JWT from global ids internally; :class:`~neurorehab_plugin.api.PluginApi`
sends local ids plus ``entity_id`` and the server resolves them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PluginRecord:
    """A single database record exposed to a plugin.

    Attributes:
        id: Table-local record id (``local_id``, displayed as ``#N`` in the UI).
            Not the global database primary key.
        entity_id: ID of the entity (table) this record belongs to.
        display_label: Human-readable label for the record (e.g. its name).
        data: Field values for the record, keyed by field key. Reference fields
            store table-local target ids (not global primary keys).
        variant_id: ID of the record's sub-type/variant, if the entity uses
            variants; ``None`` otherwise.
        variant_key: Machine key of the record's variant, if any.
        variant_label: Human-readable label of the record's variant, if any.
    """

    id: int
    entity_id: int
    display_label: str
    data: dict[str, Any] = field(default_factory=dict)
    variant_id: int | None = None
    variant_key: str = ""
    variant_label: str = ""


@dataclass(frozen=True)
class PluginContext:
    """Snapshot of the host application's state handed to a plugin invocation.

    This is the security boundary for record access: a plugin can only
    read data for records present in ``selected_records`` /
    ``applicable_records`` (and linked records the server expands into the
    session scope). Identifiers in this context are table-local.

    Attributes:
        entity_id: ID of the currently active entity (table).
        entity_key: Machine key of the active entity.
        entity_label: Human-readable singular label of the active entity.
        entity_label_plural: Human-readable plural label of the active entity.
        username: Name of the logged-in host user running the plugin.
        selected_records: Records currently selected by the user; this is
            the set the plugin is authorized to operate on.
        applicable_records: Subset of records the plugin's ``match_scope``
            actually applies to (may differ from ``selected_records`` when
            a plugin only targets certain sub-types/field values).
        primary_variant_key: Machine key of the dominant variant among the
            selection, if any.
        primary_variant_label: Human-readable label of the dominant variant
            among the selection, if any.
        plugin_id: Identifier of the running plugin.
        plugin_root: Filesystem path to the plugin's installation directory.
        plugin_python: Path to the plugin's dedicated Python interpreter
            (venv), if one has been provisioned.
    """

    entity_id: int
    entity_key: str
    entity_label: str
    entity_label_plural: str
    username: str
    selected_records: list[PluginRecord] = field(default_factory=list)
    applicable_records: list[PluginRecord] = field(default_factory=list)
    primary_variant_key: str = ""
    primary_variant_label: str = ""
    plugin_id: str = ""
    plugin_root: Path = field(default_factory=Path)
    plugin_python: Path | None = None

    @property
    def selected_record_ids(self) -> list[int]:
        """Table-local IDs of ``selected_records`` (``#N`` in the UI)."""
        return [int(record.id) for record in self.selected_records]

    @property
    def applicable_record_ids(self) -> list[int]:
        """Table-local IDs of ``applicable_records``."""
        return [int(record.id) for record in self.applicable_records]

    @property
    def has_selection(self) -> bool:
        """True if at least one record is selected."""
        return bool(self.selected_records)

    @property
    def has_applicable_selection(self) -> bool:
        """True if at least one selected record matches the plugin's scope."""
        return bool(self.applicable_records)
