"""Source-aware interpretation of requirement constraint payloads."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping


_INFERRED_SOURCES = frozenset({"derived", "llm_inferred"})


def has_explicit_constraints(payload: Mapping[str, object]) -> bool:
    """Return whether a requirement contains a user/model-stated bound.

    New intake payloads keep both explicit and derived candidates in the same
    constraint containers.  Once provenance is present, only ``explicit``
    entries drive technical-requirement completion.  Older payloads without
    provenance retain the historical max/min behavior for compatibility.
    """

    provenance = payload.get("constraint_provenance")
    if isinstance(provenance, (list, tuple)):
        return any(
            isinstance(item, Mapping)
            and str(item.get("source", "")).casefold() not in _INFERRED_SOURCES
            for item in provenance
        )
    return bool(payload.get("constraints")) or any(
        str(key).startswith(("max_", "min_"))
        for key in payload
    )


def explicit_constraint_map(payload: Mapping[str, object]) -> Mapping[str, object]:
    """Return canonical max/min fields whose provenance is explicitly stated."""

    provenance = payload.get("constraint_provenance")
    if isinstance(provenance, (list, tuple)):
        explicit_entries = [
            item for item in provenance
            if isinstance(item, Mapping)
            and str(item.get("source", "")).casefold() not in _INFERRED_SOURCES
        ]
        explicit_keys = {
            f"{item.get('operator')}_{item.get('field')}"
            for item in explicit_entries
            if str(item.get("operator", "")).strip()
            and str(item.get("field", "")).strip()
        }
        if explicit_entries and not explicit_keys:
            explicit_keys = None
    else:
        explicit_keys = None

    constraints: MutableMapping[str, object] = {}
    for key, value in payload.items():
        key = str(key)
        if key.startswith(("max_", "min_")) and (
            explicit_keys is None or key in explicit_keys
        ):
            constraints[key] = value
    for container_key in ("constraints", "limits"):
        container = payload.get(container_key)
        if not isinstance(container, Mapping):
            continue
        for key, value in container.items():
            key = str(key)
            if key.startswith(("max_", "min_")) and (
                explicit_keys is None or key in explicit_keys
            ):
                constraints[key] = value
    return dict(sorted(constraints.items()))
