"""Stable MBSE semantic API backed by the typed build pipeline."""

from __future__ import annotations

from rflp_lite.application.mbse.legacy_builder import (
    FORMAL_RELATION_ENDPOINTS,
    MBSE_SEMANTIC_MODEL_VERSION,
    RELATION_KINDS,
    SECTION_KEYS,
    SEMANTIC_FORMAT,
    build_legacy_mbse_semantic_model,
    legacy_mbse_projection,
    mbse_entity_index,
    validate_mbse_semantic_model,
)
from rflp_lite.application.mbse.pipeline import build_typed_mbse_semantic_model
from rflp_lite.domain.canonical import canonical_hash


def build_mbse_semantic_model(
    analysis: dict[str, object],
    revision: object = None,
    provenance: object = None,
) -> dict[str, object]:
    """Build semantics through the typed, compatibility-preserving pipeline."""

    return build_typed_mbse_semantic_model(
        analysis, revision, provenance
    ).as_dict()


def generate_mbse_semantic_revision(
    state: dict[str, object], provenance: object = None
) -> dict[str, object]:
    semantic = build_mbse_semantic_model(state, state.get("revision"), provenance)
    legacy = legacy_mbse_projection(semantic)
    model = {
        **legacy,
        "semantic_model": semantic,
    }
    model["revision"] = canonical_hash(
        {key: value for key, value in model.items() if key != "revision"}
    )
    return model
