# NeuroRehab plugin dev kit

All-in-one project to build **read-only** NeuroRehab database plugins: embedded SDK,
starter code, and copy-paste examples.

**This folder is the plugin.** Rename it to the plugin id (for example `mea_viewer`),
then edit the files here. Do **not** keep a nested `dev-kit/` subdirectory — SDK,
scripts, `plugin.toml`, and `main.py` all live at this folder’s root. After
`prepare-publish`, import `publish/` into the database.

**Kit — 2026-11-11** — aligned with NeuroRehab client **1.1.0** / server **1.1.0**.
Rich-text images live on the NAS (`file_kind=rich_image`); File attributes
can show image thumbnails. Schema UX: defaults, uniqueness rules, Combo
fields, column filters, broader type migration, Manage actions, and an
optional plugin **form file suggest** hook (`examples/form_file_assist`).
`folder_tree` returns the folder-attribute tree the record panel shows
(read-only). `field_key_for_label` raises `ValueError` when several
attributes share a label unless `variant=` is passed. Duplicate file or
folder display names stay in the tree; open the file dict (`id`).
Inventory lists Table / Row ID / Subtype / Label (filter via column
headers, including Table). Search covers every visible attribute and adds
a column per match (black cell = attribute absent). Information shows the
selected row the same way as its table. **Open in table** replaces Edit,
Duplicate, and Actions preview on Inventory. Home retention has three
windows (Records / File versions / Schema trash).
Plugins run on table tabs and Home; they never attach to the **Inventory**
tab. Reference / Multi-reference attributes may target the **current table**
(self-reference) and its subtypes. Manage subtypes / Tables Sub-types panels
list subtypes by **Name** / **Label** (technical `variant_key` is not shown). Desktop
spreadsheet **Export…** / **Import…** (create table, create subtype, existing
subtype ≤10 rows) with File/Folder path upload; scalar attribute **type
migration** (Text/Number/Date/Time/Boolean + lists ↔ text/number) when all
values convert.
Reference Display fields may include Specific-subtype attributes when the
reference is subtype-restricted. Plugins stay **read-only** end-to-end (SDK +
server whitelist of **24** ops; no purge/CRUD/team writes). Worker subprocess stdin
guard — omitted stdin → `DEVNULL`, `plugin_popen` / `plugin_run`; plugin
**package versioning**: required `version` in `plugin.toml`, side-by-side
`id@version` installs; host stays interactive during plugin IPC — see GUIDE
Host responsiveness; concurrent plugin launches; shared automation rule-value
codec; unified exceptions / batch limit / display quotes; `form_layout` +
spreadsheet column-map public API; homogenized Home purge summary vs audit
`PURGE` details; English config/docs; `preferences` router documented;
English-only MEA sample manifest; `selection_ui` for faster row-select plugin
refresh; plugin local ids + Home `entity_keys`; CSV import encodings + trailing
empty columns; macOS update hardening; homogenized retention purge stats
without fake audit-deletion counters; bootstrap schema without `file_blob`;
in-app packaged client updates from Home; sha256-checked release zips;
finished retention purges recorded in the Audit log as `PURGE`; configurable
daily purge time on Home, default 23:59; Team ID / Role / Permissions columns
visible to administrators only; side-by-side plugin buttons fill the group-box
width equally; plugin group-box buttons can sit side by side or stacked via
`new_row`; toolbar launchers stay visible with `selection_mode = optional`;
one project folder named after the plugin id, no nested `dev-kit/`; incremental
Audit log fetch; background tab preload; audit log kept permanently by
retention purge; always-on `client.log` next to the program; script launch log
under `cache/<id>@<version>/`; English-only plugin authoring.

Target Python **3.11.7** (same as the NeuroRehab client). No system Python required.

**Language:** write **all** plugin text in **English** — `plugin.toml` name/description,
UI labels, messages, comments, and docstrings. See [GUIDE.md — Language](GUIDE.md#language-english-only).

**Host access:** NeuroRehab must stay usable while your plugin runs. Keep
`build_ui()` fast; put heavy work in button callbacks / `run_task` /
`open_window`. See [GUIDE.md — Host responsiveness](GUIDE.md#host-responsiveness-must).

---

## Quick start

1. **Get the kit** — **Plugins → Download dev-kit…**
   - Enter the **plugin id** as the folder name (`mea_viewer`, not `neurorehab-dev-kit`).
   - Choose a parent folder (e.g. Documents).
2. **Work in that folder** — it already contains everything to run and publish:

```powershell
cd mea_viewer          # named after your plugin
.\setup-dev.ps1        # .python/ + .venv/
.\smoke-worker.ps1     # optional: worker smoke test
```

3. Edit **`plugin.toml`** (`id` must match the folder name; set **`version`** for each publish; plus `name`, `description`, `entity_keys`, …).
4. Edit **`main.py`** (`run()` or `build_ui()`).
5. Add runtime libs to **`requirements.txt`** if needed (PySide6, numpy, …).
6. Publish and import into the database:

```powershell
.\prepare-publish.ps1
# NeuroRehab → Plugins → Import plugin to database… → publish/
# Then: To install on that version row + Apply changes (creates venv on the workstation).
```

Bump `version` in `plugin.toml` when you want a new catalog entry that can run
**side by side** with an older install (`id@version` on the workstation). Re-uploading
the same `id` + `version` replaces that package only.

**Download for editing** on an existing catalog plugin does the same thing: one
folder named after the plugin, kit + plugin sources merged at the root (no
`dev-kit/` subfolder).

Full reference: **[GUIDE.md](GUIDE.md)** · Security: **[SECURITY.md](SECURITY.md)** · Patterns: **[examples/](examples/)**

---

## What is in this folder

| Path | Role |
|------|------|
| `plugin.toml` | Your plugin manifest (start here) |
| `main.py` | Default entry point — read-only button plugin |
| `requirements.txt` | Runtime deps → worker venv on each client |
| `requirements-dev.txt` | Local dev (SDK editable install) |
| `VERSION` | Kit sync date (maintainers: updated by `assemble-kit.ps1`) |
| `CHANGELOG.md` | Kit release notes vs NeuroRehab client |
| `examples/` | Ready-made patterns (copy a folder or cherry-pick code) |
| `neurorehab_plugin/` | SDK — dev only, **not** published |
| `GUIDE.md` | Complete developer reference |
| `setup-dev.ps1` / `.sh` | Local environment |
| `prepare-publish.ps1` / `.sh` | Build `publish/` for **Import plugin to database…** |
| `smoke-worker.ps1` / `.sh` | Verify worker subprocess loads your entry |
| `sync-sdk.ps1` / `.sh` | Maintainers: refresh SDK from repo root |

The `publish/` folder is generated locally — never commit it.
Nothing else is required to run the plugin locally or import it to the server.

---

## Choose a pattern

| Goal | Example folder |
|------|----------------|
| Button + read selected rows | Root `main.py` (default) |
| Standalone PyQt window (no selection) | [examples/standalone_gui/](examples/standalone_gui/) |
| Auto Information panel on row click | [examples/on_select_panel/](examples/on_select_panel/) |
| Buttons always visible (`build_ui`) | [examples/persistent_buttons/](examples/persistent_buttons/) |
| Custom Qt window in worker (reopen after close) | [examples/worker_window/](examples/worker_window/) |
| Limit to tables / sub-types | [examples/scope_targeting/](examples/scope_targeting/) |
| Read a referenced record (outgoing) | [examples/outgoing_references/](examples/outgoing_references/) |

Copy an example: duplicate its `plugin.toml` + `main.py` to **this project root**.

---

## Runtime (one sentence)

Plugins with `requirements.txt` run in an isolated **worker subprocess**
(`plugins/venvs/<plugin_id>/python.exe`, piped I/O). The NeuroRehab
GUI renders authorized zones and dialogues; plugin code never writes to the database.
Selection changes trigger a single batched UI refresh (no flicker). Heavy read loops
should use **`invoke_batch()`** (see [GUIDE.md — Performance](GUIDE.md#performance--many-api-calls)).

See [GUIDE.md — Architecture](GUIDE.md#architecture).

---

## Maintainers (repo root)

Refresh the embedded SDK and kit date:

```powershell
cd plugins
.\assemble-kit.ps1                    # sync SDK + bump VERSION in the shared kit
.\assemble-kit.ps1 -OutputDir "C:\Projects\my_plugin" -PluginId "my_plugin"
```

Or from this folder only: `.\sync-sdk.ps1`

Distribute the whole **project folder** via the app (flat layout, no nested kit):

1. Maintainer: `cd plugins ; .\assemble-kit.ps1` → `plugins/dist/neurorehab-dev-kit.zip`
2. Admin: **Plugins → Publish dev-kit to server…**
3. Developers: **Plugins → Download dev-kit…** → name the folder after the plugin id
