# Dev kit — current compatibility

| Component | Version |
|-----------|---------|
| Kit stamp (`VERSION`) | **2026-11-11** |
| Client version (`CLIENT_VERSION`) | **1.1.0** |
| Server version (`SERVER_VERSION`) | **1.1.0** |
| Python (dev + client + plugin venvs) | **3.11.7** |
| `PLUGIN_API_VERSION` / `api_version` in `plugin.toml` | **1** |
| Package `version` in `plugin.toml` | **required on upload** (`MAJOR.MINOR.PATCH`) |
| PySide6 in client | 6.11.x |
| Default API port (NAS) | **32772** |
| Kit zip on NAS storage | `assets/dev-kit.zip` |

## 2026-11-11 — Version **1.1.0** (rich text images, schema UX)

- `CLIENT_VERSION` **1.1.0** and `SERVER_VERSION` **1.1.0** (both bumped:
  rich-text images on NAS / download policy, schema defaults & uniqueness,
  Combo fields, type migration, column filters, Manage-actions / form UX).
  `min_server_version` is **1.1.0**. Redeploy the server image before
  publishing the client.
- Rich text: pasted/inserted images upload as `entity_record_file` rows with
  `file_kind=rich_image`; HTML stores `neurorehab-file:{logical_key}` (no
  base64 in JSONB). Viewers of the row can load those images without
  `can_download_files`. File attributes show inline image thumbnails when
  download is allowed.
- Schema / data entry: optional **default values**, **uniqueness rules**,
  **Combo** attributes, broader type migration (lists ↔ text/number, team
  member → multi), per-column list filters, Related-label checkboxes,
  Manage actions on every subtype, plugin **form file suggest** draft hook
  (`examples/form_file_assist`), and non-modal Add/Edit windows.
- Inventory: list stays on catalog columns (Table / Row ID / Subtype /
  Label); filter by table via the **Table** column header (the separate
  Table combo is removed). A search match adds a column; a **black** cell
  means that row does not have the attribute. Manage subtypes button rows
  use transparent hosts so they keep the zone background.
- Plugin SDK whitelist is **24** read ops (`get_record_file_by_path` added
  for rich-image / path lookup). `PLUGIN_API_VERSION` stays **1**.
- Retention **purge** updated for rich-text images and **three Home
  windows**: Records (rows + folder/file trash including `rich_image`),
  File versions, Schema trash (tables / subtypes / attributes / actions).
  Orphan NAS cleanup also keeps keys still cited by `neurorehab-file:` in
  live or revision rich-text HTML. Audit `PURGE` details list all three
  windows. Audit log stays permanent; catalogue plugins are still not
  removed by purge. Unit + file-storage orphan tests re-verified.
- Docs aligned (`Features_Guide`, `ARCHITECTURE`, `deploy/README`,
  `build/README`, READMEs, GUIDE). Build hidden imports cover rich text /
  defaults / uniqueness / column filters / file preview.
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.1.0** (`min_server_version` **1.1.0**).

## 2026-10-23 — Version **1.0.7** (Inventory search, folder tree)

- `CLIENT_VERSION` **1.0.7** and `SERVER_VERSION` **1.0.7** (both bumped:
  Inventory `search_text` / `attributes`, and related-row scans no longer
  read a choice list as a record id). `min_server_version` is **1.0.7**.
  Redeploy the server image before publishing the client.
- Inventory search covers every attribute of rows the account may view,
  including hidden columns and subtype attributes not on screen. Each
  match becomes a column; a struck-through cell means the row does not
  have that attribute. **Open in table** replaces Edit, Duplicate, and
  Actions preview. Information uses the same form as the row's own table:
  shared attributes plus that subtype only, including files and folders.
- Plugin SDK: `folder_tree` returns the folder-attribute tree the record
  panel shows (read-only; built from `list_folders` + `list_files`). A
  file dict from that tree is input for `open_file` / `save_file_to_temp`
  / `download_file`. Duplicate display names stay in the tree; use the
  file `id`. `field_key_for_label` raises `ValueError` when several
  attributes share a label unless `variant=` is passed. Server whitelist
  stays **22** read ops.
- Docs aligned (`Features_Guide`, help tip, tutorials, `GUIDE.md`,
  `DEVELOPMENT.md`, READMEs, `build/README`).
- Retention **purge unchanged** (audit log stays permanent; catalogue
  plugins are still not removed by purge). Unit + scheduler purge tests
  re-verified.
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.7** (`min_server_version` **1.0.7**).

## 2026-10-13 — Version **1.0.6** (Inventory selection)

- `CLIENT_VERSION` **1.0.6**. `SERVER_VERSION` stays **1.0.5** (no API change;
  no server rebuild). `min_server_version` stays **1.0.5**.
- Inventory: clicking a row highlights it immediately. Field values, history,
  and related rows load in the background, the same way as a table tab.
- Docs aligned (`Features_Guide`, help tip, tutorials, READMEs, `build/README`).
- Kit stamp unchanged (**2026-10-13**); SDK re-synced. Windows client rebuild
  ships `client_manifest.json` **1.0.6** (`min_server_version` **1.0.5**).

## 2026-10-13 — Version **1.0.5** refresh (access scope)

- Still **client 1.0.5 / server 1.0.5** (no version bump).
- Storage keys whose record row is gone are no longer treated as a global id
  (no cross-table file read or write).
- Entity-tab bundles omit labels and links for tables the account cannot view.
- Selection-scoped plugins no longer receive out-of-scope file names, folder
  counts, reference labels, or the full table row count. Reference formatting
  stays on the declared target table. `stored_file_exists` and storage byte
  totals reject keys that are not record paths.
- Retention **purge unchanged** (orphans are still removed by storage-path
  reference, not by record id; audit log stays permanent; catalogue plugins
  are still not removed by purge). Unit + scheduler purge tests re-verified.
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.5** (`min_server_version` **1.0.5**).

## 2026-10-13 — Version **1.0.5** (plugins off Inventory)

- `CLIENT_VERSION` **1.0.5** and `SERVER_VERSION` **1.0.5** (both bumped in
  lockstep for this release).
- Desktop: plugins never attach to the **Inventory** tab (toolbar, Information,
  related rows, plugin panel), even when `entity_keys` is omitted or the
  plugin names Inventory. Table tabs and Home are unchanged.
- Docs aligned (`Features_Guide`, help tip, tutorials, `GUIDE.md`,
  `DEVELOPMENT.md`, READMEs, `build/README`).
- Retention **purge unchanged** (audit log stays permanent; catalogue plugins
  are still not removed by purge). Unit + scheduler purge tests re-verified.
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.5** (`min_server_version` **1.0.5**).

## 2026-10-10 — Version **1.0.4** refresh (File/Folder rename)

- Still **client 1.0.4 / server 1.0.4** (no version bump).
- Desktop: **Rename…** for Folder-field files/folders/subfolders, and for
  File-field display names (edit form; applied on Update).
- Server invoke: `rename_record_folder` / `rename_record_file_by_id` (edit ACL);
  **not** in `PLUGIN_READONLY_OPS` (still **22** read ops).
- Plugin SDK: blocks `rename_*` write prefix (defense in depth). GUIDE /
  SECURITY / DEVELOPMENT / plugins README updated.
- Docs: `Features_Guide`, `build/README`; kit stamp refreshed; SDK re-synced.
- Windows client rebuild ships `client_manifest.json` **1.0.4**
  (`min_server_version` **1.0.4**).

## 2026-10-10 — Version **1.0.4** (client + server aligned)

- `CLIENT_VERSION` **1.0.4** and `SERVER_VERSION` **1.0.4** (both bumped in
  lockstep for this release).
- Deep verification: fixed subtype-combo / record-info test fakes after UI
  refresh paths (`get_entity_def`, `tab.entity`); PostgreSQL integration
  fixtures skip cleanly when the local Docker DB is down; added unit coverage
  that the Reference target combo lists the **current table** first.
- Follow-up from pre-release audit: Reference target combo again includes
  **Team** (avoids rewriting legacy team-refs on edit); schema Tree draws
  self-reference loops; Features Guide wording clarified; Word lock file
  `docs/~$atures_Guide.md` removed.
- Docs aligned (`Features_Guide`, root / ARCHITECTURE / build / plugins
  READMEs); kit stamp refreshed; SDK re-synced.
- Windows client rebuild ships `client_manifest.json` **1.0.4**
  (`min_server_version` **1.0.4**).

## 2026-10-09 — Version **1.0.4** (self-referencing Reference)

- `CLIENT_VERSION` **1.0.4** (`SERVER_VERSION` was still **1.0.0** that day).
- Reference / Multi-reference target combo includes the **current table**
  (listed first) so a row can link to another row of the same table; subtype
  scope and display fields apply to that table's subtypes as usual.
- Docs aligned (`Features_Guide`, root / ARCHITECTURE / build / plugins
  READMEs); subtype/attribute slides regenerated.
- Retention **purge unchanged** (still scrubs dangling reference / multi-
  reference ids via `scrub_references_to_targets`, including self-references).
  Unit + scheduler purge tests re-verified.
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.4** (`min_server_version` **1.0.0**).

## 2026-10-09 — Version **1.0.3** (subtype Key column)

- `CLIENT_VERSION` **1.0.3** (`SERVER_VERSION` stays **1.0.0**).
- **Manage subtypes…** and Tables → Sub-types list **Key** (`variant_key`)
  instead of the internal numeric id; Name unchanged. Uniqueness stays
  per table (`UNIQUE(entity_id, variant_key)`).
- Docs aligned (`Features_Guide`, root / ARCHITECTURE / build / plugins
  READMEs); subtype slides regenerated.
- Retention **purge unchanged** (soft-deleted subtypes, `variant_id` clear on
  remaining active rows). Unit + scheduler purge tests re-verified.
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.3** (`min_server_version` **1.0.0**).

## 2026-10-05 — Version **1.0.2** refresh (kit + build + zip)

- `SERVER_VERSION` corrected back to **1.0.0** (was mistakenly bumped to 1.0.2).
- Docs aligned (root / ARCHITECTURE / Features Guide / plugins READMEs).
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.2** (`min_server_version` **1.0.0**).

## 2026-10-05 — Version **1.0.2** (spreadsheet + scalar migration)

- `CLIENT_VERSION` **1.0.2** (`SERVER_VERSION` stays **1.0.0**).
- Desktop **Export…**: Excel/CSV of all table + subtype attributes; visible or
  selected rows; optional File/Folder attachments into `<file>_files` next to
  the spreadsheet (relative paths in cells).
- Desktop **Import…** on an existing subtype (max **10** rows/run); dry-run of
  values + File/Folder paths before any create; choice values must already
  exist (no list extension).
- Import when **creating a table** (table + subtype + attributes from columns)
  and when **creating a subtype**; File/Folder local paths supported on all
  spreadsheet imports (absolute or relative to the spreadsheet folder).
- Scalar attribute **type migration** (Text / Number / Date / Time / Boolean):
  preview → convert when compatible, else refuse with incompatibilities.
  Invoke ops: `preview_entity_field_migration` /
  `preview_variant_field_migration`.
- Docs aligned (`Features_Guide`, root / build / ARCHITECTURE / plugins READMEs).
- Full suite: **709** passed, **1** skipped (no failures).
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.2**.

## 2026-10-05 — Deep verification / test hardening (still **1.0.0**)

- Full suite: **703** passed, **6** skipped (no failures).
- Fixed automation unit fake for runtime journal
  (`_log_automation_execution` on `_FakeAutomationDB`).
- Fixed `test_pg_errors` so the temporary `psycopg` stub no longer leaks into
  later PostgreSQL integration tests.
- Re-verified Reference display fields from Specific subtypes (unit + picker /
  schema wiring) and retention purge integration against live PostgreSQL.
- Docs: Synology README aligned with additive `core/db/migrations.py`; Features
  Guide stamp; plugins README points at kit examples (removed dead MEA path).
- Kit stamp refreshed; SDK re-synced; Windows client rebuild ships
  `client_manifest.json` **1.0.0**.
- `build-windows.ps1` treats `uv` stderr progress as non-fatal (exit code wins).
- macOS build parity: `build-macos.sh` verifies onedir **and** `.app`, restores
  execute bits, keeps manifests/host_python in sync; `prepare-host-python.sh`
  probes `uv pip` like Windows; `client.spec` sets `CFBundleVersion` /
  `LSMinimumSystemVersion`. Run `./build/build-macos.sh` **on a Mac** to ship
  the `.app` (no cross-compile from Windows).

## 2026-10-02 — Reference display fields from specific subtypes (still **1.0.0**)

- Reference / Multi-reference **Display fields** may include attributes of the
  selected **Specific subtypes** (not only shared table attributes + Subtype
  pseudo-key `__variant__`). Entire-table scope stays table-only.
- UI: `ReferenceDisplayFieldsPicker` reloads when the subtypes picker changes;
  schema dialogs (table + subtype attributes) wired via `selectionChanged`.
- Backend: `_validate_reference_field_config` and `record_display_label` accept
  / resolve subtype attribute keys when `target_variant_ids` is set (same rule
  as cross-table automations).
- Docs: `Features_Guide.md` (Links + Automatic actions), `ARCHITECTURE.md`
  (reference config + automations), admin slides / tutorials regenerated.
- Retention **purge unchanged** (still scrubs dangling reference record ids
  only; orphaned display keys are ignored at render / rejected on next edit).
  Unit + scheduler purge tests re-verified.
- Versions unchanged: `CLIENT_VERSION` **1.0.0**, `SERVER_VERSION` **1.0.0**.
- Kit stamp refreshed; Windows client rebuild ships `client_manifest.json`
  **1.0.0**.

## 2026-10-01k — Keep-alive / remote-poll fix (still **1.0.0**)

- Desktop HTTP transport retries once on a fresh connection after a dropped
  keep-alive (`RemoteDisconnected` and similar), so the **Connection lost —
  retrying…** banner no longer flashes on every other 8 s remote-change poll.
- API uvicorn `timeout_keep_alive` raised to **75 s** (was default 5 s).
- Docs: `ARCHITECTURE.md`, `Features_Guide.md`, `build/README.md`, `client/README.md`.
- Versions unchanged: `CLIENT_VERSION` **1.0.0**, `SERVER_VERSION` **1.0.0**.
- Windows client rebuild ships `client_manifest.json` **1.0.0**.

## 2026-10-01j — Version **1.0.0** (stable)

- **First stable release:** `CLIENT_VERSION` **1.0.0**, `SERVER_VERSION` **1.0.0**.
- Deep re-verification: plugins remain **read-only** end-to-end
  (`PLUGIN_READONLY_OPS` = **22** ops, no write-like names; SDK prefix blocks;
  HTTP `/api/v1/plugin/*` only; JWT scope authoritative; soft-deleted rows
  denied; host IPC buttons-only; worker subprocess isolation). Audit: **0**
  write-like client ops leaked into the plugin whitelist; purge / trash /
  CRUD ops all rejected for plugins.
- Retention purge re-verified (unit + integration): daily scheduler + Home
  manual, advisory lock, preview, hard-delete of expired soft-deleted data,
  audit `PURGE` event, audit log never purged.
- Docs aligned (`Features_Guide`, `build/README`, kit README); kit SDK
  re-synced; Windows client rebuild ships `client_manifest.json` **1.0.0**.

## 2026-10-01i — Security verification / readiness / kit+build

- Deep security pass: plugins remain **read-only** end-to-end (SDK prefix
  blocks, HTTP `/api/v1/plugin/*` only, server `PLUGIN_READONLY_OPS` whitelist
  of **22** ops with no write-like names, JWT `allowed_record_ids` authoritative,
  host IPC allowlist buttons-only, worker subprocess isolation).
- `/health/ready`: optional purge/storage enrichment must not flip readiness to
  503 after a successful `SELECT 1` (tuple/dict row safe).
- Sync isolation test updated for `_sync_enabled_plugin(..., progress=…)`.
- `CLIENT_VERSION` **0.9.29**, `SERVER_VERSION` **0.9.16**.
- Kit SDK re-synced; **217** plugin unit tests + **32** HTTP security tests green.

## 2026-10-01h — Reliability / diagnostics / retention cascade

- `CLIENT_VERSION` **0.9.28**, `SERVER_VERSION` **0.9.15**.
- Table soft-delete **cascades** active rows (shared `deleted_at`); restore
  restores those cascaded rows (pre-trashed rows stay trashed).
- Plugin worker stderr → `.plugin_worker.log`; script launch log rotation;
  venv failures → `.venv_install.log`.
- Client update: plugins moved **after** atomic rename; lock-enum failure
  refuses update; helper must stay alive before quit.
- Offline banner + entity Retry; startup preference sync surfaced; plugin
  quarantine/venv banners + Clear error & retry.
- Audit list capped (500/2000); plugin zip stream-to-disk; upload/zip limits;
  pool health-check + shutdown `close_pool`; invoke errors sanitized; plugin
  catalog gated by `can_use_plugins`; first-admin advisory lock; JWT default
  **120** min.
- Explicitly **not** changed (user request): client `/invoke/batch` limit,
  HTTPS login force, lockout TTL.
- Kit SDK re-synced; **666** unit tests green.

## 2026-10-01b — Docs timeout drift / prepare-publish packages

- GUIDE: `build_ui` host timing corrected — worker configure/ready ~**45 s**,
  run/`build_ui` waits are unlimited (Stop), not a 15 s hard kill.
- `prepare-publish`: also copies root Python packages (`*/__init__.py`),
  still excluding `.venv`, `__pycache__`, `examples`, SDK, etc.
- SECURITY: note that `os.system` / `asyncio` subprocesses are outside the
  stdin `DEVNULL` guard.

## 2026-10-01 — Verification pass (docs / kit / build)

- Full regression: **661** unit tests green (quarantine test updated for
  `id@version` instance keys used by `set_machine_enabled`).
- Packaged `client.log` confirmed next to the executable (`frozen=True`).
- Docs aligned to **0.9.27** / **0.9.14**: `build/README.md`, Features Guide,
  client / plugins README paths (`cache/<id>@<version>/`).
- Kit stamp refreshed; SDK re-synced from `neurorehab_plugin/`; Windows client
  rebuild ships `client_manifest.json` **0.9.27**.

## 2026-09-11g — Worker subprocess stdin guard

- `CLIENT_VERSION` **0.9.27** (`SERVER_VERSION` stays **0.9.14**).
- Plugin worker installs a `subprocess.Popen` guard so omitted / `None` stdin
  becomes `DEVNULL`. Children no longer inherit the host IPC stdin pipe (that
  hang looked like a multi-minute “slow” analysis while the same CLI finished
  quickly outside the worker).
- Public helpers: `plugin_popen` / `plugin_run` from `neurorehab_plugin`.
- GUIDE / SECURITY updated; kit SDK re-synced from `neurorehab_plugin/`.

## 2026-09-11f — Plugin package versioning

- Plugins declare a package **`version`** in `plugin.toml` (semver-like
  `MAJOR.MINOR.PATCH`). Upload requires it; local omit defaults to `1.0.0`.
- Catalog identity is `(id, version)`: re-upload replaces that version only;
  a new version is a separate installable row.
- Workstations install side by side under `id@version` (cache, venv, workers,
  favorites, host button labels `Name (vX.Y.Z)`).
- GUIDE / README / starter `plugin.toml` / examples updated; kit SDK re-synced
  from `neurorehab_plugin/`.

## 2026-09-11e — Concurrent plugin launches

- `CLIENT_VERSION` **0.9.26** (`SERVER_VERSION` stays **0.9.14**).
- Host accepts other plugins' `run` / button clicks while a plugin UI session
  is already open (deferred out of `processEvents`, then started). Same-plugin
  clicks are queued on that worker. Nested `build_ui` refresh is still skipped.
- Win32 foreground lock is depth-counted so concurrent sessions do not unlock
  each other early; window handoff retries while another session is active.

## 2026-09-11d — Host must stay responsive during plugins

- `CLIENT_VERSION` **0.9.25** (`SERVER_VERSION` stays **0.9.14**).
- Host IPC wait pumps **user input** so NeuroRehab stays clickable while a
  plugin worker runs; `build_ui` also pumps (still without Win32 foreground
  lock). (Historical note: a **15 s** `build_ui` hard timeout was documented
  here; current host uses ~**45 s** configure/ready and unlimited
  run/`build_ui` waits — see 2026-10-01b.)
- GUIDE: new **Host responsiveness (MUST)** section; SECURITY / README /
  `PluginUi` docs updated. Kit SDK re-synced from `neurorehab_plugin/`.

## 2026-09-11c — Code cleanup / shared modules

- `CLIENT_VERSION` **0.9.24** (`SERVER_VERSION` stays **0.9.14**).
- Shared automation value codec: `core/services/automation_rule_values.py`
  (desktop editor + history formatting).
- Unified `IntegrityError` / `PgGrantWarning` (client re-exports core),
  `APP_DISPLAY_NAME`, and `INVOKE_BATCH_LIMIT` (50) for client + plugin batch.
- Desktop: `form_layout.py`, `spreadsheet_column_map.py`, `field_actions/` package;
  `RemoteDatabase` cache mutation sets at module level; dead folder kwargs removed.
- Audit/UI labels: ASCII `quote_label()` instead of French guillemets in
  `meta_repository` / `meta_automations`.

## 2026-09-11b — Homogenize docs / purge UI / kit / build

- `CLIENT_VERSION` **0.9.23** (`SERVER_VERSION` stays **0.9.14**).
- Retention purge: shared `format_purge_home_summary` so Home dialog counts
  match audit `PURGE` details (same stats keys).
- Docs/config English homogenization: root `.env.example`,
  `build/requirements-build.txt`; `server/README.md` + `ARCHITECTURE.md`
  list `preferences` router; Features Guide stamped for 0.9.23.
- MEA sample `plugin.toml` English-only (name/description/comments).
- Kit stamp refreshed via `assemble-kit.ps1`; SDK re-synced from
  `neurorehab_plugin/`.

## 2026-09-11 — Cleanup pass (docs / kit / purge / build)

- `CLIENT_VERSION` **0.9.22** (`SERVER_VERSION` stays **0.9.14**).
- Removed obsolete shims (`server/deps.py`, `server/routers/invoke_common.py`),
  legacy tutorial generators/copies, unused slide assets, and dead client/core
  helpers / compat aliases.
- `client/domain/constants_meta.py` is now a re-export of
  `core.models.constants_meta` (same pattern as `models.py`).
- Docs aligned: `ARCHITECTURE.md` / `README.md` / `server`+`client` READMEs /
  purge wording (SQL tables vs stats keys) / Synology `TZ` comment /
  admin tutorial purge slides.
- Kit stamp refreshed via `assemble-kit.ps1`; SDK re-synced from
  `neurorehab_plugin/`.

## 2026-09-10c — Plugin local ids + Home table access

- Plugins only see **table-local** record ids (`#N` / `local_id`), never the
  global primary key. Reference field values in `data` are local ids too.
- `PluginApi` methods that take a record id accept an optional `entity_id`
  (defaults to the active table) so the server can resolve local → global.
- Home plugins: declare readable tables with `entity_keys` in `plugin.toml`.
  Access is the intersection of that declaration and the user's live view
  rights (`allowed_entity_ids` in the plugin JWT). Omit `entity_keys` for
  UI-only Home buttons (no row data).
- GUIDE / DEVELOPMENT / `examples/home_buttons` updated; kit SDK re-synced.

## 2026-09-10b — Selection UI performance (`selection_ui`)

- SDK `manifest.py`: `selection_ui` (`none` / `enable` / `rebuild`) plus
  helpers `selection_ui_mode` / `selection_affects_ui` /
  `selection_needs_worker_rebuild`. Legacy `ui_depends_on_selection` still
  maps to `none` / `rebuild`.
- Host (client): cheap launcher / enable-only sync on row select; heavy
  `build_ui` / `on_select` worker work is debounced and run cooperatively
  (one plugin per event-loop turn).
- GUIDE: document `selection_ui`, update “Host refresh on selection”.
- Starter `plugin.toml` comments for `selection_ui`.
- Kit SDK re-synced from repo `neurorehab_plugin/`.

## 2026-09-10 — Client 0.9.21 (Mac hardening + CSV import)

- `CLIENT_VERSION` **0.9.21** (`SERVER_VERSION` stays **0.9.14**).
- macOS packaged updates: restore execute bits after zip extract, unwrap
  `.app` → `Contents/MacOS`, relaunch via `open -n`, lock probe via `ps`
  (no `/proc`).
- CSV subtype import: auto-detect encodings (UTF-8 / Windows-1252 /
  MacRoman / …); trim trailing empty header columns like `.xlsx`.
- Plugin venv helpers prefer `bin/python` or `bin/python3` on POSIX.
- Kit stamp refreshed via `assemble-kit.ps1`.

## 2026-09-10 — Homogenize purge / build / kit (no migrations)

- `CLIENT_VERSION` **0.9.20**, `SERVER_VERSION` **0.9.14**.
- Retention purge: drop always-zero `audit_logs` / `snapshots` stats and dead
  audit-deletion helpers; `hard_purge_*` / `purge_expired_automation_rules`
  no longer pretend to remove audit history (journal stays permanent).
- Bootstrap schema: remove unused `file_blob` BYTEA table (NAS paths only).
  Fresh empty DB required — no runtime migrations.
- Client cleanup: removed deprecated widget row-action helpers, obsolete
  folder-tree preload no-op, one-shot mixin extract scripts, and unused
  `storage_key_for_platform`. Build hidden imports cover list-action
  delegate, spreadsheet export, and `subprocess_env`.
- `.gitignore`: ignore `build/cache/`, `build/client/`, `plugins/dist/`.
- Kit stamp refreshed via `assemble-kit.ps1`.

## 2026-09-10 — Spreadsheet subtype import (client); SDK stays read-only

- Desktop: create a subtype with optional Excel/CSV row import (openpyxl).
- Plugins cannot import or write: SDK blocks `import_*`, `create_*`, team
  name-part lookups (`list_team_member_name_parts`), etc.; server
  `PLUGIN_READONLY_OPS` unchanged (read-only).
- Kit docs (GUIDE / SECURITY / DEVELOPMENT) clarify Forbidden list.
- No database migrations — fresh empty DB only (`core/db/schema.py`).

## 2026-09-09 — Client 0.9.19 (client-only bump)

- `CLIENT_VERSION` bumped to **0.9.19** (`SERVER_VERSION` stays **0.9.13**).
- Update helper runs from a staged ``.nr_update_runtime_*`` copy of ``host_python``
  (avoids missing ``python311.zip`` under ``*_new`` / Desktop sync).
- Verify ``python311.zip`` is present and readable before launching the helper.

## 2026-09-08 — Client 0.9.18 (client-only bump)

- `CLIENT_VERSION` bumped to **0.9.18** (`SERVER_VERSION` stays **0.9.13**).
- Windows update: no PowerShell lock probe; helper is `pythonw` only;
  no console windows during apply / relaunch.

## 2026-09-08 — Client 0.9.17 (client-only bump)

- `CLIENT_VERSION` bumped to **0.9.17** (`SERVER_VERSION` stays **0.9.13**).

## 2026-09-08 — Client 0.9.16

- `CLIENT_VERSION` bumped to **0.9.16** (`SERVER_VERSION` stays **0.9.13**).
- Client updates: sha256 only (no HMAC); continuous Update progress animation;
  Windows update helper uses `pythonw` (no console flash).
- Fresh bootstrap schema without `client_release.signature`.

## 2026-09-08 — Fresh bootstrap (no migrations)

- Confirmed: no Alembic / `migrate_*` / `deploy/patch_*.sql`. Schema is
  bootstrap-only (`core/db/schema.py`). Local DB + file storage reset to empty.
- `client_release.signature` column removed from bootstrap DDL (HMAC gone;
  integrity remains sha256).

## 2026-09-08 — Client updates without HMAC

- Packaged client updates verify **sha256** only. The shared HMAC key /
  `client_release_hmac.key` / `NR_CLIENT_RELEASE_HMAC_KEY` path was removed
  (a key file next to the exe is not a secret).

## 2026-09-08 — Client 0.9.15 (client-only bump)

- `CLIENT_VERSION` bumped to **0.9.15** (`SERVER_VERSION` stays **0.9.13**).

## 2026-09-08 — Client 0.9.14 (client-only bump)

- `CLIENT_VERSION` bumped to **0.9.14** (`SERVER_VERSION` stays **0.9.13**).
- No API / schema / kit stamp change; rebuild + publish the packaged client zip.

## 2026-09-08 — Packaged client updates, no migrations

- Administrators publish Windows/macOS client zips from **Home → Publish client…**
  (NAS history keeps the last 5 builds per OS). Workstations apply them via
  **Update client…** / **Previous client…** (sha256, preserve `plugins/`,
  atomic `*_new` / `*_old` swap).
- `CLIENT_VERSION` and `SERVER_VERSION` are separate constants (both **0.9.13**
  for this release). Build embeds `client_manifest.json`.
- Retention purge behaviour unchanged: finished runs write `PURGE` in the Audit
  log; daily time remains configurable on Home (default **23:59**).
- Kit stamp refreshed via `assemble-kit.ps1`. Schema remains bootstrap-only
  (`core/db/schema.py`). No runtime migration layer.

## 2026-09-03 — Team tab reload, no migrations

- The Team tab no longer flashes a full “Loading…” rebuild when other tables
  change on the server. Record edits refresh entity tabs incrementally; the
  member list reloads only when team membership actually changes.
- App version bumped to **0.9.12**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-09-02 — Purge audit log, Team ID privacy, no migrations

- Each finished retention purge (Home or daily 23:59) writes a `PURGE` row
  in the Audit log (`table_name=database`). Skipped concurrent runs do not.
  Clients cannot forge `PURGE` via `/invoke`. The journal and revision
  snapshots stay permanent.
- Team tab hides **ID**, **Role**, and **Permissions** columns unless the
  signed-in user is an administrator.
- Schema remains bootstrap-only (`core/db/schema.py`). No runtime migration
  layer, Alembic, `migrate_*`, or `deploy/patch_*.sql`.
- App version bumped to **0.9.11**; kit stamp refreshed via `assemble-kit.ps1`.
- Packaged client hidden imports cover `ui_zones` and `user_privacy`.

## 2026-08-31 — Plugin button row width

- Buttons that share a row expand equally to fill the group-box width, with
  centered labels. Stacked single-button rows also span the full width.
- App version bumped to **0.9.10**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-08-31 — Plugin button rows

- Each plugin group box can mix **side-by-side** and **stacked** buttons.
  `add_button(..., new_row=True)` starts a new row; `new_row=False` keeps the
  button on the current row. When omitted, toolbar and Home stay on the same
  row; Information / Related / Plugin panel stack.
- App version bumped to **0.9.9**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-08-31 — Retention purge, actions, plugin toolbar

- Concurrent Home Purge and daily 23:59 jobs share a PostgreSQL advisory lock;
  a second caller is skipped (`skipped=1`) instead of overlapping deletes.
- Reference scrubbing now includes **soft-deleted** tables/subtypes/attributes
  and reports `references_scrubbed`. Multi-reference and table-level
  automatic-action rules are included in expired-rule cleanup.
- Folder trash `IN` lists are chunked; nested table row hard-deletes commit in
  chunks; empty `deleted_at` values are ignored. Home confirmation uses the
  **saved** retention policy (not an unsaved spin-box value).
- Schema is created once on an empty database (`core/db/schema.py`). Leftover
  compatibility with older databases has been removed.
- Automatic actions can trigger from **multi-reference** fields (still one
  chosen target). The Actions editor only offers **table-level** attributes
  (not subtype fields). A run that cannot finish raises; the editor was
  sped up for create / edit / delete.
- Entity-tab **toolbar** launchers stay visible for `selection_mode = optional`
  after a click or row select (host buttons restored when a signature skip
  would otherwise leave the zone empty).
- Plugin `add_button` on a zone that is not on the current tab (e.g. `ZONE_HOME`
  on a table tab) is skipped instead of aborting the plugin. New manifest
  `placement = "all"` runs on table tabs and the Home tab.
- App version bumped to **0.9.8**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-08-28 — One project folder named after the plugin

- The downloaded kit **is** the plugin project: name the folder after the plugin
  id and edit it in place. SDK, `setup-dev`, and `prepare-publish` stay at the
  root — there is **no** nested `dev-kit/` subdirectory.
- **Download for editing** merges catalog sources onto the kit in that same
  flat folder so you can run and **Import plugin to database…** from `publish/`.
- Packaged client hidden imports cover `dev_kit_local` (flat extract / merge).
- App version bumped to **0.9.7**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-08-19 — Incremental audit log, background tab preload, build/DevKit sync

- Audit log tab no longer rebuilds the full journal on every remote change:
  after the first load, the client fetches only rows newer than the last known
  id (`since_id`) and prepends them. Search still filters in memory. Older
  servers without `since_id` fall back to a full fetch.
- Hidden tabs (tables, Tree, Team, Tables, Audit log) preload in the
  background after login so the first click does not flash a loading state.
- Retention purge is unchanged: the global `audit_log` and linked revision
  snapshots stay **permanent**; daily automatic purge stays at **23:59** local
  time (no run at API startup). Incremental audit fetch is safe because purge
  never deletes those rows.
- Packaged client hidden imports already cover `logs_tab`, `app_startup`
  preload, Date/Time history columns, and `table_utils` prepend.
- App version bumped to **0.9.6**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-08-15 — Permanent audit log, purge 23:59, tab flicker, build/DevKit sync

- Retention purge **never** deletes the global `audit_log` or linked revision
  snapshots (`entity_revision`). Home Purge confirmation and summary state that
  the audit log is kept; per-record `entity_record_history` still goes with the
  purged row.
- Daily automatic purge stays at **23:59** local time (no run at API startup).
  The scheduler constant had drifted to 03:59; it is restored and covered by a
  unit test. Manual Home Purge is unchanged.
- First open of a tab after launch no longer flashes the list/info panels
  (first-show freeze). Toggling **Show deleted** no longer rebuilds the info
  panel in a way that blinks.
- History tables split **Date** and **Time** (seconds, no milliseconds) in
  entity tabs, Audit log, schema history, and automatic-action history.
- Packaged client hidden imports cover `startup_progress`, `time_select`,
  `logs_tab`, and `schema_history_panel`.
- App version bumped to **0.9.5**; kit stamp refreshed via `assemble-kit.ps1`.
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).

## 2026-08-11 — UI homogeneity, purge confirmation, build/DevKit sync

- Desktop UI pass: shared push-button theme on the app stylesheet; order
  buttons (`↑`/`↓`) and `QDialogButtonBox` actions use common helpers so
  dialogs/tabs match the same look.
- List option / automation rule lists use the theme selection blue; plugin
  list highlight uses the accent token; transfer Cancel radius aligned.
- Home **Purge** uses the themed confirmation dialog and correctly states that
  abandoned upload/open temps use a **fixed 24-hour** age (not `retention_days`).
- No runtime migration layer (bootstrap DDL in `core/db/schema.py` only).
- App version bumped to **0.9.4**; kit stamp refreshed via `assemble-kit.ps1`.

## 2026-08-10 — Always-on diagnostic logs (client + plugin launch)

- Desktop client always writes **`client.log`** next to the executable (last
  session only; overwrite each launch). No env var required; disable with
  `NR_CLIENT_LOG=0`.
- Client log includes session header (version/OS/paths/env), stdout+stderr,
  logging, Python/Qt warnings, uncaught exceptions (main + threads),
  faulthandler, and connection/startup events.
- Plugin `launch_script` writes a richer
  `.plugin_script_launch.log` (header + child stdout/stderr,
  `PYTHONFAULTHANDLER` / `PYTHONWARNINGS`, unbuffered `-u`).
- Packaged build copies on-disk `neurorehab_plugin` into `_internal/` after
  COLLECT (`install_packaged_plugin_sdk`) so plugin workers can sync the SDK.
- App version bumped to **0.9.3**; kit stamp refreshed via `assemble-kit.ps1`.

## 2026-08-10 — English-only authoring rule

- Dev-kit docs now require **English for all plugin-authored text**:
  `plugin.toml` name/description, UI strings, comments, docstrings, and
  plugin docs (see GUIDE.md — Language).
- Starter `main.py` / `plugin.toml` remind authors to keep wording in English.
- Checklist entry added in SECURITY.md; DEVELOPMENT.md important rules updated.

## 2026-08-10 — Client log next to the program

- Optional client debug log (`NR_CLIENT_LOG=1`) writes `client.log` **next to the
  executable** (or project root in dev), no longer under `%LOCALAPPDATA%` /
  Application Support.
- Plugin `launch_script` capture remains
  `plugins/cache/<plugin_id>/.plugin_script_launch.log` (next to the install).
- Retention purge docs clarify that these workstation-local log files are
  **not** part of server retention purge.
- App version bumped to **0.9.2**; kit stamp refreshed via `assemble-kit.ps1`.

## 2026-08-10 — Retention purge hardening, no migrations, build/DevKit sync

- Retention purge hard-deletes expired folder trees **including nested child
  files** (unlink NAS blobs before FK CASCADE) so orphan storage cannot remain
  after a folder trash purge.
- Hard-purging a soft-deleted table now cleans nested subtype/attribute audit
  history before the `entity_def` row is removed.
- API startup uses FastAPI **lifespan** (replacing deprecated `on_event`) while
  still running retention purge on a daemon thread.
- Confirmed: **no runtime migration layer** (bootstrap DDL in `core/db/schema.py`
  only; no Alembic / `migrate_*` / `deploy/patch_*.sql`).
- Remaining French code comments translated to English; Home retention help and
  deploy docs updated.
- Client PyInstaller hidden imports explicitly include `help_tip` /
  `help_texts` / `confirmation_dialog` / `soft_delete`.
- App version bumped to **0.9.1**; kit stamp refreshed via `assemble-kit.ps1`.

## 2026-08-05 — Transfer cancel, close guard, atomic downloads

- Desktop transfers expose **Cancel** on the progress panel (with a confirmation
  dialog); closing the app while a transfer runs asks for confirmation
  (**Quit and cancel** / **Keep working**).
- Cooperative `CancellationToken` aborts dedicated HTTP upload/download sockets.
- Downloads write to a `.nr-partial` file then rename atomically; cancel/error
  removes the partial. Cancelled uploads leave no finalized NAS blob; leftover
  server spools stay under retention purge / upload `finally` cleanup.
- Parallel multi-file transfers abort siblings when cancel is requested.
- Packaged client build includes `client.transfer_cancel` /
  `client.transfer_parallel` as explicit hidden imports.

## 2026-08-05 — Build/runtime cleanup, purge perf, no legacy patches

- Removed legacy one-shot SQL patches under `deploy/patch_*.sql` and all
  runtime schema patching. `core/db/schema.py` is the single bootstrap source.
- Reduced duplicate backend computations in form/history/detail bundles by
  reusing resolved field lists, team-member options, and label maps inside one
  request.
- Retention purge hard-deletes expired **audit-adjacent categories in batch SQL**
  (file versions, folder trash) and scrubs dangling references once per
  expired-record set; hard deletes commit in chunks. The global `audit_log`
  itself is **not** deleted (made permanent later; see 2026-08-15). Stale NAS
  `.tmp` upload spools (including after cancelled uploads) remain covered by
  the temp purge.
- Build helpers now de-duplicate hidden imports while preserving order to keep
  PyInstaller analysis stable and avoid redundant module scanning.
- Desktop transfer progress panel (upload/download) is fully English: `B/KB/MB`,
  `Speed` / `Remaining`, and upload status messages.

## 2026-07-27 — Plugins tab Last used / Last used by

- Plugins tab columns **Last used** / **Last used by** show
  `plugin_package.last_used_at` and who last launched the plugin.
- **Last used by** displays **First name** then **Last name** from the Team
  profile (`prenom` / `nom`), never the PostgreSQL login.
- Updated when a plugin `run()` starts, when a **tab-zone button** is clicked,
  or when the plugin calls `/plugin/invoke`. Script-only plugins (no DB access)
  are covered via host launch / button clicks.
- Host endpoint: `POST /api/v1/plugins/{id}/last-used` (`can_use_plugins`).
  Not part of the plugin SDK surface; SDK also blocks `touch_*` ops client-side.
- Columns are part of the bootstrap schema in `core/db/schema.py`. Retention
  purge does **not** remove unused plugins — use **Delete** on the Plugins tab.

## 2026-07-24 — Plugins next to the packaged exe

- Packaged client stores `plugins/` (cache, venvs, settings) **next to the
  executable** instead of AppData. Deleting the install folder removes local
  plugin data. Falls back to OS user-data if the install dir is not writable.

## 2026-07-24 — Folder trash (soft-delete) + purge counters

- Folder-field **files and folders** are soft-deleted (`deleted_at`) and
  restorable in the client via **Show deleted items** / **Restore**.
- `PluginApi.list_folders` / `list_files` return **active** items by default;
  pass `only_deleted=True` to inspect trash (read-only).
- New `PluginApi.get_folder(folder_id)`.
- Retention purge also hard-deletes expired trash folder items
  (`folder_files` / `folders` stats). Columns/indexes are in `schema.py`.

## 2026-07-24 — Multi-reference attributes, purge scrub, no migrate_*

- New attribute type **`multi_reference`** (multi-select references / team
  members). Single-reference automations are unchanged.
- Incoming / outgoing reference APIs and UI refresh helpers include multi-
  reference array values.
- Retention **hard purge** clears dangling single- and multi-reference ids
  from other records before deleting a purged row.
- Runtime `migrate_*` helpers fully removed; schema remains bootstrap-only
  (`CREATE TABLE IF NOT EXISTS`).

## 2026-07-23 — Download permission, no runtime migrations

- Team permission **`can_download_files`**: download record attachments locally
  (including **Download for edit…** / **Replace…**) and download the shared
  plugin development kit (`Plugins → Download dev-kit…`).
- Server schema is bootstrap-only (`core/db/schema.py`); runtime `migrate_*`
  patches were removed. Fresh DBs get full DDL from the bootstrap script.
- Retention purge startup log reports all purge categories (rows, schema,
  automations, file versions, audit, orphans, temps).

## 2026-07-23 — Retention purge covers file versions and temps

- Retention purge hard-deletes archived file versions past `retention_days`,
  then removes orphan NAS files and stale ``.tmp`` spools (24h).
- Home Purge summary reports `file_versions` and `temp_files` counts.

## 2026-07-22 — Schema manage bundle, PG pool, attribute edit

- Desktop **Edit attribute** for table and subtype fields; structural edits are
  blocked when the table / subtype already has active records (UI + server).
- New `load_schema_manage_bundle` (client allowlist only — not exposed to plugins)
  aggregates variants, fields, soft-deleted rows, and `has_active_records` flags.
- API process-wide PostgreSQL pool (`NR_PG_POOL_SIZE` / `NR_PG_POOL_TIMEOUT`).
- Desktop `RemoteDatabase.invoke_batch` (max 50) for multi-op round-trips.
- Table settings Restore toggle uses CrossToggle; reference-target row hides
  correctly when the field type is not Reference.

## 2026-07-22 — Schema soft-delete, Tree zoom, Actions UI

- Soft-delete / restore for **table and subtype attributes** (history on parent
  table / subtype); purge counts include attribute rows.
- Tables tab: click empty area in the table list to clear selection.
- Tree tab: Zoom − / Zoom + / 100%, Ctrl+wheel zoom down to 10%.
- Automatic actions: Then → Action no longer offers « Update the current row »
  (`update_source`); existing rules still run / open for edit.
- Invoke entity-access: ops that take a decoded `EntityRecord` (e.g.
  `record_display_label`) resolve permissions correctly.
- Plugin readonly scope handles `record_display_label` with EntityRecord args.

## 2026-07-21 — Automatic actions & security

- SDK continues to block all automatic-action mutations and history ops
  (`save_variant_automation_rules`, `list_automation_rule_*`, `preview_*`, …).
- Server `PLUGIN_READONLY_OPS` does **not** include automation ops (final gate).
- App-side: fine-grained `can_create_actions` / `can_edit_actions` /
  `can_delete_actions`; Actions UI uses a dedicated editor window; rule history
  is stored via `/invoke` with rich audit details.
- Retention purge also removes expired soft-deleted automation rules.

## Desktop client

- English Plugins tab: **Favorites** / **Other plugins** sections.
- Machine-scoped local install (`machine_settings.json`, `plugins/cache/`, `plugins/venvs/`).
- Per-user favorites on the server (`GET/PUT /api/v1/plugins/favorites`).
- **Download dev-kit…** — downloads `assets/dev-kit.zip` from the API and extracts
  `neurorehab-dev-kit/` to a local folder (Documents by default).
- **Publish dev-kit to server…** (admins) — uploads the kit zip to NAS storage.
- Forced dark theme, high-contrast zones, separate login address/port fields.
- Entity tabs show **“Loading data…”** while the list bundle loads.

## Server API

- `GET /api/v1/plugins/dev-kit` — download kit zip (`can_download_files` or
  plugin install/use/publish/delete rights).
- `GET /api/v1/plugins/dev-kit/status` — `{ available, storage_key }`.
- `POST /api/v1/plugins/dev-kit` — publish/replace kit (`can_publish_dev_kit`).

## Plugin SDK

- Worker subprocess model with keep-alive HTTP and `invoke_batch()` (max 50 ops).
- `window_builder_is_alive()`, `button_style`, `pump_gui_events()`.
- Read-only API enforced by SDK and server whitelist (no automation-rule ops).

## Maintainers

```powershell
cd plugins
.\assemble-kit.ps1   # sync SDK + VERSION + plugins/dist/neurorehab-dev-kit.zip
```

Then **Plugins → Publish dev-kit to server…** (or copy the zip to
`FILE_STORAGE_DIR/assets/dev-kit.zip`).
