"""Read plugin.toml manifest (stdlib tomllib / tomli fallback).

Trigger modes (`run_trigger`):
- manual (default): launcher button; UI stays until next click or selection change
- on_select: no button; run() on each selection; UI updated automatically
  (`on_click` is still accepted as an alias for manual)

Selection modes (`selection_mode`):
- one_or_more (default): button hidden without selection
- optional: button always visible; execution with 0, 1 or N rows
- none: button visible only without selection
- single / multiple: strict selection constraints

UI rebuild hint (`ui_depends_on_selection`):
- omitted / unset: auto — true for ``build_ui`` / ``on_select``, false for
  plain manual launchers (selection only enables/disables the host button)
- true / false: force whether a row-selection change must rebuild plugin UI

Selection UI policy (`selection_ui`), finer than the bool above:
- omitted: derived from ``ui_depends_on_selection`` / auto rules
- ``none``: selection never rebuilds UI (host may still enable launchers)
- ``enable``: host enables/disables existing ``build_ui`` buttons; worker
  ``build_ui`` only on first paint (no IPC on later row changes)
- ``rebuild``: full worker ``build_ui`` / ``on_select`` on selection change
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from neurorehab_plugin.scope import (
    PluginMatchScope,
    format_match_scope,
    match_scope_from_dict,
    match_scope_to_dict,
    parse_match_scope,
    record_matches_scope,
)

DEFAULT_PLUGIN_VERSION = "1.0.0"
_PLUGIN_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$"
)

PLACEMENT_ENTITY_TAB = "entity_tab"
PLACEMENT_RECORD_PANEL = "record_panel"
PLACEMENT_HOME = "home"
PLACEMENT_ALL = "all"
RUN_TRIGGER_MANUAL = "manual"
RUN_TRIGGER_ON_CLICK = "on_click"  # backward-compatible alias for manual
RUN_TRIGGER_ON_SELECT = "on_select"
SELECTION_ONE_OR_MORE = "one_or_more"
SELECTION_NONE = "none"
SELECTION_SINGLE = "single"
SELECTION_MULTIPLE = "multiple"
SELECTION_OPTIONAL = "optional"
SELECTION_UI_NONE = "none"
SELECTION_UI_ENABLE = "enable"
SELECTION_UI_REBUILD = "rebuild"
PLUGIN_PLACEMENTS: frozenset[str] = frozenset(
    {PLACEMENT_ENTITY_TAB, PLACEMENT_RECORD_PANEL, PLACEMENT_HOME, PLACEMENT_ALL}
)
PLUGIN_RUN_TRIGGERS: frozenset[str] = frozenset(
    {RUN_TRIGGER_MANUAL, RUN_TRIGGER_ON_SELECT}
)
PLUGIN_SELECTION_MODES: frozenset[str] = frozenset(
    {
        SELECTION_ONE_OR_MORE,
        SELECTION_NONE,
        SELECTION_SINGLE,
        SELECTION_MULTIPLE,
        SELECTION_OPTIONAL,
    }
)
PLUGIN_SELECTION_UI_MODES: frozenset[str] = frozenset(
    {SELECTION_UI_NONE, SELECTION_UI_ENABLE, SELECTION_UI_REBUILD}
)


def parse_plugin_version(
    value: Any,
    *,
    required: bool = False,
    default: str = DEFAULT_PLUGIN_VERSION,
) -> str:
    """Validate and normalize ``plugin.version`` (semver-like ``MAJOR.MINOR.PATCH``).

    Args:
        value: Raw manifest value.
        required: When True, missing/blank values raise ``ValueError`` instead
            of falling back to ``default`` (used for server uploads).
        default: Fallback when ``value`` is omitted and ``required`` is False.

    Returns:
        Normalized version string.

    Raises:
        ValueError: If the value is required but missing, or does not match
            ``MAJOR.MINOR.PATCH`` with an optional ``-prerelease`` suffix.
    """
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise ValueError("plugin.version is required.")
        raw = str(default).strip() or DEFAULT_PLUGIN_VERSION
    if not _PLUGIN_VERSION_RE.match(raw):
        raise ValueError(
            "plugin.version must be MAJOR.MINOR.PATCH "
            "(optional -prerelease suffix, e.g. 1.2.0 or 1.2.0-rc.1)."
        )
    return raw


def plugin_instance_key(plugin_id: str, version: str) -> str:
    """Return the runtime identity key ``id@version`` for a plugin package."""
    plugin_id = str(plugin_id or "").strip()
    version = parse_plugin_version(version, required=True)
    if not plugin_id:
        raise ValueError("plugin.id is required to build an instance key.")
    return f"{plugin_id}@{version}"


def split_plugin_instance_key(instance_key: str) -> tuple[str, str]:
    """Split ``id@version`` into ``(id, version)``.

    Raises:
        ValueError: If the key is not ``id@version`` with a valid version.
    """
    key = str(instance_key or "").strip()
    if "@" not in key:
        raise ValueError(f"Invalid plugin instance key (expected id@version): {key!r}")
    plugin_id, version = key.rsplit("@", 1)
    plugin_id = plugin_id.strip()
    version = parse_plugin_version(version, required=True)
    if not plugin_id:
        raise ValueError(f"Invalid plugin instance key (missing id): {key!r}")
    return plugin_id, version


@dataclass(frozen=True)
class PluginManifest:
    """Parsed, validated contents of a plugin's ``plugin.toml`` manifest.

    Attributes:
        id: Unique plugin identifier (required).
        version: Package version (semver-like); defaults to ``1.0.0`` locally.
        name: Human-readable plugin name (defaults to ``id``).
        description: Human-readable description of the plugin.
        api_version: Plugin SDK API version the plugin targets.
        placement: Where the plugin's UI is rendered; one of
            :data:`PLACEMENT_ENTITY_TAB` / :data:`PLACEMENT_RECORD_PANEL` /
            :data:`PLACEMENT_HOME` / :data:`PLACEMENT_ALL`.
        entry: Relative path (within ``path``) to the plugin's entry-point
            Python file.
        path: Absolute, resolved path to the plugin's installation directory.
        entity_keys: Entity (table) keys this plugin targets; empty means
            "applies to all tables" on entity tabs. The Inventory catalog is
            not a table tab and never hosts plugins. On ``placement = "home"``
            (or Home via ``all``), a non-empty list grants read access to
            those tables (intersected with the user's view rights); empty
            means no table data on Home.
        match_scope: Fine-grained targeting rules (sub-type / field values)
            further restricting which records the plugin applies to.
        selection_mode: Constraint on how many records must be selected for
            the plugin to be actionable; one of the ``SELECTION_*`` constants.
        run_trigger: When the plugin executes; one of the ``RUN_TRIGGER_*``
            constants.
        ui_depends_on_selection: Optional override for whether changing the
            row selection must rebuild this plugin's UI. ``None`` means auto
            (see :meth:`selection_ui_mode`). Prefer ``selection_ui`` for
            ``enable`` vs ``rebuild``.
        selection_ui: Optional ``none`` / ``enable`` / ``rebuild`` policy for
            how selection changes affect UI (see :meth:`selection_ui_mode`).
    """

    id: str
    name: str
    description: str
    api_version: int
    placement: str
    entry: str
    path: Path
    version: str = DEFAULT_PLUGIN_VERSION
    entity_keys: tuple[str, ...] = ()
    match_scope: PluginMatchScope = PluginMatchScope()
    selection_mode: str = SELECTION_ONE_OR_MORE
    run_trigger: str = RUN_TRIGGER_MANUAL
    ui_depends_on_selection: bool | None = None
    selection_ui: str | None = None

    @property
    def instance_key(self) -> str:
        """Runtime identity ``id@version`` (unique across side-by-side installs)."""
        return plugin_instance_key(self.id, self.version)

    @property
    def display_name(self) -> str:
        """Human-readable label including version for side-by-side UI."""
        base = str(self.name or self.id).strip() or self.id
        return f"{base} (v{self.version})"

    @property
    def entry_file(self) -> Path:
        """Absolute path to the plugin's entry-point Python file."""
        return self.path / self.entry

    def selection_ui_mode(self, *, has_build_ui: bool = False) -> str:
        """How row selection should affect this plugin's UI.

        Returns one of :data:`SELECTION_UI_NONE` / :data:`SELECTION_UI_ENABLE` /
        :data:`SELECTION_UI_REBUILD`.
        """
        if self.selection_ui is not None:
            return self.selection_ui
        if self.ui_depends_on_selection is False:
            return SELECTION_UI_NONE
        if self.ui_depends_on_selection is True:
            return SELECTION_UI_REBUILD
        if has_build_ui:
            return SELECTION_UI_REBUILD
        if self.run_trigger == RUN_TRIGGER_ON_SELECT:
            return SELECTION_UI_REBUILD
        return SELECTION_UI_NONE

    def selection_affects_ui(self, *, has_build_ui: bool = False) -> bool:
        """Whether a row-selection change should touch this plugin's UI at all."""
        return self.selection_ui_mode(has_build_ui=has_build_ui) != SELECTION_UI_NONE

    def selection_needs_worker_rebuild(self, *, has_build_ui: bool = False) -> bool:
        """Whether selection must invoke the plugin worker (``build_ui``/``run``)."""
        return (
            self.selection_ui_mode(has_build_ui=has_build_ui) == SELECTION_UI_REBUILD
        )

    def applies_to_entity(self, *, entity_key: str, entity_label: str) -> bool:
        """Return True if this plugin targets the given entity (table).

        Args:
            entity_key: Machine key of the entity to test.
            entity_label: Human-readable label of the entity to test.

        Returns:
            True if ``entity_keys`` is empty (applies to all tables) or
            matches ``entity_key``/``entity_label`` case-insensitively.
        """
        return manifest_applies_to_entity(
            self.entity_keys,
            entity_key=entity_key,
            entity_label=entity_label,
        )

    def applies_to_record(
        self,
        *,
        record_data: dict[str, Any],
        variant_key: str = "",
        variant_label: str = "",
    ) -> bool:
        """Return True if this plugin's ``match_scope`` matches a given record.

        Args:
            record_data: Field values of the record to test.
            variant_key: Machine key of the record's variant/sub-type, if any.
            variant_label: Human-readable label of the record's variant, if any.

        Returns:
            True if the record satisfies at least one rule in ``match_scope``
            (or if the scope is empty, meaning "applies to all records").
        """
        return record_matches_scope(
            self.match_scope,
            record_data=record_data,
            variant_key=variant_key,
            variant_label=variant_label,
        )

    def scope_summary(self) -> str:
        """Return a short human-readable summary of ``match_scope`` for display."""
        return format_match_scope(self.match_scope)


def parse_entity_keys(plugin: dict[str, Any]) -> tuple[str, ...]:
    """Parse the ``plugin.entity_keys`` manifest field into a normalized tuple.

    Args:
        plugin: Parsed ``[plugin]`` table from ``plugin.toml``.

    Returns:
        Tuple of unique, stripped, non-empty entity keys; empty if the field
        is absent (meaning "all entities").

    Raises:
        ValueError: If ``entity_keys`` is present but not a string or list
            of strings.
    """
    raw = plugin.get("entity_keys")
    if raw is None:
        return ()
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValueError("plugin.entity_keys must be a string or a list of strings.")
    keys = tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))
    return keys


def manifest_applies_to_entity(
    entity_keys: tuple[str, ...],
    *,
    entity_key: str,
    entity_label: str,
) -> bool:
    """True if the plugin targets all tables or a matching table."""
    if not entity_keys:
        return True
    targets = {item.casefold() for item in entity_keys}
    return entity_key.casefold() in targets or entity_label.casefold() in targets


def _load_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file using stdlib ``tomllib`` (3.11+) or the ``tomli`` fallback.

    Args:
        path: Path to the TOML file to read and parse.

    Returns:
        Parsed TOML content as a nested dict.

    Raises:
        RuntimeError: If neither ``tomllib`` nor ``tomli`` is available.
    """
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib

        return tomllib.loads(text)
    except ModuleNotFoundError:
        try:
            import tomli
        except ImportError as exc:
            raise RuntimeError(
                "Install tomli for Python < 3.11 or use Python 3.11+."
            ) from exc
        return tomli.loads(text)


def parse_placement(value: Any) -> str:
    """Validate and normalize the ``plugin.placement`` manifest field.

    Args:
        value: Raw value from the manifest; defaults to
            :data:`PLACEMENT_ENTITY_TAB` when falsy.

    Returns:
        A validated placement string (one of :data:`PLUGIN_PLACEMENTS`).

    Raises:
        ValueError: If ``value`` is not a recognized placement.
    """
    placement = str(value or PLACEMENT_ENTITY_TAB).strip() or PLACEMENT_ENTITY_TAB
    if placement not in PLUGIN_PLACEMENTS:
        allowed = ", ".join(sorted(PLUGIN_PLACEMENTS))
        raise ValueError(f"plugin.placement must be one of: {allowed}.")
    return placement


def placement_runs_on_entity_tabs(placement: str | None) -> bool:
    """True when the plugin is invoked on table (entity) tabs.

    Home-only plugins (``placement = "home"``) are excluded. ``all`` runs
    on both table tabs and the Home tab. The Inventory tab is not included.
    """
    return str(placement or PLACEMENT_ENTITY_TAB) != PLACEMENT_HOME


def placement_runs_on_home(placement: str | None) -> bool:
    """True when the plugin is invoked on the Home tab."""
    return str(placement or "") in {PLACEMENT_HOME, PLACEMENT_ALL}


def parse_selection_mode(value: Any) -> str:
    """Validate and normalize the ``plugin.selection_mode`` manifest field.

    Args:
        value: Raw value from the manifest; defaults to
            :data:`SELECTION_ONE_OR_MORE` when falsy.

    Returns:
        A validated selection mode string (one of
        :data:`PLUGIN_SELECTION_MODES`).

    Raises:
        ValueError: If ``value`` is not a recognized selection mode.
    """
    mode = str(value or SELECTION_ONE_OR_MORE).strip() or SELECTION_ONE_OR_MORE
    if mode not in PLUGIN_SELECTION_MODES:
        allowed = ", ".join(sorted(PLUGIN_SELECTION_MODES))
        raise ValueError(f"plugin.selection_mode must be one of: {allowed}.")
    return mode


def parse_run_trigger(value: Any) -> str:
    """Validate and normalize the ``plugin.run_trigger`` manifest field.

    The legacy alias ``on_click`` is normalized to :data:`RUN_TRIGGER_MANUAL`.

    Args:
        value: Raw value from the manifest; defaults to
            :data:`RUN_TRIGGER_MANUAL` when falsy.

    Returns:
        A validated run-trigger string (one of :data:`PLUGIN_RUN_TRIGGERS`).

    Raises:
        ValueError: If ``value`` is not a recognized run trigger.
    """
    trigger = str(value or RUN_TRIGGER_MANUAL).strip() or RUN_TRIGGER_MANUAL
    if trigger == RUN_TRIGGER_ON_CLICK:
        trigger = RUN_TRIGGER_MANUAL
    if trigger not in PLUGIN_RUN_TRIGGERS:
        allowed = ", ".join(sorted(PLUGIN_RUN_TRIGGERS))
        raise ValueError(f"plugin.run_trigger must be one of: {allowed}.")
    return trigger


def parse_ui_depends_on_selection(value: Any) -> bool | None:
    """Validate ``plugin.ui_depends_on_selection`` (optional bool override).

    Returns:
        ``None`` when the field is omitted (auto), otherwise a bool.

    Raises:
        ValueError: If the value is present but not a boolean.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("plugin.ui_depends_on_selection must be a boolean when set.")


def parse_selection_ui(value: Any) -> str | None:
    """Validate ``plugin.selection_ui`` (``none`` / ``enable`` / ``rebuild``).

    Returns:
        ``None`` when omitted (auto), otherwise a normalized mode string.

    Raises:
        ValueError: If the value is present but not a recognized mode.
    """
    if value is None:
        return None
    mode = str(value).strip().casefold()
    if mode not in PLUGIN_SELECTION_UI_MODES:
        allowed = ", ".join(sorted(PLUGIN_SELECTION_UI_MODES))
        raise ValueError(f"plugin.selection_ui must be one of: {allowed}.")
    return mode


def load_manifest(plugin_dir: Path) -> PluginManifest:
    """Load, parse, and validate a plugin's ``plugin.toml`` manifest.

    Args:
        plugin_dir: Directory containing the plugin's ``plugin.toml`` and
            entry-point script.

    Returns:
        A validated :class:`PluginManifest` describing the plugin.

    Raises:
        ValueError: If ``plugin.toml`` is missing, ``plugin.id`` is absent,
            or any field fails validation.
    """
    manifest_path = plugin_dir / "plugin.toml"
    if not manifest_path.is_file():
        raise ValueError(f"Missing plugin.toml in {manifest_path}")
    raw = _load_toml(manifest_path)
    plugin = raw.get("plugin") if isinstance(raw.get("plugin"), dict) else raw
    plugin_id = str(plugin.get("id") or "").strip()
    if not plugin_id:
        raise ValueError(f"plugin.id is required in {manifest_path}")
    return PluginManifest(
        id=plugin_id,
        version=parse_plugin_version(plugin.get("version")),
        name=str(plugin.get("name") or plugin_id),
        description=str(plugin.get("description") or ""),
        api_version=int(plugin.get("api_version") or 1),
        placement=parse_placement(plugin.get("placement")),
        entry=str(plugin.get("entry") or "main.py"),
        path=plugin_dir.resolve(),
        entity_keys=parse_entity_keys(plugin),
        match_scope=parse_match_scope(plugin),
        selection_mode=parse_selection_mode(plugin.get("selection_mode")),
        run_trigger=parse_run_trigger(plugin.get("run_trigger")),
        ui_depends_on_selection=parse_ui_depends_on_selection(
            plugin.get("ui_depends_on_selection")
        ),
        selection_ui=parse_selection_ui(plugin.get("selection_ui")),
    )


__all__ = [
    "DEFAULT_PLUGIN_VERSION",
    "PLACEMENT_ALL",
    "PLACEMENT_ENTITY_TAB",
    "PLACEMENT_HOME",
    "PLACEMENT_RECORD_PANEL",
    "PLUGIN_PLACEMENTS",
    "PLUGIN_RUN_TRIGGERS",
    "PLUGIN_SELECTION_MODES",
    "PLUGIN_SELECTION_UI_MODES",
    "RUN_TRIGGER_MANUAL",
    "RUN_TRIGGER_ON_CLICK",
    "RUN_TRIGGER_ON_SELECT",
    "SELECTION_MULTIPLE",
    "SELECTION_NONE",
    "SELECTION_ONE_OR_MORE",
    "SELECTION_OPTIONAL",
    "SELECTION_SINGLE",
    "SELECTION_UI_ENABLE",
    "SELECTION_UI_NONE",
    "SELECTION_UI_REBUILD",
    "PluginManifest",
    "load_manifest",
    "manifest_applies_to_entity",
    "match_scope_from_dict",
    "match_scope_to_dict",
    "parse_placement",
    "parse_plugin_version",
    "parse_run_trigger",
    "parse_selection_mode",
    "parse_match_scope",
    "parse_ui_depends_on_selection",
    "parse_selection_ui",
    "placement_runs_on_entity_tabs",
    "placement_runs_on_home",
    "plugin_instance_key",
    "split_plugin_instance_key",
]
