"""Plugin targeting rules (sub-type, fields, values).

Defines the data model and evaluation logic for a plugin's ``when``/
``match_scope`` rules, which determine which records a plugin's UI/actions
apply to based on the record's variant (sub-type) and/or specific field
values. This is a *display/applicability* filter, not a security
boundary: it complements (but does not replace) the ``allowed_record_ids``
enforcement performed by :class:`~neurorehab_plugin.api.PluginApi`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PluginFieldCondition:
    """A single field-value condition used in a targeting rule.

    Exactly one of ``equals``/``contains`` is expected to be set (enforced
    by :func:`parse_field_conditions`).

    Attributes:
        field_key: Key of the record field to inspect.
        equals: If set, the field's normalized string value must equal this
            (case-insensitive).
        contains: If set, this substring must appear in the field's
            normalized string value (case-insensitive).
    """

    field_key: str
    equals: str | None = None
    contains: str | None = None


@dataclass(frozen=True)
class PluginWhenRule:
    """A single targeting rule: variant keys AND field conditions (all must match).

    Attributes:
        variant_keys: If non-empty, the record's variant key or label must
            match one of these (case-insensitive) for the rule to apply.
        field_conditions: Field-level conditions that must all be satisfied.
    """

    variant_keys: tuple[str, ...] = ()
    field_conditions: tuple[PluginFieldCondition, ...] = ()

    def is_empty(self) -> bool:
        """Return True if this rule has no constraints (always matches)."""
        return not self.variant_keys and not self.field_conditions


@dataclass(frozen=True)
class PluginMatchScope:
    """One or more rules combined with OR (|). Each rule is an internal AND."""

    rules: tuple[PluginWhenRule, ...] = ()

    def is_empty(self) -> bool:
        """Return True if there are no rules, or all rules are themselves empty.

        An empty scope means "matches every record" (no targeting
        restriction configured).
        """
        if not self.rules:
            return True
        return all(rule.is_empty() for rule in self.rules)


def _parse_string_list(raw: Any) -> tuple[str, ...]:
    """Normalize a TOML value (string or list) into a deduplicated string tuple.

    Args:
        raw: ``None``, a single string, or a list/tuple of strings.

    Returns:
        Tuple of unique, stripped, non-empty strings in original order.

    Raises:
        ValueError: If ``raw`` is neither ``None``, a string, nor a list/tuple.
    """
    if raw is None:
        return ()
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValueError("Expected a string or a list of strings.")
    return tuple(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def parse_field_conditions(raw: Any) -> tuple[PluginFieldCondition, ...]:
    """Parse a list of field-condition tables from a manifest ``when`` block.

    Args:
        raw: ``None`` or a list of dicts, each with a ``key``/``field`` and
            either ``equals`` or ``contains``.

    Returns:
        Tuple of parsed :class:`PluginFieldCondition` objects.

    Raises:
        ValueError: If ``raw`` is not a list, an item is not a dict, a
            ``key``/``field`` is missing, or neither ``equals`` nor
            ``contains`` is provided.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("Field conditions must be provided as a list of tables.")
    conditions: list[PluginFieldCondition] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid field condition at index {index}.")
        field_key = str(item.get("key") or item.get("field") or "").strip()
        if not field_key:
            raise ValueError(f"Field condition at index {index} is missing 'key'.")
        equals = item.get("equals")
        contains = item.get("contains")
        if equals is None and contains is None:
            raise ValueError(
                f"Field condition for {field_key!r} requires 'equals' or 'contains'."
            )
        conditions.append(
            PluginFieldCondition(
                field_key=field_key,
                equals=None if equals is None else str(equals),
                contains=None if contains is None else str(contains),
            )
        )
    return tuple(conditions)


def parse_when_rule(raw: dict[str, Any]) -> PluginWhenRule:
    """Parse a single ``when`` table into a :class:`PluginWhenRule`.

    Args:
        raw: A dict with optional ``variant_keys`` and ``fields`` entries.

    Returns:
        The parsed rule.
    """
    variant_keys = _parse_string_list(raw.get("variant_keys"))
    fields_raw = raw.get("fields")
    return PluginWhenRule(
        variant_keys=variant_keys,
        field_conditions=parse_field_conditions(fields_raw),
    )


def parse_match_scope(plugin: dict[str, Any]) -> PluginMatchScope:
    """Parse a plugin's full targeting scope from its manifest ``[plugin]`` table.

    Supports both the modern ``when`` block (a single table, meaning one
    AND-rule, or a list of tables, meaning several OR-combined rules) and
    the legacy top-level ``variant_keys``/``fields`` shorthand.

    Args:
        plugin: Parsed ``[plugin]`` table from ``plugin.toml``.

    Returns:
        The parsed :class:`PluginMatchScope` (empty if no targeting rules
        are configured).

    Raises:
        ValueError: If ``plugin.when`` is present but not a table or list
            of tables.
    """
    when = plugin.get("when")
    if when is not None and not isinstance(when, (dict, list)):
        raise ValueError("plugin.when must be a table or a list of tables.")
    if isinstance(when, list):
        rules = tuple(parse_when_rule(item) for item in when if isinstance(item, dict))
        return PluginMatchScope(rules=rules)
    if isinstance(when, dict):
        return PluginMatchScope(rules=(parse_when_rule(when),))
    variant_keys = _parse_string_list(plugin.get("variant_keys"))
    field_conditions = parse_field_conditions(plugin.get("fields"))
    if variant_keys or field_conditions:
        return PluginMatchScope(
            rules=(
                PluginWhenRule(
                    variant_keys=variant_keys,
                    field_conditions=field_conditions,
                ),
            )
        )
    return PluginMatchScope()


def _rule_to_dict(rule: PluginWhenRule) -> dict[str, Any]:
    """Serialize a single :class:`PluginWhenRule` into a plain JSON-safe dict."""
    return {
        "variant_keys": list(rule.variant_keys),
        "fields": [
            {
                "key": condition.field_key,
                **({"equals": condition.equals} if condition.equals is not None else {}),
                **(
                    {"contains": condition.contains}
                    if condition.contains is not None
                    else {}
                ),
            }
            for condition in rule.field_conditions
        ],
    }


def match_scope_to_dict(scope: PluginMatchScope) -> dict[str, Any]:
    """Serialize a :class:`PluginMatchScope` into a plain JSON-safe dict.

    Args:
        scope: The match scope to serialize.

    Returns:
        Dict with a ``"rules"`` key holding a list of serialized rules.
    """
    return {"rules": [_rule_to_dict(rule) for rule in scope.rules]}


def match_scope_from_dict(raw: Any) -> PluginMatchScope:
    """Deserialize a :class:`PluginMatchScope` from a dict or JSON string.

    Supports the structured ``{"rules": [...]}`` form as well as the legacy
    flat ``{"variant_keys": [...], "fields": [...]}`` form. Any malformed
    input (wrong type, invalid JSON) degrades gracefully to an empty scope
    rather than raising.

    Args:
        raw: A dict, a JSON string encoding a dict, or a falsy value.

    Returns:
        The deserialized :class:`PluginMatchScope` (empty on any parsing
        failure or falsy input).
    """
    if not raw:
        return PluginMatchScope()
    if isinstance(raw, str):
        import json

        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return PluginMatchScope()
    if not isinstance(raw, dict):
        return PluginMatchScope()
    rules_raw = raw.get("rules")
    if isinstance(rules_raw, list):
        rules: list[PluginWhenRule] = []
        for item in rules_raw:
            if isinstance(item, dict):
                rules.append(
                    PluginWhenRule(
                        variant_keys=_parse_string_list(item.get("variant_keys")),
                        field_conditions=parse_field_conditions(item.get("fields")),
                    )
                )
        return PluginMatchScope(rules=tuple(rules))
    variant_keys = _parse_string_list(raw.get("variant_keys"))
    field_conditions = parse_field_conditions(raw.get("fields"))
    if variant_keys or field_conditions:
        return PluginMatchScope(
            rules=(
                PluginWhenRule(
                    variant_keys=variant_keys,
                    field_conditions=field_conditions,
                ),
            )
        )
    return PluginMatchScope()


def normalize_field_value(value: Any) -> str:
    """Normalize a record field value into a comparable string.

    Args:
        value: Raw field value (``None``, ``bool``, number, or other).

    Returns:
        ``""`` for ``None``; ``"true"``/``"false"`` for booleans; the plain
        string form for numbers; ``str(value).strip()`` otherwise.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return str(value).strip()


def field_condition_matches(data: dict[str, Any], condition: PluginFieldCondition) -> bool:
    """Evaluate a single field condition against a record's field data.

    Args:
        data: Record field values, keyed by field key.
        condition: The condition to evaluate.

    Returns:
        True if the condition's ``equals``/``contains`` test passes (or if
        neither is set, which trivially matches).
    """
    actual = normalize_field_value(data.get(condition.field_key))
    if condition.equals is not None:
        return actual.casefold() == condition.equals.casefold()
    if condition.contains is not None:
        return condition.contains.casefold() in actual.casefold()
    return True


def record_matches_rule(
    rule: PluginWhenRule,
    *,
    record_data: dict[str, Any],
    variant_key: str = "",
    variant_label: str = "",
) -> bool:
    """Evaluate whether a record satisfies a single :class:`PluginWhenRule` (AND semantics).

    Args:
        rule: The rule to evaluate.
        record_data: The record's field values.
        variant_key: The record's variant machine key, if any.
        variant_label: The record's variant human-readable label, if any.

    Returns:
        True if the rule is empty, or if both the variant constraint (when
        present) and all field conditions are satisfied.
    """
    if rule.is_empty():
        return True
    if rule.variant_keys:
        targets = {item.casefold() for item in rule.variant_keys}
        key_ok = variant_key.casefold() in targets if variant_key else False
        label_ok = variant_label.casefold() in targets if variant_label else False
        if not key_ok and not label_ok:
            return False
    for condition in rule.field_conditions:
        if not field_condition_matches(record_data, condition):
            return False
    return True


def record_matches_scope(
    scope: PluginMatchScope,
    *,
    record_data: dict[str, Any],
    variant_key: str = "",
    variant_label: str = "",
) -> bool:
    """Evaluate whether a record satisfies a full :class:`PluginMatchScope` (OR of rules).

    Args:
        scope: The match scope to evaluate.
        record_data: The record's field values.
        variant_key: The record's variant machine key, if any.
        variant_label: The record's variant human-readable label, if any.

    Returns:
        True if ``scope`` is empty, or if the record matches at least one
        of its rules.
    """
    if scope.is_empty():
        return True
    return any(
        record_matches_rule(
            rule,
            record_data=record_data,
            variant_key=variant_key,
            variant_label=variant_label,
        )
        for rule in scope.rules
    )


def _format_rule(rule: PluginWhenRule) -> str:
    """Render a single rule as a short human-readable string (semicolon-separated)."""
    parts: list[str] = []
    if rule.variant_keys:
        parts.append("sub-types: " + ", ".join(rule.variant_keys))
    for condition in rule.field_conditions:
        if condition.equals is not None:
            parts.append(f"{condition.field_key} = {condition.equals}")
        elif condition.contains is not None:
            parts.append(f"{condition.field_key} ~ {condition.contains}")
    return " ; ".join(parts) if parts else ""


def format_match_scope(scope: PluginMatchScope) -> str:
    """Render a full match scope as a short human-readable summary string.

    Args:
        scope: The match scope to format.

    Returns:
        Rules joined with ``" | "`` (OR), each rule's parts joined with
        ``" ; "`` (AND); ``""`` if the scope is empty.
    """
    if scope.is_empty():
        return ""
    parts = [_format_rule(rule) for rule in scope.rules if not rule.is_empty()]
    return " | ".join(part for part in parts if part)
