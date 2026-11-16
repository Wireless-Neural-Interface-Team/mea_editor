"""NeuroRehab plugin: open Mapping JSON files in the local MEA editor.

Buttons live in the plugin panel on the Mapping and Components tables.
The editor process is the standalone MEA editor. It loads a local copy of
the database file and saves on disk only.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext, PluginRecord
from neurorehab_plugin.local_files import file_display_name
from neurorehab_plugin.ui import ZONE_PLUGIN_PANEL, PluginUi

JSON_FILE_LABEL = "JSON mapping file"
MAPPING_REFERENCE_LABEL = "Mapping"
OPEN_REQUEST_NAME = ".mea_editor_open.json"
SESSION_NAME = ".mea_editor_session.json"
COMMAND_NAME = ".mea_editor_command.json"
VIEWER_SESSION_NAME = ".mea_editor_viewer_session.json"
VIEWER_COMMAND_NAME = ".mea_editor_viewer_command.json"
EDITOR_SCRIPT = "open_mea_editor.py"

_FIELD_KEYS: dict[tuple[int, str, str], str] = {}
_FIELD_KEYS_LOADED = False
_MAPPING_ENTITY_ID: dict[str, int | None] = {}
_LOCAL_COPIES: dict[str, str] = {}
_REMEMBERED: dict[tuple[int, int], str] = {}
_REMEMBERED_LOADED = False
_PENDING_VIEWER: dict[str, Any] = {}
_EDITOR_BOOT_S = 20.0

_MAPPING_TABLES = frozenset({"mapping", "mappings"})
_COMPONENT_TABLES = frozenset({"component", "components"})
_MEA_SUBTYPES = frozenset(
    {
        "intracerebra mea",
        "in vitro mea",
        "epicortical mea",
    }
)


def build_ui(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Add plugin-panel buttons for the Mapping and Components tables."""
    kind = _table_kind(context)
    if kind is None:
        return

    records = context.selected_records
    selected = records[0] if len(records) == 1 else None
    if kind == "mapping":
        can_open = selected is not None
        callback = lambda record=selected: _open_mapping_row(api, context, ui, record)
    else:
        can_open = selected is not None and _is_mea_subtype(selected)
        callback = lambda record=selected: _open_component_mapping(api, context, ui, record)

    ui.add_button(
        "View mapping",
        callback,
        zone=ZONE_PLUGIN_PANEL,
        enabled=can_open,
    )
    ui.add_button(
        "Open MEA Mapping Editor",
        lambda: _launch_editor(api, context, ui, None),
        zone=ZONE_PLUGIN_PANEL,
        new_row=False,
    )


def _open_mapping_row(
    api: PluginApi,
    context: PluginContext,
    ui: PluginUi,
    record: PluginRecord | None,
) -> None:
    """Download the selected Mapping row's JSON and open it locally."""
    if record is None:
        ui.show_message("Open JSON mapping", "Select one Mapping row.")
        return

    def _resolve(deliver) -> tuple[str | None, str | None]:
        return _json_path_for_record(
            api,
            record.id,
            record.entity_id,
            variant=record.variant_key or record.variant_label or None,
            file_name_hint=f"mapping_{record.id}",
            deliver=deliver,
        )

    _finish_open(api, context, ui, _resolve)


def _open_component_mapping(
    api: PluginApi,
    context: PluginContext,
    ui: PluginUi,
    record: PluginRecord | None,
) -> None:
    """Follow the Mapping reference, then open that row's JSON locally."""
    if record is None or not _is_mea_subtype(record):
        ui.show_message(
            "Open JSON mapping",
            "Select one Components row whose subtype is Intracerebra MEA, "
            "In vitro MEA, or Epicortical MEA.",
        )
        return

    def _resolve(deliver) -> tuple[str | None, str | None]:
        target, error = _mapping_target(api, record)
        if error or target is None:
            return None, error or "This row has no Mapping reference."
        target_id = _record_id(target)
        entity_id = _entity_id(target) or _mapping_entity_id(api)
        if target_id is None or entity_id is None:
            return None, "The Mapping reference could not be resolved."
        return _json_path_for_record(
            api,
            target_id,
            entity_id,
            variant=_variant_name(target),
            file_name_hint=f"mapping_{target_id}",
            deliver=deliver,
        )

    _finish_open(api, context, ui, _resolve)


def _finish_open(
    api: PluginApi,
    context: PluginContext,
    ui: PluginUi,
    resolve,
) -> None:
    """Open the viewer, show a local copy at once, then refresh it if needed.

    A mapping already saved on this computer is handed to the viewer before
    the database is asked again. The first open still downloads the file.
    """
    try:
        token = _ensure_editor(api, context, ui)
    except Exception as exc:
        ui.show_message("Open JSON mapping", str(exc))
        return
    root = Path(context.plugin_root)
    shown: dict[str, str | None] = {"path": None}

    def deliver(path: str) -> None:
        if not path or path == shown["path"]:
            return
        _post_command(root, token, path)
        shown["path"] = path

    try:
        path, error = resolve(deliver)
    except Exception as exc:
        path, error = None, str(exc)
    if error or not path:
        if shown["path"]:
            return
        message = error or "No JSON mapping file on this row."
        _write_command(root / VIEWER_COMMAND_NAME, token, "", message)
        return
    deliver(path)


def _launch_editor(
    api: PluginApi,
    context: PluginContext,
    ui: PluginUi,
    path: str | None,
) -> None:
    """Start a new standalone MEA editor. ``path`` is a local JSON, or blank."""
    root = Path(context.plugin_root)
    token = uuid.uuid4().hex
    request = root / OPEN_REQUEST_NAME
    try:
        request.write_text(
            json.dumps({"path": path, "token": token}),
            encoding="utf-8",
        )
        api.launch_script(EDITOR_SCRIPT, detached=True, check_delay=0)
    except Exception as exc:
        ui.show_message("MEA Mapping Editor", str(exc))


def _ensure_editor(api: PluginApi, context: PluginContext, ui: PluginUi) -> str:
    """Reuse the mapping viewer, or start one without waiting for its window."""
    del ui
    root = Path(context.plugin_root)
    session = _read_session(root, VIEWER_SESSION_NAME)
    if session is not None and _pid_alive(int(session["pid"])):
        _PENDING_VIEWER.clear()
        return str(session["token"])
    pending = str(_PENDING_VIEWER.get("token") or "")
    started = float(_PENDING_VIEWER.get("at") or 0.0)
    if pending and (time.monotonic() - started) < _EDITOR_BOOT_S:
        return pending
    token = uuid.uuid4().hex
    (root / OPEN_REQUEST_NAME).write_text(
        json.dumps({"path": None, "token": token, "view_only": True}),
        encoding="utf-8",
    )
    api.launch_script(EDITOR_SCRIPT, detached=True, check_delay=0)
    _PENDING_VIEWER["token"] = token
    _PENDING_VIEWER["at"] = time.monotonic()
    return token


def _post_command(root: Path, token: str, path: str) -> None:
    """Ask the running viewer to load ``path``. A new seq wakes its watcher."""
    _write_command(root / VIEWER_COMMAND_NAME, token, path)


def _write_command(command: Path, token: str, path: str, error: str = "") -> None:
    seq = 1
    try:
        current = json.loads(command.read_text(encoding="utf-8"))
        if isinstance(current, dict):
            seq = int(current.get("seq") or 0) + 1
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        seq = 1
    command.write_text(
        json.dumps({"token": token, "seq": seq, "path": path, "error": error}),
        encoding="utf-8",
    )


def _read_session(root: Path, name: str = SESSION_NAME) -> dict[str, Any] | None:
    try:
        payload = json.loads((root / name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    token = payload.get("token")
    if not isinstance(pid, int) or not token:
        return None
    return payload


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _json_path_for_record(
    api: PluginApi,
    record_id: int,
    entity_id: int,
    *,
    variant: str | None,
    file_name_hint: str,
    deliver=None,
) -> tuple[str | None, str | None]:
    """Download ``JSON mapping file`` to a local JSON path.

    ``deliver`` receives a path as soon as one is known, including a copy
    left from an earlier open, so the viewer does not stay empty during
    the database round trip.
    """
    remembered = _remembered_local(entity_id, record_id)
    if remembered and deliver is not None:
        deliver(remembered)
    try:
        field_key = _cached_field_key(api, JSON_FILE_LABEL, entity_id, variant)
    except ValueError as exc:
        return None, str(exc)
    files = api.list_files(record_id, field_key, entity_id=entity_id)
    chosen, error = _pick_json_file(files)
    if error or chosen is None:
        return None, error
    local_path = _write_local_copy(api, chosen, file_name_hint)
    _remember_local(entity_id, record_id, local_path)
    return local_path, None


def _mapping_target(
    api: PluginApi,
    record: PluginRecord,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return the Mapping row referenced by a Components row.

    The selected row already carries the reference id. That avoids the
    outgoing-reference query, which loads every linked record.
    """
    key_error: str | None = None
    try:
        field_key = _cached_field_key(
            api,
            MAPPING_REFERENCE_LABEL,
            record.entity_id,
            record.variant_key or record.variant_label or None,
        )
    except ValueError as exc:
        field_key = ""
        key_error = str(exc)
    if field_key:
        ids = _reference_ids(api.get_field(record, field_key))
        if len(ids) > 1:
            return None, "This row references more than one Mapping record."
        if len(ids) == 1:
            entity_id = _mapping_entity_id(api)
            if entity_id is None:
                return None, "The Mapping table was not found."
            return {"id": ids[0], "entity_id": entity_id}, None

    refs = api.list_outgoing_reference_records(record.id, entity_id=record.entity_id)
    matches = [
        target
        for _table_label, field_label, target in refs
        if _norm(field_label) == _norm(MAPPING_REFERENCE_LABEL)
    ]
    if len(matches) > 1:
        return None, "This row references more than one Mapping record."
    if len(matches) == 1:
        return matches[0], None
    if key_error:
        return None, key_error
    return None, "This row has no Mapping reference."


def _cached_field_key(
    api: PluginApi,
    label: str,
    entity_id: int,
    variant: str | None,
) -> str:
    """Resolve a label once per table. The schema call is the slow part."""
    _load_field_keys()
    cache_key = (int(entity_id), label.casefold(), _norm(variant))
    cached = _FIELD_KEYS.get(cache_key)
    if cached:
        return cached
    key = api.field_key_for_label(label, entity_id=entity_id, variant=variant)
    _FIELD_KEYS[cache_key] = key
    _save_field_keys()
    return key


def _cache_dir() -> Path:
    folder = Path(tempfile.gettempdir()) / "mea_editor_mappings"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _load_field_keys() -> None:
    """Keep attribute keys across plugin restarts so the schema is not reloaded."""
    global _FIELD_KEYS_LOADED
    if _FIELD_KEYS_LOADED:
        return
    _FIELD_KEYS_LOADED = True
    try:
        payload = json.loads((_cache_dir() / "field_keys.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    for raw, key in payload.items():
        parts = str(raw).split("\t")
        if len(parts) != 3 or not key or not parts[0].isdigit():
            continue
        _FIELD_KEYS[(int(parts[0]), parts[1], parts[2])] = str(key)


def _save_field_keys() -> None:
    payload = {
        f"{entity_id}\t{label}\t{variant}": key
        for (entity_id, label, variant), key in _FIELD_KEYS.items()
    }
    (_cache_dir() / "field_keys.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_remembered() -> None:
    global _REMEMBERED_LOADED
    if _REMEMBERED_LOADED:
        return
    _REMEMBERED_LOADED = True
    try:
        payload = json.loads((_cache_dir() / "opened_mappings.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    for raw, path in payload.items():
        entity_text, sep, record_text = str(raw).partition(":")
        if not sep or not entity_text.isdigit() or not record_text.isdigit():
            continue
        if path:
            _REMEMBERED[(int(entity_text), int(record_text))] = str(path)


def _remembered_local(entity_id: int, record_id: int) -> str | None:
    """Last local copy opened for this row, if it is still on disk."""
    _load_remembered()
    path = _REMEMBERED.get((int(entity_id), int(record_id)))
    if path and Path(path).is_file():
        return path
    return None


def _remember_local(entity_id: int, record_id: int, path: str) -> None:
    _load_remembered()
    _REMEMBERED[(int(entity_id), int(record_id))] = path
    payload = {f"{entity}:{record}": saved for (entity, record), saved in _REMEMBERED.items()}
    (_cache_dir() / "opened_mappings.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_local_copy(api: PluginApi, file_row: dict[str, Any], hint: str) -> str:
    """Store the database file under a local temp folder. Save stays there.

    The same database file is not downloaded again. Opening it is then the
    same step as File > Open on a file already on disk.
    """
    identity = _file_identity(file_row)
    cached = _LOCAL_COPIES.get(identity)
    if cached and Path(cached).is_file() and Path(cached).stat().st_size > 0:
        return cached
    name = Path(file_display_name(file_row)).name.replace("/", "_").replace("\\", "_")
    if not name or name in {".", ".."}:
        name = f"{hint}.json"
    if not name.lower().endswith(".json"):
        name = f"{hint}_{name}.json"
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:12]
    path = _cache_dir() / f"{hint}_{digest}_{name}"
    if path.is_file() and path.stat().st_size > 0:
        _LOCAL_COPIES[identity] = str(path)
        return str(path)
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(api.download_file(file_row))
    partial.replace(path)
    _LOCAL_COPIES[identity] = str(path)
    return str(path)


def _file_identity(file_row: dict[str, Any]) -> str:
    """Stable id for a stored file, so an unchanged mapping is not fetched twice.

    A checksum, or the file id with its size, is enough. ``file_path`` is left
    out: the storage key can change while the bytes stay the same, and that
    used to download the mapping again on every click.
    """
    file_id = file_row.get("id")
    checksum = file_row.get("checksum") or file_row.get("sha256") or ""
    size = file_row.get("size")
    if size in (None, ""):
        size = file_row.get("byte_size")
    if file_id not in (None, "") and checksum:
        return f"id={file_id}|sum={checksum}"
    if file_id not in (None, "") and size not in (None, ""):
        updated = file_row.get("updated_at") or ""
        return f"id={file_id}|size={size}|updated={updated}"
    parts: list[str] = []
    for key in ("id", "file_path", "updated_at", "checksum", "sha256", "size", "byte_size"):
        value = file_row.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return "|".join(parts) or file_display_name(file_row)


def _pick_json_file(files: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Choose the single JSON attached to the file attribute."""
    if not files:
        return None, "No file is attached to JSON mapping file."
    json_files = [
        row for row in files if file_display_name(row).lower().endswith(".json")
    ]
    if len(json_files) == 1:
        return json_files[0], None
    if len(json_files) > 1:
        names = ", ".join(file_display_name(row) for row in json_files)
        return None, f"JSON mapping file has several JSON files: {names}"
    if len(files) == 1:
        return files[0], None
    names = ", ".join(file_display_name(row) for row in files)
    return None, f"JSON mapping file has no JSON file: {names}"


def _mapping_entity_id(api: PluginApi) -> int | None:
    if "id" in _MAPPING_ENTITY_ID:
        return _MAPPING_ENTITY_ID["id"]
    found: int | None = None
    for key in ("mapping", "mappings"):
        found = api.entity_id_for_key(key)
        if found is not None:
            break
    _MAPPING_ENTITY_ID["id"] = found
    return found


def _table_kind(context: PluginContext) -> str | None:
    names = {
        _norm(context.entity_key),
        _norm(context.entity_label),
        _norm(context.entity_label_plural),
    }
    names.discard("")
    if names & _MAPPING_TABLES:
        return "mapping"
    if names & _COMPONENT_TABLES:
        return "components"
    return None


def _is_mea_subtype(record: PluginRecord) -> bool:
    names = {_norm(record.variant_label), _norm(record.variant_key)}
    names.discard("")
    return bool(names & _MEA_SUBTYPES)


def _norm(value: object) -> str:
    text = str(value or "").replace("_", " ").replace("-", " ")
    return " ".join(text.split()).casefold()


def _record_id(record: PluginRecord | dict[str, Any]) -> int | None:
    if isinstance(record, PluginRecord):
        return int(record.id)
    return _coerce_id(record.get("id"))


def _entity_id(record: PluginRecord | dict[str, Any]) -> int | None:
    if isinstance(record, PluginRecord):
        return int(record.entity_id)
    return _coerce_id(record.get("entity_id"))


def _variant_name(record: PluginRecord | dict[str, Any]) -> str | None:
    if isinstance(record, PluginRecord):
        variant = record.variant_key or record.variant_label
    else:
        variant = str(record.get("variant_key") or record.get("variant_label") or "")
    variant = str(variant or "").strip()
    return variant or None


def _reference_ids(value: Any) -> list[int]:
    if isinstance(value, list):
        ids: list[int] = []
        for item in value:
            found = _coerce_id(item)
            if found is not None:
                ids.append(found)
        return ids
    found = _coerce_id(value)
    return [found] if found is not None else []


def _coerce_id(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        return None
    if isinstance(value, dict):
        for key in ("id", "local_id", "record_id"):
            found = _coerce_id(value.get(key))
            if found is not None:
                return found
    return None
