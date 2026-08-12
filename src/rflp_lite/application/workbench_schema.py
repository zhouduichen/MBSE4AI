"""Schema/version migration for the requirements workbench state."""

from __future__ import annotations

import json
from typing import Any

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


WORKBENCH_SCHEMA_VERSION = 2

_V2_DEFAULTS: dict[str, object] = {
    "document_pages": [],
    "document_regions": [],
    "entities": [],
    "structured_requirements": [],
    "trace_links": [],
    "diagnostics": [],
    "mbse": None,
    "artifacts": [],
    "revision": 0,
    "review_queue": [],
    "change_set": {
        "kind": "legacy",
        "base_revision": 0,
        "items": [],
        "summary": {
            "added": 0,
            "affected": 0,
            "removed": 0,
            "requires_confirmation": 0,
        },
    },
}


def empty_document_state() -> dict[str, object]:
    """Return a fresh state fragment for document intelligence fields."""

    return json.loads(canonical_json(_V2_DEFAULTS))


def migrate_workbench_state(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize legacy state to schema v2 without mutating repository data."""

    if state is None:
        return None
    if not isinstance(state, dict):
        raise ContractViolation("workbench state must be an object")
    normalized = json.loads(canonical_json(state))
    version = int(normalized.get("schema_version", 1))
    if version > WORKBENCH_SCHEMA_VERSION:
        raise ContractViolation(
            f"unsupported workbench schema version: {version}"
        )
    normalized["schema_version"] = WORKBENCH_SCHEMA_VERSION
    for key, default in _V2_DEFAULTS.items():
        if key not in normalized or normalized[key] is None:
            normalized[key] = json.loads(canonical_json(default))
    # The old extractor called these spans; v2 treats them as document regions.
    if not normalized["document_regions"] and normalized.get("spans"):
        normalized["document_regions"] = [
            {
                "id": span.get("id", ""),
                "artifact_id": span.get("artifact_id", ""),
                "page": None,
                "kind": "text",
                "locator": span.get("locator", ""),
                "text": span.get("text", ""),
                "bbox": [],
                "confidence": 1.0,
            }
            for span in normalized.get("spans", [])
        ]
    return normalized
