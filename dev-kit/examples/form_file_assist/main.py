"""Suggest draft form values when the user picks a local File in Add/Edit.

The host calls ``on_file_chosen`` after Browse… on a File attribute. Return
``suggested_values`` for other fields on the open form. Nothing is written to
the database until the user confirms Add / Update.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from neurorehab_plugin import PluginApi, PluginContext, PluginUi


def on_file_chosen(
    api: PluginApi,
    context: PluginContext,
    ui: PluginUi,
    *,
    field_key: str,
    local_path: str,
    draft: dict[str, Any],
    variant_id: int | None,
    form_mode: str,
) -> dict[str, Any]:
    """Return draft suggestions derived from the chosen local file.

    ``ui`` host emit is disabled for this op — do not rely on ``add_button``.
    ``api`` remains read-only. Prefer reading ``local_path`` on disk.
    """
    del api, context, ui, draft, variant_id, form_mode
    path = Path(local_path)
    if not path.is_file():
        return {"suggested_values": {}}

    # Minimal demo: stem → text field ``name`` when present on the form.
    # Replace with real header/metadata parsing for your table.
    stem = path.stem.strip()
    suggested: dict[str, Any] = {}
    if stem:
        suggested["name"] = stem
    # Optional: expose original file name without extension for notes.
    suggested["notes"] = f"Imported from {os.path.basename(local_path)}"
    # Only keys that exist on the open form (and are not File/Folder/Combo)
    # are applied by the host.
    return {"suggested_values": suggested}


def run(api: PluginApi, context: PluginContext, ui: PluginUi) -> None:
    """Optional manual launcher explaining the form-assist behaviour."""
    del api, context
    ui.show_message(
        "Form file assist",
        "Open Add or Edit, choose a file on a File attribute, and matching "
        "draft fields are filled from on_file_chosen(). Nothing is saved "
        "until you confirm the form.",
    )
