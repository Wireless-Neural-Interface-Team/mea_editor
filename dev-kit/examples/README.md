# Examples

Each folder is a **complete mini-plugin**. To try one:

1. Copy `plugin.toml` and `main.py` (and extra files) to **this project root**
   (the folder named after your plugin), or
2. Copy the whole example folder elsewhere, rename it to the plugin id, and run
   `setup-dev.ps1` there.

Then `.\prepare-publish.ps1` and **Import plugin to database…** with `publish/`.
Each example includes `version = "1.0.0"` in `plugin.toml` (bump it when publishing
a new catalog release). Do not put a nested `dev-kit/` folder inside the project.

| Folder | Pattern | Key manifest fields |
|--------|---------|---------------------|
| [home_buttons](home_buttons/) | Persistent Home-tab buttons | `placement = home`, `build_ui()`, `ZONE_HOME` |
| [standalone_gui](standalone_gui/) | PyQt window without selection | `selection_mode = optional`, `launch_script`, `configure_push_button` |
| [on_select_panel](on_select_panel/) | Auto Information button | `run_trigger = on_select`, `placement = record_panel` |
| [persistent_buttons](persistent_buttons/) | Always-visible buttons | `build_ui()`; see `selection_ui` in GUIDE |
| [worker_window](worker_window/) | Custom Qt in worker + reusable window | `build_ui()` + `open_window()` + `window_builder_is_alive()` |
| [scope_targeting](scope_targeting/) | Tables + sub-types + fields | `entity_keys`, `[[plugin.when]]` |
| [outgoing_references](outgoing_references/) | Read referenced MEA from Experience | `list_outgoing_reference_records`, `run_task` |
| [useless_website](useless_website/) | Embedded browser on The Useless Web | `launch_script`, `QWebEngineView`, `selection_mode = optional` |
| [form_file_assist](form_file_assist/) | Fill Add/Edit draft fields after Browse on a File | `on_file_chosen`, `suggested_values` |

The **project root** (`main.py` + `plugin.toml`, same folder as the plugin id)
is the default read-only manual button plugin — the simplest starting point.

**Language:** keep example code and any UI you copy in **English** (see
[GUIDE.md — Language](../GUIDE.md#language-english-only)).

### Performance tip

If your plugin loads data for many rows or references, use **`api.invoke_batch()`**
(see [GUIDE.md](../GUIDE.md#performance--many-api-calls)) inside **`ui.run_task()`**
rather than dozens of separate API calls in a loop.
