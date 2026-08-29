"""Immutable, complete inputs used by requirements analysis jobs.

The snapshot deliberately contains every source region.  Any reduction for a
model request happens through :func:`source_batches`, never through a silent
slice at the analysis boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


_MODES = frozenset({"incremental", "coverage_audit", "full_reanalysis"})


def _clone(value: object) -> object:
    return json.loads(canonical_json(value))


def build_project_snapshot(
    state: dict[str, object],
    *,
    mode: str,
    delta_region_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build a JSON-safe analysis snapshot without dropping source regions."""

    if mode not in _MODES:
        raise ContractViolation(f"未知需求分析模式: {mode}")
    scope = state.get("project_scope")
    scope = scope if isinstance(scope, Mapping) else {}
    raw_regions = state.get("document_regions") or state.get("spans") or ()
    regions = [
        {
            "id": str(item.get("id", "")),
            "text": str(item.get("text", "")),
            "locator": str(item.get("locator", "")),
            "artifact_id": str(item.get("artifact_id", "")),
            "page": item.get("page"),
        }
        for item in raw_regions
        if isinstance(item, Mapping) and str(item.get("text", "")).strip()
    ]
    delta = {str(value) for value in delta_region_ids if str(value)}
    selected_regions = (
        [item for item in regions if item["id"] in delta]
        if mode == "incremental" and delta
        else list(regions)
    )
    discovery = state.get("discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    architecture = discovery.get("architecture")
    architecture = architecture if isinstance(architecture, Mapping) else {}
    return {
        "mode": mode,
        "workspace": str(scope.get("workspace", "")),
        "revision": int(state.get("revision", 0) or 0),
        "content_revision": int(
            state.get("content_revision", state.get("revision", 0)) or 0
        ),
        "input_hash": str(scope.get("input_hash", "")),
        "delta_region_ids": sorted(delta),
        "input_regions": _clone(selected_regions),
        "all_source_ids": sorted(item["id"] for item in regions if item["id"]),
        "stakeholders": _clone(state.get("stakeholders", ())),
        "concerns": _clone(state.get("concerns", ())),
        "needs": _clone(state.get("needs", ())),
        "requirements": _clone(
            list(state.get("structured_requirements", ()))
            + list(state.get("claims", ()))
        ),
        "scenarios": _clone(state.get("scenarios", ())),
        "trace_links": _clone(state.get("trace_links", ())),
        "architecture": _clone(dict(architecture)),
        "deletion_registry": _clone(state.get("deletion_registry", ())),
    }


def source_batches(
    snapshot: dict[str, object], *, batch_size: int = 20
) -> tuple[tuple[dict[str, object], ...], ...]:
    """Return every selected source in deterministic batches."""

    if batch_size < 1:
        raise ContractViolation("source batch size must be positive")
    sources = tuple(
        sorted(
            (
                dict(item)
                for item in snapshot.get("input_regions", ())
                if isinstance(item, Mapping)
            ),
            key=lambda item: str(item.get("id", "")),
        )
    )
    if not sources:
        return ((),)
    return tuple(
        sources[offset : offset + batch_size]
        for offset in range(0, len(sources), batch_size)
    )


__all__ = ["build_project_snapshot", "source_batches"]
