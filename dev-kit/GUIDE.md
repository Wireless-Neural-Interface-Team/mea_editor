# Developer guide — NeuroRehab plugins

Read-only extensions for the NeuroRehab database desktop client.

---

## Table of contents

1. [Architecture](#architecture)
2. [Quick start](#quick-start)
3. [Language (English only)](#language-english-only)
4. [Project layout](#project-layout)
5. [`plugin.toml`](#plugintoml)
6. [Entry points](#entry-points)
7. [`PluginContext`](#plugincontext)
8. [`PluginApi`](#pluginapi)
9. [`PluginUi`](#pluginui)
10. [Host responsiveness (MUST)](#host-responsiveness-must)
11. [Host refresh on selection](#host-refresh-on-selection)
12. [Performance — many API calls](#performance--many-api-calls)
13. [Packaged NeuroRehab client](#packaged-neurorehab-client)
14. [External GUI scripts](#external-gui-scripts)
15. [Publish & install](#publish--install)
16. [Security](#security)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  NeuroRehab desktop (.exe)                                  │
│  · Renders ZONE_* (buttons only)                            │
│  · Host IPC allowlist: add_button / clear only              │
│  · Read-only PluginApi HTTP (token scoped to selection)     │
└───────────────────────────┬─────────────────────────────────┘
                            │ JSON stdin/stdout
┌───────────────────────────▼─────────────────────────────────┐
│  Worker subprocess (every plugin)                           │
│  plugins/venvs/<id>@<version>/python.exe                       │
│  · run() / build_ui() / button callbacks                    │
│  · show_message / show_table / run_task (worker-local)      │
│  · ui.open_window() → custom Qt widgets in worker process   │
└─────────────────────────────────────────────────────────────┘
```

| Topic | Detail |
|-------|--------|
| **Python** | 3.11.7 on dev machines and clients |
| **Venv** | One isolation venv per plugin per **machine** (always; deps installed when `requirements.txt` exists) |
| **Worker** | Always used — `python.exe` in the plugin venv (piped stdin/stdout — not `pythonw`) |
| **Host UI** | NeuroRehab stays interactive during plugin IPC (pumps user input); hung workers are killed |
| **Machine paths** | `plugins/cache/`, `plugins/venvs/`, `plugins/machine_settings.json` (`enabled` + `packages`) |
| **User data** | Favorites on server (`plugin_user_preference.favorite`), no local `plugins/users/` cache |
| **Activation** | Plugins tab: **To install** / **To uninstall** columns + **Apply changes** (machine-scoped) |
| **Writes** | Forbidden — SDK + server whitelist |
| **HTTP** | One persistent connection per `PluginApi`; use `invoke_batch()` for heavy reads |

---

## Quick start

### Get the kit

- **From NeuroRehab (recommended):** **Plugins → Download dev-kit…**
  - Name the project folder after the **plugin id** (lowercase, digits, underscore).
  - Choose a parent folder. The kit is extracted **into that named folder**
    (SDK, scripts, starter `plugin.toml` / `main.py` at the root).
  - **This folder is the plugin.** Edit it in place. Do **not** add a nested
    `dev-kit/` subdirectory.
  - Admins publish kit updates with **Publish dev-kit to server…**.
- **Download for editing** (Plugins tab, per row): same layout — one folder
  named after the plugin, catalog sources overlaid on the kit. Ready to run
  `setup-dev` and `prepare-publish`.
- **From the Git repo:** `cd plugins ; .\assemble-kit.ps1 -OutputDir "C:\Projects\my_plugin" -PluginId "my_plugin"`.

### Develop

```powershell
cd my_plugin
.\setup-dev.ps1
.\smoke-worker.ps1
# edit plugin.toml + main.py  (id must match the folder name)
.\prepare-publish.ps1
```

Install `publish/` in NeuroRehab: **Plugins → Import plugin to database…** (server upload).
Then in the **Plugins** tab, check **To install** for the plugin and click **Apply changes**
to build the local venv on this workstation.

Pick a pattern from [examples/](examples/) if the root starter is not enough.

---

## Language (English only)

NeuroRehab and this kit are **English-first**. Write **everything** in English:

| Surface | Expectation |
|---------|-------------|
| `plugin.toml` | `name`, `description`, comments |
| UI strings | Buttons, dialogs, banners, tables, status text, window titles |
| Code | Comments, docstrings, log/error messages |
| Docs shipped with the plugin | README, notes, examples you publish or share |

Do **not** mix French (or other languages) into user-visible text or source comments.
Schema field *keys* (`entity_keys`, attribute keys) stay as defined in the database;
only the wording you author must be English.

Before `prepare-publish`, skim your `publish/` folder: every label a user can see
should read naturally in English.

---

## Project layout

```
my_plugin/                 # folder name = plugin.toml id
├── plugin.toml            # manifest (published)
├── main.py                # entry point (published)
├── requirements.txt       # runtime deps (published if present)
├── other_module.py        # optional helpers (published)
├── neurorehab_plugin/     # SDK — dev only
├── examples/              # patterns — not published
├── GUIDE.md
├── setup-dev.ps1
└── prepare-publish.ps1    # → publish/ for Import plugin to database…
```

All of these files live at the **project root**. Do not nest a `dev-kit/` folder
inside `my_plugin/`. `prepare-publish.ps1` copies only `plugin.toml`,
`requirements.txt`, the `entry` file, and other `*.py` at the project root
(not `examples/`). That `publish/` folder is what you import into the database.

---

## `plugin.toml`

```toml
[plugin]
id = "my_plugin"              # unique: lowercase, digits, underscore — same as the folder name
version = "1.0.0"             # package version MAJOR.MINOR.PATCH (required on upload)
name = "My plugin"              # button / group title
description = "..."             # required — shown in Plugins tab (Description column)
api_version = 1
entry = "main.py"
placement = "entity_tab"        # entity_tab | record_panel | home | all
selection_mode = "optional"     # see table below
# run_trigger = "manual"        # manual (default) | on_select
# selection_ui = "enable"       # none | enable | rebuild — see table below

# entity_keys = ["mea"]         # table tabs: omit = all except Inventory; Home: declare readable tables

# [[plugin.when]]
# variant_keys = ["mea64"]
# [[plugin.when.fields]]
# key = "status"
# equals = "active"
```

### `version` (package versioning)

| Rule | Detail |
|------|--------|
| Format | `MAJOR.MINOR.PATCH` (optional prerelease, e.g. `1.2.0-rc.1`) |
| Upload | **Required** when importing to the database |
| Local dev | May be omitted → defaults to `1.0.0` |
| Same `id` + same `version` | Replaces that catalog entry |
| Same `id` + new `version` | Adds a **new** installable package; older versions stay available |
| Workstation | Each version installs as `id@version` (cache / venv / buttons side by side) |

Bump `version` before each publish that should coexist with a previous release.
Do **not** reuse an old version string unless you intend to overwrite that exact package.

### `placement`

| Value | Where |
|-------|--------|
| `entity_tab` | Toolbar above the grid (default) |
| `record_panel` | Information panel (below host fields) |
| `home` | Home tab, below session content (use `ZONE_HOME`) |
| `all` | Table tabs **and** Home. Zones missing on the current tab are skipped. |

The **Inventory** tab reuses the table layout but **never** hosts plugins.
Omitting `entity_keys`, naming Inventory, or using `placement = "all"` does
not place buttons there. Open the row in its own table tab to use plugins.

The Information panel has two layers: **host fields** (ID, attributes, folders —
always NeuroRehab) and **your** `ZONE_RECORD_PANEL` buttons below.

Home buttons sit **below** whatever the current user can see on Home (session
block, and retention when that role allows it).

On Home, `entity_keys` declares which tables the plugin may **read** (all rows
the signed-in user can view on those tables). Omit it for UI-only Home buttons
(no row data). Access is always the intersection of plugin read-only scope and
the user's live table rights.

### `selection_mode`

| Value | Without selection |
|-------|-------------------|
| `one_or_more` (default) | Button hidden |
| `optional` | Button visible; 0–N rows OK |
| `none` | For 0 rows only |
| `single` / `multiple` | Enforced at run time |

### `selection_ui`

Controls how **row selection** refreshes this plugin’s UI (performance).

| Value | Behavior |
|-------|----------|
| *(omit)* | Auto: plain manual launchers → `none`; `build_ui` / `on_select` → `rebuild` |
| `none` | Selection never rebuilds UI (host may still enable/disable a launcher) |
| `enable` | Host `setEnabled` on existing `build_ui` buttons; worker `build_ui` only on first paint |
| `rebuild` | Full worker `build_ui` / `on_select` after each selection change |

Use `enable` when buttons are static and only need enable/disable. Use `rebuild`
(or omit) when labels/content must follow the selected row (e.g. `Analyze #123`).
Legacy `ui_depends_on_selection = false` maps to `none`; `true` maps to `rebuild`.

### `run_trigger`

| Value | Behavior |
|-------|----------|
| `manual` | Launcher button; UI until next click or selection change |
| `on_select` | No launcher; `run()` after row detail loads |

`on_click` is an alias for `manual`.

When `build_ui()` is defined, `run_trigger` is **ignored**. `placement = "home"`
still targets the Home tab; `placement = "all"` runs on table tabs **and** Home;
other placements still run on table tabs. None of these placements run on
Inventory.

---

## Entry points

### `run(api, context, ui)` — manual / on_select

Called when the user clicks the launcher (`manual`) or after the detail bundle
loads (`on_select`).

```python
def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    records = context.applicable_records or context.selected_records
    if not records:
        ui.show_message("Plugin", "Select a row.")
        return
    ui.add_button("Action", lambda: ui.show_message("OK", "Done"))
```

### `build_ui(api, context, ui)` — persistent buttons

Called when the plugin becomes active. By default (`selection_ui = "rebuild"`
or omitted with `build_ui` present) it also runs after each selection change.
With `selection_ui = "enable"`, the host only toggles `enabled` on existing
buttons after the first paint (no worker round-trip per click).

```python
def build_ui(api, context, ui):
    records = context.applicable_records or context.selected_records
    one = len(records) == 1
    btn = ui.add_button("Analyze", _analyze, zone=ZONE_RECORD_PANEL, enabled=one)
    if one:
        btn.set_label(f"Analyze #{records[0].id}")
```

Use `selection_mode = "optional"` to keep buttons visible with no selection
(disabled via `enabled=False`). Prefer `selection_ui = "enable"` when you do
not need per-row labels.

### `on_file_chosen(api, context, ui, *, …)` — draft form assist

Optional. When the user picks a **local file** via **Browse…** on a File
attribute in an open **Add / Edit / Duplicate** form, the host calls this
hook (no launcher button required). Return suggested values for **other**
fields on that open form. The host applies them to widgets only — **nothing
is written to the database** until the user confirms Add / Update.

Detection: the entry file must define `def on_file_chosen`. The plugin must
target the form's table (`entity_keys` / placement on entity tabs) and be
installed on the workstation.

```python
def on_file_chosen(
    api,
    context,
    ui,
    *,
    field_key: str,
    local_path: str,
    draft: dict,
    variant_id: int | None,
    form_mode: str,  # "add" | "edit" | "duplicate"
):
    # Read local_path on disk. api stays read-only.
    # Host UI emit is disabled — do not rely on add_button here.
    return {
        "suggested_values": {
            "name": Path(local_path).stem,
            "notes": f"From {Path(local_path).name}",
        }
    }
```

| Rule | Detail |
|------|--------|
| Return | `{"suggested_values": {field_key: value, …}}`, a bare `{field_key: value}` dict, or `None` |
| Applied keys | Only fields present on the open form |
| Never applied | File, Folder, Combo, and the File field that triggered Browse |
| Invalid values | Skipped for that field (form stays usable) |
| DB writes | Forbidden — same read-only API; host never auto-submits the form |

See [examples/form_file_assist](examples/form_file_assist/).

---

## `PluginContext`

| Field | Meaning |
|-------|---------|
| `entity_key` | Current table identifier |
| `selected_records` | All selected rows |
| `applicable_records` | Rows matching `[[plugin.when]]` rules |
| `primary_variant_key` | Sub-type of primary row |
| `plugin_id` / `plugin_root` / `plugin_python` | Install paths |
| `username` | Logged-in user |

Each `PluginRecord` has `id` (table-local `#N`, not the global PK), `entity_id`, `display_label`, `data` (reference fields also store table-local target ids), `variant_key`, …

Reference values are converted with the record's own subtype first, so a key shared by several subtypes gets the right type; keys left by a previous subtype are still converted. A single reference whose target row was purged is `None`; purged ids are dropped from a multi-reference list.

Record ids throughout `PluginApi` / `PluginUi.highlight_records` are table-local.
Pass `entity_id=` when the row belongs to a table other than the active one.

---

## `PluginApi`

Read-only. Common calls:

| Category | Methods |
|----------|---------|
| Records | `get_record`, `get_field`, `get_fields` |
| Schema | `list_entity_defs`, `load_schema`, `entity_id_for_key`, `field_key_for_label` |
| Files | `list_files`, `list_files_for_field_keys`, `list_files_for_records`, `find_files`, `download_file`, `download_bytes`, `save_file_to_temp`, `open_file`, `open_files`, `open_files_for_records` |
| File lookup | `get_record_file_by_path` (resolve a stored path / `neurorehab-file:` key, including rich-text images) |
| Folders | `folder_tree`, `list_folders`, `list_folders_for_field_keys`, `list_folders_for_records` |
| References | `list_incoming_reference_records`, `list_outgoing_reference_records` |
| Table links | `list_source_records_linked_to`, `list_target_records_for_link` |
| Batch / scripts | `invoke_batch`, `launch_script` |

Single- and **multi-reference** attribute values are included in incoming /
outgoing graphs (a multi-reference may yield several targets for one field).

`folder_tree`, `list_files`, and `list_folders` take the attribute **key**. Users see the label, so resolve it first. `folder_tree` loads folders and files in one batch. It is the same arborescence as the record panel. A file dict from that tree is read-only input for `open_file`, `save_file_to_temp`, or `download_file`.

`find_files(record_id, name="scan.dcm")` resolves a file in one request. `open_file` / `save_file_to_temp` always stream a new copy from the server to disk. A previous local file for the same storage key is not reused. `download_file` still returns the whole content in memory for plugins that parse it.

```python
key = api.field_key_for_label("Données brutes")
tree = api.folder_tree(record.id, key)

def walk(node):
    for folder in node["folders"]:
        walk(folder)
    for file_row in node["files"]:
        api.open_file(file_row)

walk(tree)
```

The label match ignores case and surrounding spaces. If two subtypes share the label, `field_key_for_label` raises `ValueError`; pass `variant=` (subtype name or key). With a selection, the current subtype breaks that tie. Two files or folders may share a display name. The tree keeps both; open the file dict (`id`), not the name.

**Performance:** for tens of read calls, prefer **`invoke_batch([{"op": "…", "args": […]}, …])`**
(max 50 per request) instead of looping `get_record` / `list_files` individually.
The SDK keeps a **keep-alive** HTTP connection and reconnects on transient errors.

**Forbidden:** write-like prefixes (`create_*`, `update_*`, `delete_*`, `set_*`, `store_*`, `save_*`, `apply_*`, `run_*`, `restore_*`, `provision_*`, `sync_*`, `install_*`, `upload_*`, `clear_*`, `purge_*`, `grant_*`, `revoke_*`, `touch_*`, `import_*`, `hard_*`, `duplicate_*`, `reorder_*`, `export_*`, `rename_*`, `copy_*`), team/account lookups (`list_app_users`, `list_team_member_combo_items`, `list_team_member_name_parts`, …), and automatic-action ops (`save_variant_automation_rules`, `list_automation_rule_history`, …) → `PluginWriteForbiddenError`. Spreadsheet subtype import and File/Folder **rename** are desktop-only: plugins cannot create subtypes or rows, nor rename stored files/folders. The server whitelist (`core/plugin/readonly_ops.py`, **25** read ops) is the final gate.

Linked records (references in both directions) are readable when tied to the
selection. See [examples/outgoing_references/](examples/outgoing_references/).

---

## `PluginUi`

Authorized zones — **buttons only** in host zones:

| Constant | Location |
|----------|----------|
| `ZONE_ENTITY_TOOLBAR` | Above grid |
| `ZONE_RECORD_PANEL` | Information panel |
| `ZONE_RELATED_PANEL` | Related rows panel |
| `ZONE_PLUGIN_PANEL` | Right column below Related |
| `ZONE_HOME` | Home tab, below session content (retention and other permission-gated widgets) |

A valid zone that is not on the current tab (e.g. `ZONE_HOME` on a table tab,
or `ZONE_RECORD_PANEL` on Home) is **skipped**: `add_button` returns a no-op
handle and does not raise. Use `placement = "all"` if the plugin should run
on both surfaces. Inventory skips every zone.

In each plugin group box, buttons can sit **side by side** or **one below the
other**. Toolbar and Home keep successive buttons on the same row; other zones
start a new row. Override with `new_row=True` (below) or `new_row=False` (same
row):

```python
ui.add_button("Save", on_save, zone=ZONE_RECORD_PANEL)
ui.add_button("Export", on_export, zone=ZONE_RECORD_PANEL, new_row=False)
ui.add_button("Run", on_run)  # toolbar: same row as the previous toolbar button
ui.add_button("Advanced", on_advanced, new_row=True)
```

| Method | Role |
|--------|------|
| `add_button(label, callback, zone=..., enabled=True, new_row=None)` | Returns `PluginButton` handle (**only** host chrome mutation) |
| `show_message` / `show_table` / `show_info` | Modals in the **worker** process |
| `open_window(title, width=..., height=...)` | Floating **worker** window (fully customizable) |
| `window_builder_is_alive(builder)` | `False` if the worker window was closed (safe reuse of a stored `builder`) |
| `run_task(title, worker)` | Worker-local progress dialog; `worker` must not call `ui.*` |
| `export_csv` | Write CSV locally in the worker |
| `set_status_banner` / `highlight_records` | No-op (kept for API compatibility; do not affect the host) |
| `clear_zone` / `clear()` | Clear **your** plugin buttons only |

Content (text, tables) → button + `show_message` / `show_table`, or a custom `open_window`.

### `open_window()` — custom Qt in worker

```python
builder = ui.open_window("Viewer", width=640, height=480)
builder.add_button("Info", lambda: ui.show_message("Hi", "…"))

from PySide6.QtWidgets import QLabel
label = QLabel("…", builder._parent)   # declare PySide6 in requirements.txt
builder._layout.addWidget(label)
```

Open from a **button callback**, never from `build_ui()` on each selection.

Worker windows close with `WA_DeleteOnClose` (the worker process keeps running).
The host grants foreground focus to the worker after each button callback so the
first opened window is not hidden behind NeuroRehab. If you store the returned
`builder` in module state to refresh the same window on later clicks, check it is
still alive before touching `builder._parent` or `builder._layout`:

```python
from neurorehab_plugin.ui import window_builder_is_alive

_SESSION: dict[str, object] = {"builder": None}

def _open_viewer(ui: PluginUi, title: str, text: str) -> None:
    builder = _SESSION.get("builder")
    if not window_builder_is_alive(builder):
        builder = ui.open_window(title, width=640, height=480)
        _SESSION["builder"] = builder
        # create widgets once (labels, editors, …)
    else:
        builder._parent.setWindowTitle(title)
        # update existing widgets
```

Without `window_builder_is_alive()`, reusing a builder after the user closed the
window raises `RuntimeError: Internal C++ object (QDialog) already deleted.`

See [examples/worker_window/](examples/worker_window/) for a full pattern.

### Button style (custom Qt)

Host zone buttons (`ui.add_button`) use the NeuroRehab application style automatically.
In **worker windows** (`ui.open_window`) and **standalone scripts** (`launch_script`),
apply the shared SDK helpers so buttons match the desktop client:

```python
from neurorehab_plugin.button_style import configure_push_button, PUSHBUTTON_STYLESHEET

button = configure_push_button(QPushButton("Action", parent))
# or on a top-level window:
window.setStyleSheet("QMainWindow { background-color: #2e3338; }\n" + PUSHBUTTON_STYLESHEET)
```

`builder.add_button()` already uses this style. For hand-made `QPushButton` widgets,
call `configure_push_button()` (or rely on `WORKER_DIALOG_STYLESHEET` applied to
`builder._parent`).

### `PluginButton` handle

`set_enabled(bool)`, `set_label(str)`, `is_enabled()`.

---

## Host responsiveness (MUST)

**A plugin must never block access to the NeuroRehab desktop client.**

The host enforces this: plugin code always runs in a **worker subprocess**, and
while the host waits on IPC it **keeps pumping Qt events including mouse and
keyboard** so the user can still change tabs, select rows, use menus, and
**launch other plugins**. Hung or runaway workers are **killed** (and the
plugin may be quarantined).

### Author rules

| MUST | MUST NOT |
|------|----------|
| Keep `build_ui()` tiny — add/enable/label buttons only | Long HTTP loops, file I/O, or CPU work in `build_ui()` |
| Finish `build_ui()` in well under **~2 s** (worker configure/ready ~**45 s**; run/`build_ui` waits are unlimited — use Stop) | Call `open_window()`, `show_message()`, `launch_script()`, or `run_task()` from `build_ui()` |
| Prefer `selection_ui = "enable"` or `"none"` when labels are static | Rely on `rebuild` for a static launcher |
| Put heavy work in **button callbacks** | Assume the host will wait forever |
| Use `ui.run_task()` / `ui.open_window()` / `api.launch_script()` for long jobs | Block the worker entry point for minutes without a local UI |

`run()` / button callbacks may open worker-local dialogs and windows. That is
fine: those widgets live in the **worker process**, and NeuroRehab itself stays
clickable. Return from the entry point once the work is done or the window is
open; do not sit in a tight loop without `run_task` / your own Qt event loop.

If the host kills your worker for timeout, fix the plugin — do not ask users to
“wait for the plugin to finish” before using NeuroRehab.

### Subprocesses (analysis CLIs, helpers)

The worker’s **stdin is the host IPC pipe**. A child started with plain
`subprocess.Popen([...])` / `subprocess.run([...])` used to **inherit** that
stdin and could hang for many minutes (same command finished quickly outside
the plugin). The worker now defaults omitted / `None` stdin to `DEVNULL`.

| Prefer | Avoid |
|--------|--------|
| `subprocess.Popen(...)` / `run(...)` as usual (guard is automatic) | Assuming a hang means “analysis is just slow” |
| `from neurorehab_plugin import plugin_popen, plugin_run` for clarity | Passing the worker’s stdin through on purpose |
| `stdin=subprocess.PIPE` only when you write to the child | |

`api.launch_script()` already uses `stdin=DEVNULL`.

See also [Host refresh on selection](#host-refresh-on-selection) and
[Performance](#performance--many-api-calls).

---

## Host refresh on selection

When the user selects a row, NeuroRehab updates Information, History, and Related
first, then plugin UI:

1. Detail bundle loads (history, related, folders) — list highlight stays immediate.
2. **Cheap plugin path (sync):** install/enable host launchers; for
   `selection_ui = "enable"`, toggle existing `build_ui` buttons — **no worker**.
3. **Heavy path (debounced, cooperative):** only if a plugin needs
   `selection_ui = "rebuild"` or an initial `build_ui` / `on_select`. Worker
   calls run one plugin per event-loop turn and cancel if the selection moves on.

**Signature cache:** if selection, targeting, and entry `mtime` are unchanged
and the plugin zone already has content, `build_ui()` is skipped (no worker
round-trip). `on_select` plugins use a separate cache key. Call
`ui.clear()` when you need to force a full rebuild after changing only
in-memory state.

| Do | Don't |
|----|-------|
| `selection_ui = "none"` / `"enable"` when possible | Rebuild via worker for a static launcher |
| Fast, idempotent `build_ui()` (&lt; ~2 s) | `open_window()` in `build_ui()` |
| `window_builder_is_alive()` before reusing a stored `builder` | Touch `builder._parent` after the user closed the window |
| `enabled=` / `set_enabled()` for state | `launch_script()` in `build_ui()` |
| Heavy work in callbacks / `run_task` | Long API loops in `build_ui()` |
| Handle 0 rows when `selection_mode = optional` | Assume a row is always selected |
| Assume the host stays usable during your work | Expect NeuroRehab to freeze until you return |

---

## Performance — many API calls

Plugins that scan references, folders, or many rows (e.g. Experience → MEA) can
trigger **dozens of HTTP calls**. The SDK is optimized for that case:

| Mechanism | Role |
|-----------|------|
| `PluginTransport` keep-alive | Reuses one TCP connection per `PluginApi` |
| Auto-reconnect | Retries once after `ConnectionResetError`, etc. |
| `invoke_batch()` | Up to **50** read-only ops in one POST `/plugin/invoke/batch` |
| `pump_gui_events()` | Called after each response so worker Qt stays responsive |

```python
def _load_many(api: PluginApi, record_ids: list[int]) -> list[dict]:
    calls = [{"op": "get_entity_record", "args": [rid]} for rid in record_ids[:50]]
    return [r for r in api.invoke_batch(calls) if r is not None]
```

Rules of thumb:

- Use **`ui.run_task()`** for long CPU/network work in button callbacks.
- Inside `run_task`, call **`api.invoke_batch()`** rather than nested loops of single invokes.
- Do **not** call `ui.*` from inside the `run_task` worker function.
- Split batches of more than 50 operations into chunks.

See [examples/outgoing_references/](examples/outgoing_references/) — combine
`list_outgoing_reference_records` + `run_task` for file loading.

---

## Packaged NeuroRehab client

End users may run the **PyInstaller** build (`NeuroRehabDatabase.exe` on Windows,
`NeuroRehabDatabase.app` on macOS) instead of `python run_client.py`. Plugin
behavior is identical:

| Topic | Detail |
|-------|--------|
| Plugin data | `plugins/` next to the exe (fallback: `%LOCALAPPDATA%\NeuroRehabDatabase\plugins\` on Windows · `~/Library/Application Support/NeuroRehabDatabase/plugins/` on macOS) |
| Worker venv | `plugins/venvs/<id>@<version>/python` |
| SDK in packaged app | Copied into each plugin venv (`site-packages/neurorehab_plugin`) on sync |
| Wheels | Build plugin deps for **cp311** / Python **3.11.x** (same as client) |
| API connection | Server **address** + **port** at login (`http://` added automatically); default NAS port **32772** |
| Client debug log | `client.log` **next to the executable** (always; last session; full diagnostics; disable with `NR_CLIENT_LOG=0`) |
| Script launch log | `plugins/cache/<id>@<version>/.plugin_script_launch.log` (rich header + child stdout/stderr, faulthandler/warnings; overwritten each launch) |
| Worker stderr log | `plugins/cache/<id>@<version>/.plugin_worker.log` (header + worker stderr; overwritten each worker spawn) |

After installing a new client build, open the **Plugins** tab, review **To install** /
**To uninstall**, and click **Apply changes** to refresh local cache and venvs. Rebuild the
client after server/API changes: see repo `build/README.md`.

Host UX (no plugin code change required):

- **Dark theme** forced on all workstations (independent of OS light/dark mode).
- **High-contrast zones** — List (blue), History (purple), Edit (green), Panel (grey-blue).
- Entity tabs show **“Loading data…”** while the list bundle loads.
- Uploads show a **bottom-right progress panel** (same style as plugin install).
- History **Details** on create lists all filled attributes (including files uploaded after save).
- Login shows a **connection progress** dialog; unreachable NAS fails within ~20 s with an error message.

### macOS packaged client

Build on a Mac (`./build/build-macos.sh`). If the login dialog closes but nothing
appears, run the binary from Terminal to see errors:

```bash
cd dist/NeuroRehabDatabase
./NeuroRehabDatabase
```

Verify NAS reachability: `curl http://NAS-IP:32772/api/v1/health`

---

## External GUI scripts

```python
def run(api, context, ui):
    api.launch_script("mon_gui.py", detached=False)
```

Declare GUI libs in `requirements.txt`. See [examples/standalone_gui/](examples/standalone_gui/).

Env vars during execution: `NR_PLUGIN_ID`, `NR_PLUGIN_ROOT`, `NR_PLUGIN_PYTHON`,
`NR_PLUGINS_ROOT`.

---

## Publish & install

```powershell
.\prepare-publish.ps1
```

Verify **`publish/plugin.toml`**:

```toml
version = "1.0.0"             # bump for each new catalog release
selection_mode = "optional"   # active line, not commented
entry = "main.py"
```

Without `selection_mode`, default is `one_or_more` (button hidden without selection).
Without `version` on upload, the server rejects the package.

Install: **Plugins → Import plugin to database…** → `publish/` or zip of `publish/`.
In the table, check **To install** on the desired **version** row, then click **Apply changes**
to build the venv locally (`plugins/venvs/<id>@<version>/`).

### Plugins tab (workstation)

| Column | Meaning |
|--------|---------|
| **Plugin** | Name, package version, and scope (tables, sub-types, placement) |
| **Description** | Short summary from `plugin.toml` (`description`, required) |
| **Installed** | `installed` or `not installed` on this workstation (read-only) |
| **Last used** | Last launch / tab-button click (server catalog; `-` if never used) |
| **Last used by** | First name + Last name of the last user (`-` if never used) |
| **To install** | Cross toggle — mark this **version** for local install |
| **To uninstall** | Cross toggle — mark this **version** for local removal |
| **Favorite** | Personal shortcut (per signed-in user, per version) |
| **Download** | Complete project folder named after the plugin id (kit + sources at the root; no nested `dev-kit/`) |
| **Delete** | Remove this **version** from the server catalog (admins) |

Sections: **Favorites** and **Other plugins**. Inactive action columns are grayed per row.
Local state is saved in `machine_settings.json` (`enabled` list of `id@version` keys). The desktop client does
**not** call the server `set_plugin_enabled` endpoint for local installs.

---

## Security

See **[SECURITY.md](SECURITY.md)** — read-only API, server whitelist, scoped JWT,
worker isolation, and the non-blocking host contract. Test with a non-admin account.

---

## Regenerate SDK (maintainers)

```powershell
.\sync-sdk.ps1
```

```bash
./sync-sdk.sh
```

From repo `plugins/`:

```powershell
.\assemble-kit.ps1                              # sync SDK + VERSION + dist zip
.\assemble-kit.ps1 -OutputDir "C:\Projects\my_plugin" -PluginId "my_plugin"
```

Publish the shared kit for workstations:

1. `.\assemble-kit.ps1` → `plugins/dist/neurorehab-dev-kit.zip`
2. NeuroRehab → **Plugins → Publish dev-kit to server…**
3. Developers use **Download dev-kit…** and name the folder after their plugin id
