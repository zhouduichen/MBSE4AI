"""Orchestration-only MBSE semantic build pipeline."""

from __future__ import annotations

from importlib import import_module

from rflp_lite.application.mbse.builders.context import MbseBuildContext, MbseSemanticModel


def build_typed_mbse_semantic_model(
    state: dict[str, object], revision: object = None, provenance: object = None
) -> MbseSemanticModel:
    """Run the compatibility-equivalent semantic builder and type its result."""

    context = MbseBuildContext.from_state(state, revision, provenance)
    legacy = import_module("rflp_lite.application.mbse_semantics")
    payload = legacy._legacy_build_mbse_semantic_model(
        dict(context.state), context.revision, context.provenance
    )
    return MbseSemanticModel.from_payload(payload)
