"""Project-facing orchestration for the M3/M4 concept-design slice."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from rflp_lite.application.concept_design_service import (
    ConceptRunResult,
    concept_run_from_payload,
    review_layout_candidate,
    run_concept_design,
)
from rflp_lite.application.concept_store import ConceptStore
from rflp_lite.application.discipline_batch import validate_evaluator_profile
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.scheme_library import import_scheme_rows
from rflp_lite.domain.canonical import to_primitive
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import ContractViolation, NotFoundError
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate


_RESOURCE_ROOT = Path(__file__).resolve().parents[1] / "resources"
_PACK_PATH = _RESOURCE_ROOT / "domain-packs" / "fixed-wing-v1.json"
_SCHEME_PATH = _RESOURCE_ROOT / "examples" / "concept-design" / "fixed-wing-schemes.json"
_PROFILE_PATH = _RESOURCE_ROOT / "examples" / "concept-design" / "development-evaluator-profile.json"


def _default_pack() -> dict[str, Any]:
    return load_domain_pack(_PACK_PATH)


def _default_schemes(pack: Mapping[str, object], scheme_reader: Callable):
    rows = scheme_reader(_SCHEME_PATH.name, _SCHEME_PATH.read_bytes())
    imported = import_scheme_rows(pack, rows, str(_SCHEME_PATH))
    if not imported.records:
        raise ContractViolation("fixed-wing scheme library contains no valid records")
    return imported.records


def _default_profile() -> dict[str, Any]:
    return validate_evaluator_profile(json.loads(_PROFILE_PATH.read_text(encoding="utf-8")))


def _as_payload(result: ConceptRunResult) -> dict[str, Any]:
    raw = to_primitive(result)
    return dict(raw) if isinstance(raw, Mapping) else {}


class ConceptDesignProjectService:
    """Run, review and apply concept candidates for one ModelGraph project."""

    def __init__(self, repository, project_id: str, *, registry_factory: Callable, scheme_reader: Callable) -> None:
        self.repository = repository
        self.project_id = project_id
        self.store = ConceptStore(repository, project_id)
        self.registry_factory = registry_factory
        self.scheme_reader = scheme_reader

    def run(
        self,
        envelope: Mapping[str, object],
        *,
        pack: Mapping[str, object] | None = None,
        schemes: Sequence[object] | None = None,
        evaluator_profile: Mapping[str, object] | None = None,
        optimize: bool = True,
    ) -> ConceptRunResult:
        normalized_pack = dict(pack) if isinstance(pack, Mapping) else _default_pack()
        scheme_records = tuple(schemes) if schemes is not None else _default_schemes(normalized_pack, self.scheme_reader)
        profile = dict(evaluator_profile) if evaluator_profile is not None else _default_profile()
        result = run_concept_design(
            normalized_pack,
            profile,
            envelope,
            scheme_records,
            self.registry_factory(),
            self.store,
            optimize=optimize,
        )
        self.store.save_scheme_records(scheme_records)
        return result

    def latest(self) -> ConceptRunResult | None:
        raw = self.store.concept_runs()
        if not raw:
            return None
        return concept_run_from_payload(raw[-1])

    def get(self, run_id: str) -> ConceptRunResult:
        raw = self.store.load_concept_run(run_id)
        if raw is None:
            raise NotFoundError(f"concept run not found: {run_id}")
        return concept_run_from_payload(raw)

    def review(self, candidate_id: str, decision: str, run_id: str = "") -> dict[str, Any]:
        return review_layout_candidate(candidate_id, decision, self.store, run_id=run_id)

    def apply_candidate(self, candidate_id: str, run_id: str = "") -> dict[str, Any]:
        result = self.get(run_id) if run_id else self.latest()
        if result is None:
            raise NotFoundError("no concept run is available")
        candidate = next((item for item in result.candidates if item.id == candidate_id), None)
        if candidate is None:
            raise NotFoundError(f"layout candidate not found: {candidate_id}")
        graph = self.repository.load_graph(self.project_id)
        entity = make_entity(
            EntityKind.PHYSICAL_BLOCK,
            f"总体布局 {candidate.id}",
            {
                "concept_candidate_id": candidate.id,
                "concept_run_id": result.id,
                "representation_kind": "conceptual_2d_svg",
                "parameters": dict(candidate.parameters),
                "geometry": dict(candidate.geometry),
                "constraints": [to_primitive(item) for item in candidate.constraints],
                "evaluations": [
                    to_primitive(item)
                    for item in result.evaluations
                    if item.candidate_id == candidate.id
                ],
                "svg": candidate.svg,
                "source_requirement_ids": list(result.envelope.source_requirement_ids),
            },
            status=EntityStatus.ACCEPTED,
            producer=Producer.USER,
            confidence=1.0,
            source_ids=(result.id, candidate.id),
            revision=graph.revision,
        )
        existing = graph.entity_index.get(entity.id)
        if existing is not None:
            return {
                "candidate": to_primitive(candidate),
                "entity": existing.as_dict(),
                "revision": {"project_id": self.project_id, "sequence": graph.revision},
                "idempotent": True,
            }
        operations: list[object] = [AddEntity(entity)]
        operations.extend(
            Relate(requirement_id, RelationPredicate.SATISFIED_BY, entity.id)
            for requirement_id in result.envelope.source_requirement_ids
            if requirement_id in graph.entity_index
        )
        patch = Patch.create(
            self.project_id,
            "concept.apply_candidate",
            tuple(operations),
            f"应用总体布局候选 {candidate.id}",
            graph.revision,
        )
        revision = self.repository.append_patch(self.project_id, patch, graph.revision)
        self.store.record_audit(
            "concept.candidate_applied",
            {"candidate_id": candidate.id, "run_id": result.id, "entity_id": entity.id, "revision": revision.sequence},
        )
        return {"candidate": to_primitive(candidate), "entity": entity.as_dict(), "revision": to_primitive(revision)}


__all__ = ["ConceptDesignProjectService"]
