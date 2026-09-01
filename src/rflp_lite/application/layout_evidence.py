"""Auditable evidence for conceptual 2-D layout artifacts."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.application.layout_generation import candidate_distance
from rflp_lite.domain.canonical import canonical_hash, to_primitive
from rflp_lite.domain.concept_design import LayoutCandidate


def build_layout_manifest(
    pack: Mapping[str, object], candidate: LayoutCandidate, candidates
) -> dict[str, object]:
    """Build a deterministic manifest without timestamps or runtime paths."""

    distances = [
        candidate_distance(pack, candidate, other)
        for other in candidates
        if str(getattr(other, "id", "")) != candidate.id
    ]
    body = {
        "candidate_id": candidate.id,
        "envelope_id": candidate.envelope_id,
        "representation_kind": "conceptual_2d_svg",
        "views": ["top", "side"],
        "unit_system": "SI",
        "reference_scheme_ids": list(candidate.reference_ids),
        "similarity_matches": [to_primitive(item) for item in candidate.similarity_matches],
        "parameter_differences": [list(item) for item in candidate.parameter_sources],
        "hard_constraint_margins": [
            {
                "id": item.constraint_id,
                "margin": item.margin,
                "passed": item.passed,
            }
            for item in candidate.constraints
            if item.severity == "hard"
        ],
        "minimum_pairwise_distance": round(min(distances) if distances else 1.0, 8),
        "generator_id": str(pack.get("id_prefix", "layout-generator")),
        "generator_version": candidate.generator_version,
        "seed": candidate.seed,
        "input_hash": candidate.input_hash,
        "candidate_result_hash": candidate.result_hash,
        "svg_hash": canonical_hash(candidate.svg),
    }
    return {**body, "manifest_hash": canonical_hash(body)}


def validate_layout_manifest(manifest: Mapping[str, object]) -> bool:
    """Verify the self-hash and the honest conceptual representation label."""

    if not isinstance(manifest, Mapping):
        return False
    if manifest.get("representation_kind") != "conceptual_2d_svg":
        return False
    expected = canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"})
    return str(manifest.get("manifest_hash", "")) == expected


__all__ = ["build_layout_manifest", "validate_layout_manifest"]
