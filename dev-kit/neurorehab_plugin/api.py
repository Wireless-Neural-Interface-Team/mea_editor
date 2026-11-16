"""Read-only client SDK exposed to plugins.

``PluginApi`` is the single entry point plugin authors use to query the
NeuroRehab database from within a plugin's ``build_ui()`` / ``run()``
callbacks. It wraps :class:`~neurorehab_plugin.transport.PluginTransport`
(an HTTP client restricted to ``/api/v1/plugin/*`` routes) and enforces two
security constraints on every remote call:

1. **Read-only enforcement**: any operation name that looks like a write
   (prefixes such as ``create_``, ``update_``, ``delete_``, ``store_``,
   ``set_``, ``save_``, ``apply_``, ``restore_``, ``run_``, ``provision_``,
   ``sync_``, ``install_``, ``upload_``, ``clear_``, ``purge_``, ``grant_``,
   ``revoke_``, ``touch_``, ``import_``, ``hard_``, ``duplicate_``,
   ``reorder_``, ``export_``, ``rename_``) or that is an explicitly blocked
   team/account lookup or automatic-action op is rejected client-side with a
   :class:`~neurorehab_plugin.errors.PluginWriteForbiddenError` before any
   network request is made.
2. **Record scoping**: every invocation automatically injects
   ``allowed_record_ids`` into the request ``kwargs`` for compatibility;
   the server ignores that client field and enforces the JWT scope instead.
   Record identifiers on this API are **table-local** (``#N``); pass
   ``entity_id`` (defaults to the active table) so the server can resolve them.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from neurorehab_plugin.context import PluginContext, PluginRecord
from neurorehab_plugin.errors import PluginWriteForbiddenError
from neurorehab_plugin.local_files import (
    file_display_name,
    open_local_path,
    pump_gui_events,
    save_bytes_to_temp,
)
from neurorehab_plugin.script_launcher import launch_plugin_script
from neurorehab_plugin.transport import PluginTransport


class _AttrHit(NamedTuple):
    field_key: str
    label_norm: str
    variant_id: int | None
    variant_key: str
    variant_label: str


def _normalize_label(label: str) -> str:
    """Case-insensitive key for an attribute or subtype label."""
    return str(label or "").strip().casefold()


def _item_dict(value: Any) -> dict[str, Any] | None:
    """Accept a schema row as a dict or as an object with the same fields."""
    if isinstance(value, dict):
        return value
    names = (
        "id",
        "field_key",
        "label",
        "field_type",
        "deleted_at",
        "variant_key",
        "variant_id",
    )
    if any(hasattr(value, name) for name in ("field_key", "variant_key", "label")):
        return {name: getattr(value, name) for name in names if hasattr(value, name)}
    return None


def _is_deleted(row: dict[str, Any]) -> bool:
    return bool(row.get("deleted_at"))


def _active_variants(schema: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in schema.get("variants") or []:
        row = _item_dict(item)
        if row is None or _is_deleted(row):
            continue
        rows.append(row)
    return rows


def _find_variant(variants: list[dict[str, Any]], token: str) -> dict[str, Any] | None:
    """Match a subtype by its key, then by its display label."""
    norm = _normalize_label(token)
    if not norm:
        return None
    by_key = [
        row
        for row in variants
        if _normalize_label(str(row.get("variant_key") or "")) == norm
    ]
    if len(by_key) == 1:
        return by_key[0]
    by_label = [
        row
        for row in variants
        if _normalize_label(str(row.get("label") or "")) == norm
    ]
    if len(by_label) == 1:
        return by_label[0]
    if len(by_key) + len(by_label) > 1:
        raise ValueError(f"Subtype {str(token).strip()!r} matches several subtypes.")
    return None


def _collect_attr_hits(schema: dict[str, Any]) -> list[_AttrHit]:
    variants_by_id: dict[int, dict[str, Any]] = {}
    for row in _active_variants(schema):
        try:
            variants_by_id[int(row["id"])] = row
        except (KeyError, TypeError, ValueError):
            continue

    hits: list[_AttrHit] = []
    seen: set[tuple[str, int | None]] = set()

    def add(row: dict[str, Any], variant: dict[str, Any] | None) -> None:
        if _is_deleted(row):
            return
        field_key = str(row.get("field_key") or "").strip()
        label_norm = _normalize_label(str(row.get("label") or ""))
        if not field_key or not label_norm:
            return
        variant_id = int(variant["id"]) if variant is not None else None
        marker = (field_key, variant_id)
        if marker in seen:
            return
        seen.add(marker)
        hits.append(
            _AttrHit(
                field_key=field_key,
                label_norm=label_norm,
                variant_id=variant_id,
                variant_key=str(variant.get("variant_key") or "") if variant else "",
                variant_label=str(variant.get("label") or "") if variant else "",
            )
        )

    for item in schema.get("fields") or []:
        row = _item_dict(item)
        if row is not None:
            add(row, None)

    raw_variant_fields = schema.get("variant_fields") or {}
    if isinstance(raw_variant_fields, dict):
        for key, items in raw_variant_fields.items():
            try:
                variant_id = int(key)
            except (TypeError, ValueError):
                continue
            variant = variants_by_id.get(variant_id)
            if variant is None:
                continue
            for item in items or []:
                row = _item_dict(item)
                if row is not None:
                    add(row, variant)
    return hits


def _attr_place(hit: _AttrHit) -> str:
    if hit.variant_label:
        return hit.variant_label
    if hit.variant_key:
        return hit.variant_key
    return "the table"


def _ambiguous_label(label: str, hits: list[_AttrHit]) -> ValueError:
    places = ", ".join(_attr_place(hit) for hit in hits)
    return ValueError(
        f"Attribute label {label!r} matches several attributes ({places}). "
        "Pass variant= with the subtype name."
    )


def _resolve_field_key_for_label(
    schema: Any,
    label: str,
    *,
    variant: str | None = None,
    fallback_variant: str | None = None,
) -> str:
    """Return the ``field_key`` of the attribute whose display label is ``label``."""
    shown = str(label or "").strip()
    norm = shown.casefold()
    if not norm:
        raise ValueError("Attribute label is required.")
    if not isinstance(schema, dict):
        schema = {}

    matches = [hit for hit in _collect_attr_hits(schema) if hit.label_norm == norm]
    variants = _active_variants(schema)

    def narrow(token: str, *, required: bool) -> list[_AttrHit]:
        found = _find_variant(variants, token)
        if found is None:
            if required:
                raise ValueError(f"Unknown subtype {str(token).strip()!r}.")
            return matches
        try:
            variant_id = int(found["id"])
        except (KeyError, TypeError, ValueError):
            if required:
                raise ValueError(f"Unknown subtype {str(token).strip()!r}.")
            return matches
        return [
            hit
            for hit in matches
            if hit.variant_id is None or hit.variant_id == variant_id
        ]

    explicit = str(variant).strip() if variant is not None else ""
    if explicit:
        narrowed = narrow(explicit, required=True)
        if len(narrowed) == 1:
            return narrowed[0].field_key
        if not narrowed:
            raise ValueError(
                f"No attribute labeled {shown!r} on subtype {explicit!r}."
            )
        raise _ambiguous_label(shown, narrowed)

    if len(matches) == 1:
        return matches[0].field_key
    if not matches:
        raise ValueError(f"No attribute labeled {shown!r}.")

    fallback = str(fallback_variant).strip() if fallback_variant else ""
    if fallback:
        narrowed = narrow(fallback, required=False)
        if len(narrowed) == 1:
            return narrowed[0].field_key
    raise _ambiguous_label(shown, matches)


def _optional_int(value: Any) -> int | None:
    """Return ``value`` as an int, or ``None`` when it is empty or not numeric."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _attachable_parent(nodes: dict[int, dict[str, Any]], folder_id: int) -> int | None:
    """Parent folder id to nest under, or ``None`` to place the folder at the root.

    A missing parent, a self-parent, or a cycle is treated as the root so the
    walk cannot recurse forever and the folder stays visible.
    """
    parent_id = nodes[folder_id]["parent_folder_id"]
    if parent_id is None or parent_id not in nodes or parent_id == folder_id:
        return None
    seen = {folder_id}
    cursor: int | None = parent_id
    while cursor is not None and cursor in nodes:
        if cursor in seen:
            return None
        seen.add(cursor)
        cursor = nodes[cursor]["parent_folder_id"]
    return parent_id


def build_folder_tree(
    folders: list[dict[str, Any]],
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    """Nest folder and file rows the way the record panel shows them.

    At every level, subfolders come first (name, then id) and files second
    (original name, then id). A file dict in the tree is the same shape
    :meth:`PluginApi.download_file`, :meth:`PluginApi.save_file_to_temp`, and
    :meth:`PluginApi.open_file` already accept.

    A folder whose parent is missing, and a file whose folder is missing, are
    placed at the root so they stay reachable.
    """
    nodes: dict[int, dict[str, Any]] = {}
    for row in folders:
        folder_id = _optional_int(row.get("id"))
        if folder_id is None:
            continue
        nodes[folder_id] = {
            "id": folder_id,
            "record_id": row.get("record_id"),
            "field_key": row.get("field_key"),
            "name": str(row.get("name") or ""),
            "relative_path": str(row.get("relative_path") or ""),
            "parent_folder_id": _optional_int(row.get("parent_folder_id")),
            "folders": [],
            "files": [],
        }

    roots: list[dict[str, Any]] = []
    for folder_id, node in nodes.items():
        parent_id = _attachable_parent(nodes, folder_id)
        if parent_id is None:
            roots.append(node)
        else:
            nodes[parent_id]["folders"].append(node)

    root_files: list[dict[str, Any]] = []
    for row in files:
        file_row = dict(row)
        file_row.pop("deleted_at", None)
        folder_id = _optional_int(file_row.get("folder_id"))
        if folder_id is not None and folder_id in nodes:
            nodes[folder_id]["files"].append(file_row)
        else:
            root_files.append(file_row)

    def _sort_level(node: dict[str, Any]) -> None:
        node["folders"].sort(
            key=lambda item: (str(item["name"]).casefold(), int(item["id"]))
        )
        node["files"].sort(
            key=lambda item: (
                str(item.get("original_name") or "").casefold(),
                int(item.get("id") or 0),
            )
        )
        for child in node["folders"]:
            _sort_level(child)

    tree: dict[str, Any] = {"folders": roots, "files": root_files}
    _sort_level(tree)
    return tree


class PluginApi:
    """Data access surface exposed to plugins — no write operations.

    Security constraints enforced by this class:

    - **Read-only**: :meth:`_assert_readonly_op` rejects any operation name
      that matches a write-like prefix or an explicitly blocked op, raising
      :class:`~neurorehab_plugin.errors.PluginWriteForbiddenError`.
    - **Scoped to allowed records**: the host-minted plugin JWT embeds the
      selection scope; the server enforces it. Record ids accepted and
      returned by this API are table-local (``local_id`` / ``#N``), never
      the global primary key.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        context: PluginContext,
    ) -> None:
        """Create the API client bound to a host session.

        Args:
            base_url: Base URL of the NeuroRehab server (scheme + host + port).
            access_token: Bearer token identifying the current host session;
                forwarded as-is to :class:`PluginTransport`.
            context: Host-provided :class:`PluginContext` describing the
                current entity, selection, and record access scope.
        """
        self._context = context
        self._transport = PluginTransport(
            base_url,
            access_token,
            plugin_id=context.plugin_id,
        )

    def close(self) -> None:
        """Close the underlying HTTP connection (idempotent)."""
        self._transport.close()

    @property
    def context(self) -> PluginContext:
        """Return the :class:`PluginContext` this client was created with."""
        return self._context

    def _entity_id(self, entity_id: int | None = None) -> int:
        return int(entity_id if entity_id is not None else self._context.entity_id)

    def _assert_readonly_op(self, op: str) -> None:
        """Raise :class:`PluginWriteForbiddenError` if ``op`` is not read-only.

        This is the primary client-side enforcement of the read-only
        security constraint: it blocks obviously write-like operation names
        (by prefix) as well as a fixed list of team/account lookup
        operations that plugins are never allowed to call, before any
        network request is issued.
        """
        normalized = str(op or "").strip()
        if normalized.startswith(
            (
                "create_",
                "update_",
                "delete_",
                "store_",
                "set_",
                "save_",
                "apply_",
                "run_",
                "restore_",
                "provision_",
                "sync_",
                "install_",
                "upload_",
                "clear_",
                "purge_",
                "grant_",
                "revoke_",
                "touch_",
                "import_",
                "hard_",
                "duplicate_",
                "copy_",
                "reorder_",
                "export_",
                "rename_",
            )
        ):
            raise PluginWriteForbiddenError(f"Write operation blocked: {normalized}")
        if normalized in {
            "list_app_users",
            "get_app_user",
            "get_app_user_by_id",
            "ensure_app_user",
            "list_active_team_members",
            "list_team_member_combo_items",
            "list_team_member_name_parts",
            "list_available_pg_login_roles",
            "username_exists",
            "find_app_user_by_name",
            "count_app_users",
            "find_entity_record_id_by_local_id",
        }:
            raise PluginWriteForbiddenError(
                f"Operation is not available to plugins: {normalized}"
            )
        if normalized in {
            "list_automation_rule_history",
            "list_automation_rule_item_history",
            "preview_automation_rule_change_kinds",
        }:
            raise PluginWriteForbiddenError(
                f"Automatic actions are not available to plugins: {normalized}"
            )

    def _invoke(self, op: str, args: list[Any] | None = None, **kwargs: Any) -> Any:
        """Call a single read-only server-side operation by name.

        The operation is validated with :meth:`_assert_readonly_op`, then
        sent as a JSON body to ``/api/v1/plugin/invoke``. ``allowed_record_ids``
        (from ``self._context.selected_record_ids``) is always merged into
        ``kwargs`` so the server restricts the operation to records the
        plugin is authorized to see, even if the caller passed its own
        ``kwargs``.

        Args:
            op: Server-side operation name (e.g. ``"get_entity_record"``).
            args: Positional arguments forwarded to the operation.
            **kwargs: Keyword arguments forwarded to the operation (merged
                with the enforced ``allowed_record_ids``).

        Returns:
            The ``result`` field of the server response, or ``None``.
        """
        normalized = str(op or "").strip()
        self._assert_readonly_op(normalized)
        body = {
            "op": normalized,
            "args": args or [],
            "kwargs": {
                **kwargs,
                "allowed_record_ids": self._context.selected_record_ids,
            },
        }
        response = self._transport.request_json(
            "POST",
            "/api/v1/plugin/invoke",
            json_body=body,
        )
        return (response or {}).get("result")

    def invoke_batch(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute multiple read-only operations in one request (max 50).

        Each item in ``calls`` is a dict with keys ``op`` (str), ``args``
        (list, optional) and ``kwargs`` (dict, optional). Every call is
        validated with :meth:`_assert_readonly_op` and has
        ``allowed_record_ids`` injected into its ``kwargs``, exactly like
        :meth:`_invoke`, before being sent to
        ``/api/v1/plugin/invoke/batch``.

        Args:
            calls: List of operation descriptors to execute server-side.

        Returns:
            List of per-call result dicts, in the same order as ``calls``.
        """
        sanitized: list[dict[str, Any]] = []
        for item in calls:
            op = str(item.get("op") or "").strip()
            self._assert_readonly_op(op)
            sanitized.append(
                {
                    "op": op,
                    "args": list(item.get("args") or []),
                    "kwargs": {
                        **dict(item.get("kwargs") or {}),
                        "allowed_record_ids": self._context.selected_record_ids,
                    },
                }
            )
        response = self._transport.request_json(
            "POST",
            "/api/v1/plugin/invoke/batch",
            json_body={"calls": sanitized},
        )
        return list((response or {}).get("results") or [])

    def list_entity_defs(self) -> list[dict[str, Any]]:
        """Return the list of entity (table) definitions visible to the plugin."""
        rows = self._invoke("list_entity_defs") or []
        return [dict(row) for row in rows]

    def get_record(
        self,
        record_id: int,
        *,
        entity_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Fetch a single record by table-local ID (``#N``).

        Args:
            record_id: Table-local id of the record to fetch.
            entity_id: Table that owns the id; defaults to the active entity.

        Returns:
            The record as a dict (``id`` is table-local), or ``None`` if not
            found or outside the plugin selection scope.
        """
        result = self._invoke(
            "get_entity_record",
            [int(record_id)],
            entity_id=self._entity_id(entity_id),
        )
        return self._normalize_record_row(result) if isinstance(result, dict) else result

    def get_field(self, record: PluginRecord | dict[str, Any], field_key: str) -> Any:
        """Read a single field value from a record's ``data`` payload.

        Args:
            record: A :class:`PluginRecord` or a raw record dict (with a
                ``"data"`` key).
            field_key: Key of the field to read within the record's data.

        Returns:
            The field value, or ``None`` if absent.
        """
        data = record.data if isinstance(record, PluginRecord) else dict(record.get("data") or {})
        return data.get(field_key)

    def get_fields(
        self,
        record: PluginRecord | dict[str, Any],
        field_keys: list[str],
    ) -> dict[str, Any]:
        """Read several field values from a record in one call.

        Args:
            record: A :class:`PluginRecord` or a raw record dict.
            field_keys: Keys of the fields to read.

        Returns:
            Dict mapping each requested field key to its value.
        """
        return {key: self.get_field(record, key) for key in field_keys}

    def list_folders(
        self,
        record_id: int,
        field_key: str,
        *,
        only_deleted: bool = False,
        entity_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List folders attached to a record's folder field.

        Args:
            record_id: Table-local id of the record owning the field.
            field_key: Key of the folder-typed field. Resolve a UI label with
                :meth:`field_key_for_label` when the key is not known.
            only_deleted: Ignored for security: plugins never see soft-deleted
                (trash) folders. Passing ``True`` is rejected by the server.
            entity_id: Table that owns ``record_id``; defaults to the active entity.

        Returns:
            List of folder metadata dicts.
        """
        rows = (
            self._invoke(
                "list_record_folders",
                [int(record_id), field_key],
                only_deleted=bool(only_deleted),
                entity_id=self._entity_id(entity_id),
            )
            or []
        )
        return [dict(row) for row in rows]

    def list_files(
        self,
        record_id: int,
        field_key: str,
        *,
        only_deleted: bool = False,
        entity_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List files attached to a record's file/folder field.

        Args:
            record_id: Table-local id of the record owning the field.
            field_key: Key of the file- or folder-typed field. Resolve a UI label
                with :meth:`field_key_for_label` when the key is not known.
            only_deleted: Ignored for security: plugins never see soft-deleted
                (trash) files. Passing ``True`` is rejected by the server.
            entity_id: Table that owns ``record_id``; defaults to the active entity.

        Returns:
            List of file metadata dicts (each usable with
            :meth:`download_file`, :meth:`save_file_to_temp`, :meth:`open_file`).
        """
        rows = (
            self._invoke(
                "list_record_files_for_field",
                [int(record_id), field_key],
                only_deleted=bool(only_deleted),
                entity_id=self._entity_id(entity_id),
            )
            or []
        )
        return [dict(row) for row in rows]

    def folder_tree(
        self,
        record_id: int,
        field_key: str,
        *,
        entity_id: int | None = None,
    ) -> dict[str, Any]:
        """Return one folder attribute as the tree shown in the record panel.

        Subfolders are nested under ``folders``. Files that sit directly in a
        folder are that folder's ``files``. Files at the root of the attribute
        are the returned dict's ``files``. Pass any of those file dicts to
        :meth:`download_file`, :meth:`save_file_to_temp`, or :meth:`open_file`.

        Read-only: this only calls :meth:`list_folders` and :meth:`list_files`.
        Trash rows stay hidden. The record must be inside the plugin scope.

        Args:
            record_id: Table-local id of the record owning the field.
            field_key: Key of the folder-typed field. Resolve a UI label with
                :meth:`field_key_for_label` when the key is not known.
            entity_id: Table that owns ``record_id``; defaults to the active entity.

        Returns:
            ``{"field_key", "folders", "files"}``. Each folder has ``id``,
            ``name``, ``relative_path``, ``parent_folder_id``, ``folders``,
            and ``files``.
        """
        folders = self.list_folders(record_id, field_key, entity_id=entity_id)
        files = self.list_files(record_id, field_key, entity_id=entity_id)
        tree = build_folder_tree(folders, files)
        tree["field_key"] = str(field_key)
        return tree

    def get_folder(self, folder_id: int) -> dict[str, Any] | None:
        """Return one folder row by id, or ``None`` if missing."""
        row = self._invoke("get_record_folder_by_id", [int(folder_id)])
        return dict(row) if row is not None else None

    def list_folders_for_field_keys(
        self,
        record_id: int,
        field_keys: list[str],
        *,
        entity_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List folders for multiple fields of the same record.

        Args:
            record_id: Table-local id of the record owning the fields.
            field_keys: Keys of the folder-typed fields to query.
            entity_id: Table that owns ``record_id``; defaults to the active entity.

        Returns:
            Concatenated list of folder metadata dicts across all fields.
        """
        rows: list[dict[str, Any]] = []
        for field_key in field_keys:
            rows.extend(self.list_folders(record_id, field_key, entity_id=entity_id))
        return rows

    def list_files_for_field_keys(
        self,
        record_id: int,
        field_keys: list[str],
        *,
        entity_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List files for multiple fields of the same record.

        Args:
            record_id: Table-local id of the record owning the fields.
            field_keys: Keys of the file-typed fields to query.
            entity_id: Table that owns ``record_id``; defaults to the active entity.

        Returns:
            Concatenated list of file metadata dicts across all fields.
        """
        rows: list[dict[str, Any]] = []
        for field_key in field_keys:
            rows.extend(self.list_files(record_id, field_key, entity_id=entity_id))
        return rows

    def list_files_for_records(
        self,
        records: list[PluginRecord],
        field_keys: list[str],
    ) -> list[tuple[PluginRecord, dict[str, Any]]]:
        """List files across several records and field keys.

        Args:
            records: Records to inspect (typically the host selection).
            field_keys: Keys of the file-typed fields to query on each record.

        Returns:
            List of ``(record, file_row)`` pairs, preserving the record each
            file belongs to.
        """
        pairs: list[tuple[PluginRecord, dict[str, Any]]] = []
        for record in records:
            for field_key in field_keys:
                for file_row in self.list_files(
                    record.id, field_key, entity_id=record.entity_id
                ):
                    pairs.append((record, file_row))
        return pairs

    def list_folders_for_records(
        self,
        records: list[PluginRecord],
        field_keys: list[str],
    ) -> list[tuple[PluginRecord, dict[str, Any]]]:
        """List folders across several records and field keys.

        Args:
            records: Records to inspect (typically the host selection).
            field_keys: Keys of the folder-typed fields to query on each record.

        Returns:
            List of ``(record, folder_row)`` pairs, preserving the record
            each folder belongs to.
        """
        pairs: list[tuple[PluginRecord, dict[str, Any]]] = []
        for record in records:
            for field_key in field_keys:
                for folder_row in self.list_folders(
                    record.id, field_key, entity_id=record.entity_id
                ):
                    pairs.append((record, folder_row))
        return pairs

    def download_bytes(self, logical_key: str) -> bytes:
        """Download raw file content from server-side storage by logical key.

        Args:
            logical_key: Storage-relative path identifying the file
                (typically a file row's ``file_path``).

        Returns:
            Raw file content as bytes.
        """
        return self._transport.download_bytes(logical_key)

    def download_file(self, file_row: dict[str, Any]) -> bytes:
        """Download the content of a file described by a file metadata row.

        Args:
            file_row: A file dict as returned by :meth:`list_files`; must
                contain a non-empty ``file_path``.

        Returns:
            Raw file content as bytes.

        Raises:
            ValueError: If ``file_row`` has no ``file_path``.
        """
        logical_key = str(file_row.get("file_path") or "")
        if not logical_key:
            raise ValueError("Missing file_path.")
        return self.download_bytes(logical_key)

    def save_file_to_temp(self, file_row: dict[str, Any]) -> str:
        """Download a file and save it under a temporary local path.

        Args:
            file_row: A file dict as returned by :meth:`list_files`.

        Returns:
            Absolute path to the temporary file on the local filesystem.
        """
        content = self.download_file(file_row)
        return save_bytes_to_temp(content, suggested_name=file_display_name(file_row))

    def open_file(self, file_row: dict[str, Any]) -> str:
        """Download a file to a temp path and open it with the OS default app.

        Args:
            file_row: A file dict as returned by :meth:`list_files`.

        Returns:
            The temporary local path the file was saved to (and opened from).
        """
        path = self.save_file_to_temp(file_row)
        open_local_path(path)
        return path

    def open_files(self, file_rows: list[dict[str, Any]]) -> list[str]:
        """Download and open several files with the OS default application.

        Args:
            file_rows: File dicts as returned by :meth:`list_files`.

        Returns:
            List of temporary local paths, in the same order as ``file_rows``.
        """
        paths: list[str] = []
        for file_row in file_rows:
            paths.append(self.open_file(file_row))
        pump_gui_events()
        return paths

    def open_files_for_records(
        self,
        records: list[PluginRecord],
        field_keys: list[str],
    ) -> list[str]:
        """Download and open all files attached to given records/fields.

        Convenience helper combining :meth:`list_files_for_records` and
        :meth:`open_files`.

        Args:
            records: Records to inspect (typically the host selection).
            field_keys: Keys of the file-typed fields to query on each record.

        Returns:
            List of temporary local paths for every opened file.
        """
        pairs = self.list_files_for_records(records, field_keys)
        return self.open_files([file_row for _record, file_row in pairs])

    def field_key_for_label(
        self,
        label: str,
        *,
        entity_id: int | None = None,
        variant: str | None = None,
    ) -> str:
        """Resolve a visible attribute label to its ``field_key``.

        ``folder_tree``, ``list_files``, and ``list_folders`` take the field
        key. Call this first when the plugin knows the label shown in the UI.

        Matching ignores case and surrounding spaces. A label used by only
        one attribute resolves directly. The same label on two subtypes is
        ambiguous: pass ``variant`` (the subtype name or its key), or rely
        on the selection's subtype.

        Args:
            label: Attribute label as shown in the UI.
            entity_id: Table to inspect; defaults to the active entity.
            variant: Subtype name or key, used when the label is not unique.

        Returns:
            The attribute's ``field_key``.

        Raises:
            ValueError: Unknown label, unknown subtype, or ambiguous label.
        """
        schema = self.load_schema(entity_id)
        explicit = str(variant).strip() if variant is not None else ""
        fallback = None
        if not explicit:
            fallback = (
                self._context.primary_variant_key
                or self._context.primary_variant_label
                or None
            )
        return _resolve_field_key_for_label(
            schema,
            label,
            variant=explicit or None,
            fallback_variant=fallback,
        )

    def load_schema(self, entity_id: int | None = None) -> dict[str, Any]:
        """Load the schema bundle (fields, variants, etc.) for an entity.

        Args:
            entity_id: Entity (table) ID to load; defaults to the current
                context's ``entity_id`` when omitted.

        Returns:
            Schema bundle as a dict.
        """
        target = int(entity_id if entity_id is not None else self._context.entity_id)
        result = self._invoke("load_entity_schema_bundle", [target])
        return dict(result or {})

    def list_incoming_reference_records(
        self,
        record_id: int,
        entity_id: int | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Records that reference ``record_id`` (incoming references).

        Args:
            record_id: Table-local id of the record being referenced (the target).
            entity_id: Entity ID that owns the reference fields to inspect;
                defaults to the current context's ``entity_id``.

        Returns:
            List of ``(source table, attribute label, source record)``
            tuples. Each source record uses table-local ``id`` values.
        """
        target_entity_id = self._entity_id(entity_id)
        rows = (
            self._invoke(
                "list_incoming_reference_records",
                [int(record_id), target_entity_id],
                entity_id=target_entity_id,
            )
            or []
        )
        return self._normalize_reference_rows(rows)

    def list_outgoing_reference_records(
        self,
        record_id: int,
        *,
        entity_id: int | None = None,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Records referenced BY ``record_id`` (outgoing: e.g. experience -> MEA6).

        Returns (target table, attribute label, target record). Target ``id``
        values are table-local.
        """
        rows = (
            self._invoke(
                "list_outgoing_reference_records_full",
                [int(record_id)],
                entity_id=self._entity_id(entity_id),
            )
            or []
        )
        return self._normalize_reference_rows(rows)

    def list_source_records_linked_to(
        self,
        target_record_id: int,
        link_id: int,
        *,
        entity_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List records that link to ``target_record_id`` via a named link.

        Args:
            target_record_id: Table-local id of the record on the target side.
            link_id: ID of the link definition to traverse.
            entity_id: Table that owns ``target_record_id``. When omitted, the
                server resolves it from ``link_id``.

        Returns:
            List of source-side record dicts (table-local ids).
        """
        kwargs: dict[str, Any] = {}
        if entity_id is not None:
            kwargs["entity_id"] = int(entity_id)
        rows = (
            self._invoke(
                "list_source_records_linked_to",
                [int(target_record_id), int(link_id)],
                **kwargs,
            )
            or []
        )
        return [self._normalize_record_row(row) for row in rows]

    def list_target_records_for_link(
        self,
        source_record_id: int,
        link_id: int,
        *,
        entity_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List records linked to by ``source_record_id`` via a named link.

        Args:
            source_record_id: Table-local id of the record on the source side.
            link_id: ID of the link definition to traverse.
            entity_id: Table that owns ``source_record_id``. When omitted, the
                server resolves it from ``link_id``.

        Returns:
            List of target-side record dicts (table-local ids).
        """
        kwargs: dict[str, Any] = {}
        if entity_id is not None:
            kwargs["entity_id"] = int(entity_id)
        rows = (
            self._invoke(
                "list_target_records_for_link",
                [int(source_record_id), int(link_id)],
                **kwargs,
            )
            or []
        )
        return [self._normalize_record_row(row) for row in rows]

    def entity_id_for_key(self, entity_key: str) -> int | None:
        """Resolve an entity's numeric ID from its string key.

        Args:
            entity_key: Case-insensitive entity key to look up.

        Returns:
            The matching entity ID, or ``None`` if not found or ``entity_key``
            is empty.
        """
        target = str(entity_key or "").casefold()
        if not target:
            return None
        for row in self.list_entity_defs():
            if str(row.get("entity_key") or "").casefold() == target:
                return int(row["id"])
        return None

    @staticmethod
    def _normalize_record_row(row: Any) -> dict[str, Any]:
        """Coerce a server-returned row into a plain dict, dropping internal metadata.

        Ensures ``id`` is the table-local id and strips any leaked ``local_id`` key.

        Args:
            row: Raw row value from a server response (usually a dict).

        Returns:
            Plain dict copy of ``row`` with the internal ``__type`` key removed.
        """
        if isinstance(row, dict):
            payload = dict(row)
            payload.pop("__type", None)
            if payload.get("local_id") is not None:
                payload["id"] = int(payload["local_id"])
                payload.pop("local_id", None)
            return payload
        return dict(row or {})

    @staticmethod
    def _normalize_reference_rows(
        rows: list[Any],
    ) -> list[tuple[str, str, dict[str, Any]]]:
        """Normalize raw reference rows into ``(table, label, record)`` tuples.

        Args:
            rows: Raw list of ``[table, label, record]``-like sequences
                returned by the server for reference-listing operations.

        Returns:
            List of ``(table name, attribute label, normalized record dict)``
            tuples; malformed entries are silently skipped.
        """
        normalized: list[tuple[str, str, dict[str, Any]]] = []
        for row in rows or []:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            record = PluginApi._normalize_record_row(row[2])
            normalized.append((str(row[0]), str(row[1]), record))
        return normalized

    def launch_script(
        self, relative_path: str, *, detached: bool = True, check_delay: float = 0.25
    ) -> None:
        """Launch a plugin Python script via the dedicated venv (external GUI)."""
        launch_plugin_script(
            plugin_id=self._context.plugin_id,
            plugin_root=self._context.plugin_root,
            relative_path=relative_path,
            plugin_python=self._context.plugin_python,
            detached=detached,
            check_delay=check_delay,
        )
