# Security — NeuroRehab plugins

Plugins are **read-only** extensions. No database write is possible through the
official API or supported server routes.

## Allowed

- Read records, attributes, schemas, files, folders (within selection + permissions)
- Add / enable / label buttons in authorized host zones only
- Open worker-owned dialogs and fully customizable floating windows
- Export locally (CSV, temp files opened with the OS default app)

## Forbidden

- Create / update / delete / rename rows, schema, or stored files / folders
- Spreadsheet subtype import (Excel/CSV) — desktop client only; not in the SDK
- File / Folder display-name rename — desktop client only (`rename_*` blocked in SDK)
- Automatic actions (create/edit/delete rules, history listing, previews,
  `apply_record_field_automations`) — blocked in the SDK and absent from
  `PLUGIN_READONLY_OPS`
- Admin operations (users, backup, purge, …)
- Team/account lookups (`list_app_users`, `list_team_member_combo_items`,
  `list_team_member_name_parts`, …)
- Direct DB or unrestricted API access
- Reading records outside the selection scope
- Mutating NeuroRehab host chrome beyond zone buttons (no banners, row
  highlights, menus, layouts, or stylesheets on the host)
- **Blocking access to the NeuroRehab client** — long `build_ui()`, tight loops
  without `run_task` / a worker window, or any pattern that expects the host to
  freeze until the plugin finishes (see GUIDE.md — Host responsiveness)

## Protection layers

| Layer | Mechanism |
|-------|-----------|
| SDK | Blocks write prefixes (`create_*`, `import_*`, `purge_*`, `rename_*`, …), team lookups, automation history ops |
| HTTP transport | Only `/api/v1/plugin/*`; keep-alive connection per session |
| Server | `PLUGIN_READONLY_OPS` whitelist (`core/plugin/readonly_ops.py`) — automation ops are **not** listed |
| Invoke | `server/services/invoke_service.py` — plugin mode |
| Session | Short-lived JWT (`plugin` audience) with embedded `allowed_record_ids` (client kwargs cannot widen scope) |
| Worker | **Always** isolated venv subprocess (`python.exe`, piped protocol) — plugin code never runs in the host process |
| Worker children | `subprocess.Popen` defaults `stdin=DEVNULL` so analysis CLIs cannot inherit / block the host IPC pipe |
| Host IPC | Allowlist: `add_button` / `button_set_*` / `clear` only |
| Host UI | IPC wait pumps user input; other plugins can launch concurrently (deferred); hung workers killed + quarantined |
| Publish | `prepare-publish` ships `plugin.toml` + root `.py` + root packages (`*/__init__.py`) + `requirements.txt` — no SDK |

The stdin guard applies to `subprocess.Popen` / `subprocess.run` (and the
`plugin_popen` / `plugin_run` helpers). It does **not** cover `os.system`,
`os.popen`, or `asyncio.create_subprocess_*` — avoid those for child CLIs,
or set stdin to `DEVNULL` yourself.

## Author checklist

1. Use only `PluginApi` — no raw HTTP to other routes.
2. Prefer `context.applicable_records` (respects `[[plugin.when]]`).
3. In `run_task`, the worker function must not call `ui.*`.
4. No secrets in published files.
5. Test with a **non-admin** user.
6. Keep `build_ui()` side-effect free and **fast** (see GUIDE.md — Host
   responsiveness / Host refresh). Never block NeuroRehab access.
7. Write **everything in English** (manifest, UI, comments, docs) — see GUIDE.md — Language.

```python
api._invoke("update_entity_record", [1, {}])
# PluginWriteForbiddenError
```
