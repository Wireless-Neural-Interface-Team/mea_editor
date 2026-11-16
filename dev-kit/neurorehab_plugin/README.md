# NeuroRehab Plugin SDK

**Read-only** Python package for developing NeuroRehab database plugins.

## Installation

```bash
uv pip install -e ./neurorehab_plugin
```

## Execution model

On end-user workstations, plugins with `requirements.txt` run in a **dedicated
worker subprocess** (`plugins/venvs/<id>@<version>/python.exe`). The
NeuroRehab GUI renders plugin zones and dialogues. During row selection, UI events
from the worker are buffered and applied in one batch on the host.

Declare every runtime dependency in `requirements.txt` (including Qt if you
manipulate widgets in `ui.open_window()`). Venvs are created with **uv**
(`uv venv` + `uv pip install`) on each workstation when the user clicks
**Apply changes** in the Plugins tab.

On the workstation: upload via **Import plugin to database…**, then check **To install** and
click **Apply changes** (local state in `machine_settings.json`).

Worker windows are destroyed when
closed; reuse a stored `builder` only after `window_builder_is_alive(builder)`.

## Performance

- **`PluginTransport`** uses HTTP **keep-alive** (one connection per `PluginApi`).
- Transient network errors trigger **one automatic reconnect**.
- Prefer **`invoke_batch()`** (max 50 ops) for heavy read loops instead of many
  separate `get_record` / `list_files` calls.
- **`pump_gui_events()`** runs after each HTTP response so worker Qt stays responsive.
- Child processes: the worker defaults omitted `stdin` to `DEVNULL` (use
  `plugin_popen` / `plugin_run` or plain `subprocess` — do not inherit IPC stdin).

## Example

```python
from neurorehab_plugin.api import PluginApi
from neurorehab_plugin.context import PluginContext
from neurorehab_plugin.ui import PluginUi, ZONE_RECORD_PANEL


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    records = context.applicable_records or context.selected_records
    if not records:
        ui.clear()
        return
    record = records[0]
    fields = api.get_fields(record, ["status", "label"])
    ui.add_button(
        f"Summary #{record.id}",
        lambda: ui.show_message(
            "Summary",
            "\n".join(f"{k}: {v}" for k, v in fields.items()),
        ),
        zone=ZONE_RECORD_PANEL,
    )
```

## Security

- No database writes (`PluginWriteForbiddenError` on attempt)
- HTTP limited to `/api/v1/plugin/*`
- Server: read-only operation whitelist
- Records linked to the selection are readable (references, links)
- Worker process isolates plugin libraries from the desktop application

See `plugins/dev-kit/SECURITY.md` in the repository.

## Package files

| File | Role |
|------|------|
| `api.py` | Data access (`PluginApi`) — read-only, `invoke_batch` |
| `context.py` | Context and selection (`applicable_records`) |
| `scope.py` | Manifest targeting (`[[plugin.when]]`) |
| `local_files.py` | Temp files, `pump_gui_events`, worker window focus |
| `button_style.py` | Shared button stylesheet (`configure_push_button`, same look as client) |
| `ui.py` | UI contract (zones, buttons, `window_builder_is_alive`) |
| `manifest.py` | `plugin.toml` parsing (`version`, `run_trigger`, etc.) |
| `transport.py` | Plugin HTTP keep-alive (internal) |
| `worker_main.py` | Worker subprocess entrypoint (used by NeuroRehab client) |
| `worker_protocol.py` | Host ↔ worker JSON protocol |
| `script_launcher.py` | Launch external GUI scripts in plugin venv |
| `safe_subprocess.py` | Worker stdin guard + `plugin_popen` / `plugin_run` |
| `errors.py` | Exceptions |

## Version

`PLUGIN_API_VERSION = 1` — set `api_version = 1` in your `plugin.toml`.

Package releases use a separate **`version`** field (`MAJOR.MINOR.PATCH`, required
on upload). Multiple package versions of the same plugin id can be installed
side by side as `id@version`.

Packaged client: distribute plugin wheels for **Python 3.11.x** (cp311). See
`plugins/dev-kit/GUIDE.md` — Packaged NeuroRehab client.
