"""Document-to-requirements/use-case intake for the first MBSE vertical slice.

The service deliberately separates two concerns:

* a remote structured model proposes an ``IntakeDraft``;
* deterministic code validates, normalizes, and compiles that draft into the
  existing typed ModelGraph.

It is intentionally domain-neutral.  Layout, CAD, and discipline solvers can
consume the resulting requirements and behavior evidence in later slices.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
import re
import time
from typing import Any

import jsonschema

from rflp_lite.application.requirement_intake import (
    extract_requirement_constraints,
    infer_requirement_constraints,
    split_requirement_statements,
)
from rflp_lite.application.resources import resource_path
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.errors import AdapterFailure, ContractViolation, InputRequired
from rflp_lite.domain.model import AddEntity, ModelGraph, Patch, Relate, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    GenerativeModel,
    add_simplified_chinese_instruction,
)
from rflp_lite.repository.port import ModelRepository


_SCHEMA_RELATIVE_PATH = "schemas/requirements_use_case_draft.v1.json"
_PROMPT_RELATIVE_PATH = "prompts/requirements_use_case.v1.md"
_SCHEMA_VERSION = "requirements-use-case-draft.v1"
_LENS_ID = "requirements.use_case"
_MAX_DRAFT_DIAGNOSTICS = 40
_SOURCE_KINDS = frozenset({
    "system",
    "stakeholder",
    "concern",
    "scenario_hypothesis",
})
_SCENARIO_KINDS = frozenset({"operational_scenario"})
_CONSTRAINT_SOURCES = frozenset({"explicit", "derived", "llm_inferred"})
_REQUIREMENT_KINDS = frozenset({
    "functional",
    "performance",
    "interface",
    "safety",
    "constraint",
})


@lru_cache(maxsize=1)
def draft_schema() -> dict[str, Any]:
    path = resource_path(_SCHEMA_RELATIVE_PATH)
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def draft_prompt() -> str:
    path = resource_path(_PROMPT_RELATIVE_PATH)
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True, slots=True)
class IntakeDraft:
    """A JSON-safe, auditable proposal that has not necessarily been applied."""

    draft_id: str
    project_id: str
    input_hash: str
    status: str
    payload: Mapping[str, object]
    provider_id: str = ""
    model_id: str = ""
    profile_id: str = ""
    duration_ms: int = 0
    output_hash: str = ""
    diagnostics: tuple[str, ...] = ()
    created_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        payload = _plain(self.payload)
        return {
            **payload,
            "draft_id": self.draft_id,
            "project_id": self.project_id,
            "input_hash": self.input_hash,
            "status": self.status,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "profile_id": self.profile_id,
            "duration_ms": self.duration_ms,
            "output_hash": self.output_hash,
            "diagnostics": list(self.diagnostics),
            "created_at": self.created_at,
            "payload": payload,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "IntakeDraft":
        raw_payload = value.get("payload")
        if isinstance(raw_payload, Mapping):
            payload = dict(raw_payload)
        else:
            metadata = {
                "draft_id",
                "project_id",
                "input_hash",
                "status",
                "provider_id",
                "model_id",
                "profile_id",
                "duration_ms",
                "output_hash",
                "diagnostics",
                "created_at",
                "payload",
            }
            payload = {str(key): item for key, item in value.items() if key not in metadata}
        return cls(
            draft_id=str(value.get("draft_id", "")).strip(),
            project_id=str(value.get("project_id", "")).strip(),
            input_hash=str(value.get("input_hash", "")).strip(),
            status=str(value.get("status", "completed")),
            payload=payload,
            provider_id=str(value.get("provider_id", "")),
            model_id=str(value.get("model_id", "")),
            profile_id=str(value.get("profile_id", "")),
            duration_ms=int(value.get("duration_ms", 0) or 0),
            output_hash=str(value.get("output_hash", "")),
            diagnostics=tuple(str(item) for item in value.get("diagnostics", ()) if str(item).strip()),
            created_at=float(value.get("created_at", 0.0) or 0.0),
        )


@dataclass
class _CompilerState:
    project_id: str
    graph: ModelGraph
    valid_sources: set[str]
    diagnostics: list[str]
    producer: Producer = Producer.LLM
    operations: list[object] = field(default_factory=list)
    working_entities: dict[str, Entity] = field(default_factory=dict)
    working_relations: dict[str, Relation] = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=dict)

    def resolve(self, value: object) -> str | None:
        clean = str(value or "").strip()
        if not clean:
            return None
        return self.refs.get(clean) or (clean if clean in self.working_entities else None)

    def ensure(
        self,
        local_ref: str,
        kind: EntityKind,
        name: str,
        entity_payload: Mapping[str, object],
        source_refs: Sequence[object],
        confidence: object,
    ) -> str:
        clean_name = " ".join(str(name).split()).strip()
        if not clean_name:
            self.diagnostics.append(f"compile:empty-name:{local_ref}")
            return ""
        existing = _find_entity(self.working_entities.values(), kind, clean_name)
        source_ids = _valid_refs(source_refs, self.valid_sources)
        if existing is not None:
            self.refs[local_ref] = existing.id
            return existing.id
        try:
            score = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            score = 0.5
        stored_payload = dict(entity_payload)
        stored_payload.setdefault("requires_human_review", True)
        stored_payload.setdefault(
            "provenance",
            "document_evidence"
            if source_ids
            else ("rule_inferred" if self.producer is Producer.RULE else "llm_inferred"),
        )
        stored_payload.setdefault("source_refs", list(source_ids))
        entity = make_entity(
            kind,
            clean_name,
            stored_payload,
            status=EntityStatus.CANDIDATE,
            producer=self.producer,
            confidence=score,
            source_ids=source_ids,
            evidence_ids=source_ids,
            revision=self.graph.revision,
        )
        if entity.id in self.working_entities:
            self.refs[local_ref] = entity.id
            return entity.id
        self.working_entities[entity.id] = entity
        self.operations.append(AddEntity(entity))
        self.refs[local_ref] = entity.id
        return entity.id

    def relate(
        self,
        source: object,
        predicate: RelationPredicate,
        target: object,
        evidence: Sequence[object] = (),
    ) -> None:
        source_id = self.resolve(source)
        target_id = self.resolve(target)
        if source_id is None or target_id is None:
            self.diagnostics.append(f"compile:unresolved-relation:{source}->{target}")
            return
        relation_identity = (source_id, predicate.value, target_id)
        relation_id = f"rel-{canonical_hash(relation_identity)[:16]}"
        if relation_id in self.working_relations:
            return
        relation = Relation(
            relation_id,
            source_id,
            predicate,
            target_id,
            tuple(_valid_refs(evidence, self.valid_sources)),
        )
        candidate = ModelGraph(
            self.project_id,
            tuple(self.working_entities.values()),
            tuple((*self.working_relations.values(), relation)),
            self.graph.revision,
        )
        try:
            candidate.validate_relation(relation)
        except ContractViolation as exc:
            self.diagnostics.append(f"compile:invalid-relation:{exc}")
            return
        self.operations.append(Relate(source_id, predicate, target_id, relation.evidence_ids))
        self.working_relations[relation_id] = relation


def _new_compiler_state(
    project_id: str,
    graph: ModelGraph,
    valid_sources: set[str],
    diagnostics: list[str],
    producer: Producer,
) -> _CompilerState:
    return _CompilerState(
        project_id=project_id,
        graph=graph,
        valid_sources=valid_sources,
        diagnostics=diagnostics,
        producer=producer,
        working_entities=dict(graph.entity_index),
        working_relations={item.id: item for item in graph.relations},
    )


def _compile_base_entities(
    state: _CompilerState,
    payload: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, str]]:
    system_context = payload.get("system_context", {})
    if isinstance(system_context, Mapping):
        state.ensure(
            "system",
            EntityKind.SYSTEM,
            str(system_context.get("name", "目标系统")),
            {
                "mission": str(system_context.get("mission", "")),
                "system_boundary": {"inside": [], "outside": []},
                "objectives": [],
                "environment_assumptions": [],
                "exclusions": [],
                "open_questions": list(payload.get("clarifications", ())),
            },
            system_context.get("source_refs", ()),
            0.7,
        )
    for item in _items(payload.get("entities")):
        try:
            kind = EntityKind(str(item.get("kind", "")))
        except ValueError:
            state.diagnostics.append(f"compile:unsupported-entity-kind:{item.get('kind')}")
            continue
        if kind.value not in _SOURCE_KINDS:
            state.diagnostics.append(f"compile:entity-kind-not-allowed:{kind.value}")
            continue
        state.ensure(
            str(item.get("local_ref", "")),
            kind,
            str(item.get("name", "")),
            {
                "attributes": dict(item.get("attributes", {}))
                if isinstance(item.get("attributes"), Mapping)
                else {},
            },
            item.get("source_refs", ()),
            item.get("confidence", 0.5),
        )
    requirement_ids: dict[str, str] = {}
    for item in _items(payload.get("requirements")):
        local_ref = str(item.get("local_ref", ""))
        statement = str(item.get("statement", "")).strip()
        requirement_id = state.ensure(
            local_ref,
            EntityKind.REQUIREMENT,
            statement,
            {
                "statement": statement,
                "level": str(item.get("level", "system")),
                "type": str(item.get("type", "functional")),
                "obligation": str(item.get("obligation", "系统应")),
                "verification_method": str(item.get("verification_method", "review")),
                "constraints": _constraint_map(item.get("constraints", ())),
                "constraint_provenance": list(item.get("constraints", ())),
                "inferred_constraints": [
                    dict(constraint)
                    for constraint in _items(item.get("constraints"))
                    if str(constraint.get("source", "")) != "explicit"
                ],
                "related_refs": list(item.get("related_refs", ())),
                "requires_human_review": True,
            },
            item.get("source_refs", ()),
            item.get("confidence", 0.5),
        )
        if local_ref and requirement_id:
            requirement_ids[local_ref] = requirement_id
    return requirement_ids, {"system": state.refs.get("system", "")}


def _compile_scenarios(
    state: _CompilerState,
    payload: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    scenario_ids: dict[str, str] = {}
    scenario_activity_ids: dict[str, tuple[str, ...]] = {}
    for item in _items(payload.get("scenarios")):
        local_ref = str(item.get("local_ref", ""))
        actor_ids = tuple(
            item_id
            for raw in item.get("actor_refs", ())
            if (item_id := state.resolve(raw))
        )
        steps: list[dict[str, Any]] = []
        for step in _items(item.get("steps")):
            actor_id = state.resolve(step.get("actor_ref"))
            if step.get("actor_ref") and actor_id is None:
                state.diagnostics.append(f"compile:unknown-actor:{step.get('actor_ref')}")
            steps.append({
                "order": int(step.get("order", len(steps) + 1)),
                "actor_id": actor_id or "",
                "action": str(step.get("action", "")).strip(),
                "guard": str(step.get("guard", "")).strip(),
            })
        scenario_id = state.ensure(
            local_ref,
            EntityKind.OPERATIONAL_SCENARIO,
            str(item.get("name", "运行场景")),
            {
                "description": str(item.get("description", "")),
                "actor_ids": list(actor_ids),
                "steps": steps,
                "branches": [dict(branch) for branch in _items(item.get("branches"))],
                "requirement_refs": list(item.get("requirement_refs", ())),
                "diagram_kind": "activity_sequence",
                "requires_human_review": True,
            },
            item.get("source_refs", ()),
            item.get("confidence", 0.5),
        )
        if local_ref and scenario_id:
            scenario_ids[local_ref] = scenario_id
        activity_ids: list[str] = []
        for step in steps:
            order = int(step.get("order", len(activity_ids) + 1))
            action = str(step.get("action", "活动")).strip() or "活动"
            activity_id = state.ensure(
                f"{local_ref}_activity_{order}",
                EntityKind.ACTIVITY,
                f"{item.get('name', '场景')} / {order}. {action}",
                {
                    "order": order,
                    "actor_id": step.get("actor_id", ""),
                    "action": action,
                    "guard": step.get("guard", ""),
                    "scenario_id": scenario_id,
                    "next_order": order + 1 if order < len(steps) else None,
                    "diagram_kind": "activity_sequence",
                    "requires_human_review": True,
                },
                item.get("source_refs", ()),
                item.get("confidence", 0.5),
            )
            if activity_id:
                activity_ids.append(activity_id)
        scenario_activity_ids[local_ref] = tuple(activity_ids)
    return scenario_ids, scenario_activity_ids


def _compile_use_cases(
    state: _CompilerState,
    payload: Mapping[str, object],
    requirement_ids: Mapping[str, str],
    scenario_ids: Mapping[str, str],
) -> dict[str, str]:
    use_case_ids: dict[str, str] = {}
    for item in _items(payload.get("use_cases")):
        local_ref = str(item.get("local_ref", ""))
        use_case_id = state.ensure(
            local_ref,
            EntityKind.USE_CASE,
            str(item.get("name", "用例")),
            {
                "goal": str(item.get("goal", "")),
                "primary_actor_ids": [
                    item_id
                    for raw in item.get("primary_actor_refs", ())
                    if (item_id := state.resolve(raw))
                ],
                "preconditions": list(item.get("preconditions", ())),
                "postconditions": list(item.get("postconditions", ())),
                "scenario_ids": [
                    item_id
                    for raw in item.get("scenario_refs", ())
                    if (item_id := state.resolve(raw) or scenario_ids.get(str(raw)))
                ],
                "requirement_ids": [
                    item_id
                    for raw in item.get("requirement_refs", ())
                    if (item_id := state.resolve(raw) or requirement_ids.get(str(raw)))
                ],
                "diagram_kind": "use_case_activity",
                "requires_human_review": True,
            },
            item.get("source_refs", ()),
            item.get("confidence", 0.5),
        )
        if local_ref and use_case_id:
            use_case_ids[local_ref] = use_case_id
    return use_case_ids


def _compile_relations(
    state: _CompilerState,
    payload: Mapping[str, object],
    requirement_ids: Mapping[str, str],
    scenario_ids: Mapping[str, str],
    scenario_activity_ids: Mapping[str, tuple[str, ...]],
    use_case_ids: Mapping[str, str],
) -> None:
    system_id = state.refs.get("system")
    for item in _items(payload.get("entities")):
        if str(item.get("kind", "")) == EntityKind.STAKEHOLDER.value:
            state.relate(system_id, RelationPredicate.DECOMPOSES, item.get("local_ref"), item.get("source_refs", ()))
    for item in _items(payload.get("requirements")):
        requirement_id = requirement_ids.get(str(item.get("local_ref", "")))
        for related in item.get("related_refs", ()):
            state.relate(requirement_id, RelationPredicate.DERIVED_FROM, related, item.get("source_refs", ()))
    for item in _items(payload.get("scenarios")):
        scenario_ref = str(item.get("local_ref", ""))
        scenario_id = scenario_ids.get(scenario_ref)
        for actor in item.get("actor_refs", ()):
            state.relate(actor, RelationPredicate.PARTICIPATES_IN, scenario_id, item.get("source_refs", ()))
        for requirement in item.get("requirement_refs", ()):
            state.relate(requirement, RelationPredicate.DERIVED_FROM, scenario_id, item.get("source_refs", ()))
        for activity_id in scenario_activity_ids.get(scenario_ref, ()):
            state.relate(scenario_id, RelationPredicate.DERIVED_FROM, activity_id, item.get("source_refs", ()))
    for item in _items(payload.get("use_cases")):
        use_case_ref = str(item.get("local_ref", ""))
        use_case_id = use_case_ids.get(use_case_ref)
        for scenario in item.get("scenario_refs", ()):
            state.relate(use_case_id, RelationPredicate.DECOMPOSES, scenario, item.get("source_refs", ()))
        for requirement in item.get("requirement_refs", ()):
            state.relate(requirement, RelationPredicate.DERIVED_FROM, use_case_id, item.get("source_refs", ()))
        for actor in item.get("primary_actor_refs", ()):
            for scenario in item.get("scenario_refs", ()):
                state.relate(actor, RelationPredicate.PARTICIPATES_IN, scenario, item.get("source_refs", ()))


class RequirementsUseCaseService:
    """Create and compile document-driven requirements/behavior proposals."""

    def __init__(
        self,
        repository: ModelRepository,
        project_id: str,
        *,
        model: GenerativeModel | None = None,
        profile_id: str = "offline-rule",
        provider_id: str = "offline",
        model_id: str = "rule-runtime",
        max_output_tokens: int = 4096,
    ) -> None:
        self.repository = repository
        self.project_id = str(project_id).strip()
        if not self.project_id:
            raise ContractViolation("project id is required")
        self.model = model
        self.profile_id = str(profile_id or "offline-rule")
        self.provider_id = str(provider_id or "offline")
        self.model_id = str(model_id or "rule-runtime")
        self.max_output_tokens = max(512, int(max_output_tokens or 4096))

    def create_draft(
        self,
        *,
        text: str | None = None,
        document_ids: Sequence[str] = (),
    ) -> IntakeDraft:
        regions, source_refs, source_text, selected_document_ids = self._sources(
            text=text,
            document_ids=document_ids,
        )
        graph = self.repository.load_graph(self.project_id)
        graph_context = _graph_context(graph)
        input_hash = canonical_hash({
            "project_id": self.project_id,
            "revision": graph.revision,
            "source_refs": source_refs,
            "source_text": source_text,
            "document_ids": selected_document_ids,
        })
        previous = next(
            (item for item in self.list_drafts() if item.input_hash == input_hash),
            None,
        )
        if previous is not None:
            return previous

        user_payload = {
            "schema_version": _SCHEMA_VERSION,
            "input_text": source_text,
            "source_regions": regions,
            "source_refs": source_refs,
            "current_graph": graph_context,
        }
        diagnostics: list[str] = []
        started = time.perf_counter()
        provider_id = self.provider_id
        model_id = self.model_id
        output_hash = ""
        status = "completed"
        if self.model is None:
            payload = _fallback_payload(source_text, source_refs, selected_document_ids)
            status = "degraded"
            diagnostics.append("llm:model_unavailable;使用规则降级草稿")
        else:
            request = GenerationRequest(
                _LENS_ID,
                add_simplified_chinese_instruction(draft_prompt()),
                user_payload,
                draft_schema(),
                self.max_output_tokens,
            )
            try:
                response = self.model.complete_json(request)
                payload = dict(response.payload)
                provider_id = response.provider_id or provider_id
                model_id = response.model_id or model_id
                output_hash = response.output_hash
                status = response.status or status
                if response.repaired:
                    diagnostics.append("llm:structured-output-repaired")
            except (AdapterFailure, ValueError, TypeError, json.JSONDecodeError) as exc:
                payload = _fallback_payload(source_text, source_refs, selected_document_ids)
                status = "degraded"
                diagnostics.append(f"llm:fallback:{_diagnostic_text(exc)}")

        try:
            payload = _prepare_payload(
                payload,
                selected_document_ids=selected_document_ids,
                valid_source_refs=set(source_refs),
                diagnostics=diagnostics,
            )
        except ContractViolation as exc:
            diagnostics.append(f"llm:invalid-envelope:{_diagnostic_text(exc)}")
            payload = _fallback_payload(source_text, source_refs, selected_document_ids)
        try:
            jsonschema.validate(instance=payload, schema=draft_schema())
        except jsonschema.ValidationError as exc:
            diagnostics.append(f"draft:schema-invalid:{exc.message[:240]}")
            payload = _fallback_payload(source_text, source_refs, selected_document_ids)
            payload["diagnostics"] = list(payload.get("diagnostics", ())) + diagnostics[-1:]
            status = "degraded"
            jsonschema.validate(instance=payload, schema=draft_schema())

        payload, merge_diagnostics = _merge_explicit_constraints(payload)
        diagnostics.extend(merge_diagnostics)
        payload["diagnostics"] = list(dict.fromkeys(
            [str(item) for item in payload.get("diagnostics", ())]
            + diagnostics
        ))[:_MAX_DRAFT_DIAGNOSTICS]
        duration_ms = int((time.perf_counter() - started) * 1000)
        draft_id = f"intake-{canonical_hash((self.project_id, input_hash, payload))[:16]}"
        draft = IntakeDraft(
            draft_id,
            self.project_id,
            input_hash,
            status,
            payload,
            provider_id,
            model_id,
            self.profile_id,
            duration_ms,
            output_hash or canonical_hash(payload),
            tuple(payload.get("diagnostics", ())),
            time.time(),
        )
        self.repository.record_audit(
            self.project_id,
            "requirements_use_case.draft_created",
            {
                "draft_id": draft.draft_id,
                "input_hash": draft.input_hash,
                "status": draft.status,
                "profile_id": draft.profile_id,
                "provider_id": draft.provider_id,
                "model_id": draft.model_id,
                "duration_ms": draft.duration_ms,
                "output_hash": draft.output_hash,
                "draft": draft.as_dict(),
            },
        )
        return draft

    def list_drafts(self) -> tuple[IntakeDraft, ...]:
        records: list[IntakeDraft] = []
        seen: set[str] = set()
        for event in reversed(self.repository.list_audit_events(self.project_id)):
            if str(event.get("kind", "")) != "requirements_use_case.draft_created":
                continue
            raw = event.get("payload", {})
            if not isinstance(raw, Mapping):
                continue
            value = raw.get("draft")
            if not isinstance(value, Mapping):
                continue
            try:
                draft = IntakeDraft.from_dict(value)
            except (TypeError, ValueError):
                continue
            if not draft.draft_id or draft.draft_id in seen:
                continue
            seen.add(draft.draft_id)
            records.append(draft)
        return tuple(records)

    def get_draft(self, draft_id: str) -> IntakeDraft:
        clean = str(draft_id).strip()
        if not clean:
            raise ContractViolation("draft id is required")
        draft = next((item for item in self.list_drafts() if item.draft_id == clean), None)
        if draft is None:
            raise ContractViolation(f"draft not found: {clean}")
        return draft

    def apply_draft(
        self,
        draft: IntakeDraft | Mapping[str, object],
    ) -> Mapping[str, object]:
        intake = draft if isinstance(draft, IntakeDraft) else IntakeDraft.from_dict(draft)
        if intake.project_id and intake.project_id != self.project_id:
            raise ContractViolation("draft project does not match request")
        payload = dict(intake.payload)
        try:
            jsonschema.validate(instance=payload, schema=draft_schema())
        except jsonschema.ValidationError as exc:
            raise ContractViolation(f"invalid intake draft: {exc.message}") from exc

        graph = self.repository.load_graph(self.project_id)
        valid_sources = {
            str(item.get("id", ""))
            for item in self.repository.list_evidence(self.project_id)
            if str(item.get("id", "")).strip()
        }
        valid_sources.update(
            str(item.get("id", ""))
            for item in self.repository.list_source_regions(self.project_id)
            if str(item.get("id", "")).strip()
        )
        diagnostics = [str(item) for item in payload.get("diagnostics", ())]
        state = _new_compiler_state(
            self.project_id,
            graph,
            valid_sources,
            diagnostics,
            Producer.RULE if intake.status == "degraded" else Producer.LLM,
        )
        requirement_ids, _ = _compile_base_entities(state, payload)
        scenario_ids, scenario_activity_ids = _compile_scenarios(state, payload)
        use_case_ids = _compile_use_cases(
            state,
            payload,
            requirement_ids,
            scenario_ids,
        )
        _compile_relations(
            state,
            payload,
            requirement_ids,
            scenario_ids,
            scenario_activity_ids,
            use_case_ids,
        )
        return self._commit_draft(intake, state)

    def _commit_draft(
        self,
        intake: IntakeDraft,
        state: _CompilerState,
    ) -> Mapping[str, object]:
        draft_id = intake.draft_id or f"intake-{canonical_hash(intake.payload)[:16]}"
        already_applied = next(
            (
                event for event in self.repository.list_audit_events(self.project_id)
                if str(event.get("kind", "")) == "requirements_use_case.draft_applied"
                and isinstance(event.get("payload"), Mapping)
                and str(event["payload"].get("draft_id", "")) == draft_id
            ),
            None,
        )
        diagnostics = list(dict.fromkeys(state.diagnostics))[:_MAX_DRAFT_DIAGNOSTICS]
        if already_applied is not None:
            applied_payload = already_applied.get("payload", {})
            return {
                "status": "ok",
                "draft_id": draft_id,
                "applied": False,
                "idempotent": True,
                "revision": (
                    applied_payload.get("revision", state.graph.revision)
                    if isinstance(applied_payload, Mapping)
                    else state.graph.revision
                ),
                "diagnostics": tuple(diagnostics),
                "created_entity_count": 0,
                "created_relation_count": 0,
            }

        revision = state.graph.revision
        entity_count = sum(isinstance(item, AddEntity) for item in state.operations)
        relation_count = sum(isinstance(item, Relate) for item in state.operations)
        if state.operations:
            patch = Patch.create(
                self.project_id,
                "requirements_use_case.apply",
                tuple(state.operations),
                "应用需求与用例智能提取候选",
                state.graph.revision,
            )
            revision = self.repository.append_patch(
                self.project_id,
                patch,
                state.graph.revision,
            ).sequence
        self.repository.record_audit(
            self.project_id,
            "requirements_use_case.draft_applied",
            {
                "draft_id": draft_id,
                "revision": revision,
                "created_entity_count": entity_count,
                "created_relation_count": relation_count,
                "diagnostics": diagnostics,
            },
        )
        return {
            "status": "ok",
            "draft_id": draft_id,
            "applied": bool(state.operations),
            "idempotent": False,
            "revision": revision,
            "diagnostics": tuple(diagnostics),
            "created_entity_count": entity_count,
            "created_relation_count": relation_count,
        }

    def _sources(
        self,
        *,
        text: str | None,
        document_ids: Sequence[str],
    ) -> tuple[list[dict[str, Any]], tuple[str, ...], str, tuple[str, ...]]:
        clean_text = "\n".join(str(text or "").splitlines()).strip()
        selected = tuple(dict.fromkeys(str(item).strip() for item in document_ids if str(item).strip()))
        regions = [dict(item) for item in self.repository.list_source_regions(self.project_id, selected)]
        source_refs = [str(item.get("id", "")) for item in regions if str(item.get("id", "")).strip()]
        source_texts = [str(item.get("text", "")).strip() for item in regions if str(item.get("text", "")).strip()]
        if clean_text:
            text_ref = f"text-input-{canonical_hash((self.project_id, clean_text))[:16]}"
            self.repository.save_evidence(
                self.project_id,
                {
                    "id": text_ref,
                    "source_type": "user_text",
                    "source_id": self.project_id,
                    "locator": "requirements-use-case-input",
                    "claim": "用户文本需求输入",
                    "excerpt": clean_text,
                    "relevance": 1.0,
                },
            )
            source_refs.append(text_ref)
            source_texts.append(clean_text)
        source_refs = list(dict.fromkeys(source_refs))
        if not source_texts:
            raise InputRequired("requirement text or readable document content is required")
        return (
            regions,
            tuple(source_refs),
            "\n".join(source_texts),
            tuple(dict.fromkeys(str(item.get("document_id", "")) for item in regions if str(item.get("document_id", "")).strip())),
        )


def _items(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _diagnostic_text(exc: BaseException) -> str:
    text = " ".join(str(exc).split()).replace("\n", " ")
    return text[:240] or type(exc).__name__


def _graph_context(graph: ModelGraph) -> dict[str, Any]:
    entities = []
    for entity in graph.entities:
        if entity.meta.status is EntityStatus.DEPRECATED:
            continue
        payload = entity.payload
        entities.append({
            "id": entity.id,
            "kind": entity.kind.value,
            "name": entity.meta.name,
            "status": entity.meta.status.value,
            "payload": {
                key: payload[key]
                for key in (
                    "statement",
                    "mission",
                    "goal",
                    "description",
                    "constraints",
                    "steps",
                    "scenario_ids",
                    "primary_actor_ids",
                )
                if key in payload
            },
        })
    return {
        "project_id": graph.project_id,
        "revision": graph.revision,
        "entities": entities,
        "relations": [
            {
                "source_id": item.source_id,
                "predicate": item.predicate.value,
                "target_id": item.target_id,
            }
            for item in graph.relations
        ],
    }


def _fallback_payload(text: str, source_refs: Sequence[str], document_ids: Sequence[str]) -> dict[str, Any]:
    statements = split_requirement_statements(text)
    if not statements and text.strip():
        statements = (" ".join(text.split()).strip(),)
    refs = list(dict.fromkeys(str(item) for item in source_refs if str(item).strip()))
    requirements = []
    diagnostics: list[str] = []
    for index, statement in enumerate(statements, start=1):
        explicit = extract_requirement_constraints(statement)
        inferred = infer_requirement_constraints(statement, refs)
        constraints = []
        for item in explicit.get("constraint_provenance", ()):
            constraints.append({
                "field": item.get("field", ""),
                "operator": item.get("operator", "eq"),
                "value": float(item.get("value", 0)),
                "unit": str(item.get("unit", "")),
                "source": "explicit",
                "source_refs": refs,
                "confidence": 1.0,
                "assumption": "",
            })
        constraints.extend(inferred)
        if inferred:
            diagnostics.extend(
                f"rule:derived-constraint:{item['field']}"
                for item in inferred
            )
        safety_fields = {"fail_safe_behavior", "fault_tolerance"}
        requirements.append({
            "local_ref": f"requirement_{index}",
            "statement": statement,
            "level": "system",
            "type": "safety" if any(item["field"] in safety_fields for item in inferred) else ("performance" if explicit.get("constraint_provenance") else "functional"),
            "obligation": "系统应",
            "verification_method": "test" if constraints else "review",
            "constraints": constraints,
            "source_refs": refs,
            "confidence": 0.55 if constraints else 0.45,
            "related_refs": [],
        })
    actor_ref = "actor_operator"
    combined = text.casefold()
    has_actor = any(token in combined for token in ("用户", "操作员", "指挥员", "维护人员", "operator", "user"))
    entities = []
    if has_actor:
        entities.append({
            "local_ref": actor_ref,
            "kind": "stakeholder",
            "name": "操作员",
            "attributes": {"role": "任务执行者"},
            "source_refs": refs,
            "confidence": 0.45,
        })
    scenario_ref = "scenario_primary"
    steps = [
        {
            "order": index,
            "actor_ref": actor_ref if has_actor and index % 2 else "system",
            "action": statement,
            "guard": "",
        }
        for index, statement in enumerate(statements[:8], start=1)
    ]
    return {
        "schema_version": _SCHEMA_VERSION,
        "source_document_ids": list(document_ids),
        "system_context": {"name": "目标系统", "mission": "待确认", "source_refs": refs},
        "entities": entities,
        "requirements": requirements,
        "use_cases": [{
            "local_ref": "use_case_primary",
            "name": "执行主要任务",
            "goal": statements[0] if statements else "待确认任务目标",
            "primary_actor_refs": [actor_ref] if has_actor else [],
            "preconditions": [],
            "postconditions": [],
            "scenario_refs": [scenario_ref],
            "requirement_refs": [item["local_ref"] for item in requirements],
            "source_refs": refs,
            "confidence": 0.4,
        }],
        "scenarios": [{
            "local_ref": scenario_ref,
            "kind": "operational_scenario",
            "name": "完成主要任务",
            "description": "基于输入文本形成的待确认运行场景框架",
            "actor_refs": [actor_ref] if has_actor else [],
            "steps": steps or [{"order": 1, "actor_ref": "system", "action": "执行任务", "guard": ""}],
            "branches": [],
            "requirement_refs": [item["local_ref"] for item in requirements],
            "source_refs": refs,
            "confidence": 0.35,
        }],
        "clarifications": [{
            "question": "请确认任务参与者、成功判据以及未明确的性能边界。",
            "related_refs": [item["local_ref"] for item in requirements],
            "severity": "medium",
        }],
        "diagnostics": list(dict.fromkeys(diagnostics)),
    }


def _prepare_payload(
    raw: object,
    *,
    selected_document_ids: Sequence[str],
    valid_source_refs: set[str],
    diagnostics: list[str],
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ContractViolation("structured intake response must be an object")
    payload = dict(raw)
    payload.setdefault("schema_version", _SCHEMA_VERSION)
    payload.setdefault("source_document_ids", list(selected_document_ids))
    payload.setdefault("system_context", {"name": "目标系统", "mission": "", "source_refs": []})
    for key in ("entities", "requirements", "use_cases", "scenarios", "clarifications", "diagnostics"):
        payload.setdefault(key, [])
    if not isinstance(payload.get("source_document_ids"), list):
        payload["source_document_ids"] = list(selected_document_ids)
    for key in ("entities", "requirements", "use_cases", "scenarios", "clarifications", "diagnostics"):
        if not isinstance(payload.get(key), list):
            payload[key] = list(payload.get(key, ())) if isinstance(payload.get(key), (tuple, set, frozenset)) else []
    system_context = payload.get("system_context")
    if isinstance(system_context, Mapping):
        context = dict(system_context)
        context.setdefault("name", "目标系统")
        context.setdefault("mission", "")
        context.setdefault("source_refs", [])
        context["source_refs"] = _clean_refs(context.get("source_refs"), valid_source_refs, diagnostics, "system_context")
        payload["system_context"] = context
    for index, item in enumerate(_items(payload.get("entities"))):
        value = dict(item)
        value.setdefault("attributes", {})
        value.setdefault("source_refs", [])
        value.setdefault("confidence", 0.5)
        value["source_refs"] = _clean_refs(value.get("source_refs"), valid_source_refs, diagnostics, f"entity[{index}]")
        payload["entities"][index] = value
    for index, item in enumerate(_items(payload.get("requirements"))):
        value = dict(item)
        value.setdefault("constraints", [])
        value.setdefault("source_refs", [])
        value.setdefault("confidence", 0.5)
        value.setdefault("related_refs", [])
        value["source_refs"] = _clean_refs(value.get("source_refs"), valid_source_refs, diagnostics, f"requirement[{index}]")
        constraints = []
        for constraint in _items(value.get("constraints")):
            candidate = dict(constraint)
            candidate.setdefault("source", "llm_inferred")
            candidate.setdefault("source_refs", value["source_refs"])
            candidate.setdefault("confidence", value.get("confidence", 0.5))
            candidate.setdefault("assumption", "")
            candidate["source_refs"] = _clean_refs(candidate.get("source_refs"), valid_source_refs, diagnostics, f"requirement[{index}].constraint")
            constraints.append(candidate)
        value["constraints"] = constraints
        payload["requirements"][index] = value
    for collection_name in ("use_cases", "scenarios"):
        for index, item in enumerate(_items(payload.get(collection_name))):
            value = dict(item)
            value.setdefault("source_refs", [])
            value.setdefault("confidence", 0.5)
            value["source_refs"] = _clean_refs(value.get("source_refs"), valid_source_refs, diagnostics, f"{collection_name}[{index}]")
            payload[collection_name][index] = value
    return payload


def _clean_refs(value: object, valid: set[str], diagnostics: list[str], label: str) -> list[str]:
    refs = [str(item).strip() for item in value] if isinstance(value, (list, tuple)) else []
    result = []
    for ref in refs:
        if not ref:
            continue
        if ref not in valid:
            diagnostics.append(f"source:unknown-ref:{label}:{ref}")
            continue
        if ref not in result:
            result.append(ref)
    return result


def _merge_explicit_constraints(payload: dict[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    diagnostics: list[str] = []
    requirements = []
    for item in _items(payload.get("requirements")):
        value = dict(item)
        statement = str(value.get("statement", ""))
        explicit = extract_requirement_constraints(statement)
        explicit_by_key: dict[str, dict[str, Any]] = {}
        for raw in _items(explicit.get("constraint_provenance")):
            field = str(raw.get("field", ""))
            operator = str(raw.get("operator", ""))
            key = f"{operator}_{field}"
            explicit_by_key[key] = {
                "field": field,
                "operator": operator,
                "value": float(raw.get("value", 0)),
                "unit": str(raw.get("unit", "")),
                "source": "explicit",
                "source_refs": list(value.get("source_refs", ())),
                "confidence": 1.0,
                "assumption": "",
            }
        merged: dict[str, dict[str, Any]] = {}
        for constraint in _items(value.get("constraints")):
            candidate = dict(constraint)
            key = f"{candidate.get('operator', '')}_{candidate.get('field', '')}"
            source = str(candidate.get("source", "llm_inferred"))
            if source not in _CONSTRAINT_SOURCES:
                source = "llm_inferred"
                candidate["source"] = source
            if key in explicit_by_key and source != "explicit":
                diagnostics.append(f"constraint:explicit-wins:{key}")
                continue
            merged[key] = candidate
        merged.update(explicit_by_key)
        value["constraints"] = list(merged.values())
        requirements.append(value)
    payload["requirements"] = requirements
    return payload, tuple(dict.fromkeys(diagnostics))


def _constraint_map(value: object) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in _items(value):
        field = str(item.get("field", "")).strip()
        operator = str(item.get("operator", "")).strip()
        if not field or not operator:
            continue
        try:
            result[f"{operator}_{field}"] = float(item.get("value", 0))
        except (TypeError, ValueError):
            continue
    return result


def _valid_refs(value: Sequence[object] | object, valid: set[str]) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip() and str(item).strip() in valid))


def _find_entity(entities: Sequence[Entity] | Any, kind: EntityKind, name: str) -> Entity | None:
    normalized = _normalize_name(name)
    for entity in entities:
        if entity.kind is kind and entity.meta.status is not EntityStatus.DEPRECATED and _normalize_name(entity.meta.name) == normalized:
            return entity
        if kind is EntityKind.REQUIREMENT and entity.kind is kind and entity.meta.status is not EntityStatus.DEPRECATED:
            statement = str(entity.payload.get("statement", ""))
            if statement and _normalize_name(statement) == normalized:
                return entity
    return None


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


__all__ = [
    "IntakeDraft",
    "RequirementsUseCaseService",
    "draft_prompt",
    "draft_schema",
]
