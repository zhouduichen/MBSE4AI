"""Single scenario, normalization, and evaluator boundary for A–E."""

from __future__ import annotations

from dataclasses import dataclass, replace
import time
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.closure import evaluate_release_closure, evaluate_technical_closure
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse, GenerativeModel

from tests.mbse_benchmark.scenarios import BenchmarkScenario, ScenarioContract
from tests.mbse_benchmark.runners.experiment_contract import (
    BenchmarkInputEnvelope,
    EvaluationSpec,
    assert_model_visible_payload,
)
from tests.mbse_benchmark.validators.case import validate_case


TASK_SPEC: Mapping[str, object] = {
    "methodology_version": "v0.3.2",
    "input_rule": "Generate only from the complete supplied declared case input; do not use evaluator-only reference outputs.",
    "graph_rule": "Return a typed ModelGraph with RFLP and verification/validation relations.",
}

EXTERNAL_EVALUATOR_ID = (
    "tests.mbse_benchmark.runners.scenario_pipeline.ExternalEvaluator:v0.3.2"
)
MODEL_GRAPH_NORMALIZER_ID = (
    "tests.mbse_benchmark.runners.scenario_pipeline.ModelGraphNormalizer:v0.3.2"
)

_ENTITY_KINDS = tuple(item.value for item in EntityKind)
_ENTITY_STATUSES = tuple(item.value for item in EntityStatus)
_PRODUCERS = tuple(item.value for item in Producer)
_PREDICATES = tuple(item.value for item in RelationPredicate)

MODEL_GRAPH_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["project_id", "revision", "entities", "relations"],
    "properties": {
        "project_id": {"type": "string", "minLength": 1},
        "revision": {"type": "integer", "minimum": 0},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "kind", "name", "status", "producer", "payload"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "kind": {"type": "string", "enum": list(_ENTITY_KINDS)},
                    "name": {"type": "string", "minLength": 1},
                    "status": {"type": "string", "enum": list(_ENTITY_STATUSES)},
                    "producer": {"type": "string", "enum": list(_PRODUCERS)},
                    "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
                    "source_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "payload": {"type": "object"},
                },
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "source_id", "predicate", "target_id"],
                "properties": {
                    "id": {"type": "string", "minLength": 1},
                    "source_id": {"type": "string", "minLength": 1},
                    "predicate": {"type": "string", "enum": list(_PREDICATES)},
                    "target_id": {"type": "string", "minLength": 1},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


@dataclass(frozen=True, slots=True)
class RunMetadata:
    scenario: str
    model: str
    provider: str
    prompt_hash: str
    task_spec_hash: str
    temperature: float | None
    input_hash: str
    token_usage: Mapping[str, object] | None
    latency_ms: int | None
    graph_hash: str
    verifier_enabled: bool
    gate_enabled: bool
    repair_enabled: bool
    cas_enabled: bool
    normalizer_id: str = MODEL_GRAPH_NORMALIZER_ID

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "model": self.model,
            "provider": self.provider,
            "prompt_hash": self.prompt_hash,
            "task_spec_hash": self.task_spec_hash,
            "temperature": self.temperature,
            "input_hash": self.input_hash,
            "token_usage": dict(self.token_usage) if self.token_usage is not None else None,
            "latency_ms": self.latency_ms,
            "graph_hash": self.graph_hash,
            "verifier_enabled": self.verifier_enabled,
            "gate_enabled": self.gate_enabled,
            "repair_enabled": self.repair_enabled,
            "cas_enabled": self.cas_enabled,
            "normalizer_id": self.normalizer_id,
        }


@dataclass(frozen=True, slots=True)
class NormalizationAudit:
    """Audit the authority claims made by a model response."""

    claimed_statuses: Mapping[str, str]
    claimed_producers: Mapping[str, str]
    lifecycle_claims: tuple[str, ...] = ()
    authority_violations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "claimed_statuses": dict(self.claimed_statuses),
            "claimed_producers": dict(self.claimed_producers),
            "lifecycle_claims": list(self.lifecycle_claims),
            "authority_violations": list(self.authority_violations),
        }


@dataclass(frozen=True, slots=True)
class NormalizedGraph:
    graph: ModelGraph
    audit: NormalizationAudit


@dataclass(frozen=True, slots=True)
class ScenarioOutput:
    graph: ModelGraph
    metadata: RunMetadata
    responses: tuple[GenerationResponse, ...]
    normalization_audit: NormalizationAudit = NormalizationAudit({}, {})


class ModelGraphNormalizer:
    """Convert every scenario output to the canonical ModelGraph shape."""

    normalizer_id = MODEL_GRAPH_NORMALIZER_ID

    def normalize(self, value: object, *, project_id: str = "benchmark") -> ModelGraph:
        return self.normalize_with_audit(value, project_id=project_id).graph

    def normalize_with_audit(
        self,
        value: object,
        *,
        project_id: str = "benchmark",
    ) -> NormalizedGraph:
        if isinstance(value, ModelGraph):
            return self._force_graph_authority(value)
        candidate = value.get("graph", value) if isinstance(value, Mapping) else value
        if isinstance(candidate, ModelGraph):
            return self._force_graph_authority(candidate)
        if isinstance(candidate, Mapping) and "entities" in candidate:
            return self._graph_from_mapping(candidate, project_id)
        payload = candidate if isinstance(candidate, Mapping) else {}
        entities = []
        for item in payload.get("requirements", ()):
            if not isinstance(item, Mapping):
                continue
            statement = str(item.get("statement", item.get("name", ""))).strip()
            if not statement:
                continue
            entities.append(make_entity(
                EntityKind.REQUIREMENT,
                statement,
                {"statement": statement, "verification_method": item.get("verification_method", "")},
                status=EntityStatus.CANDIDATE,
                producer=Producer.LLM,
            ))
        return NormalizedGraph(
            ModelGraph(project_id, tuple(entities), (), 0),
            NormalizationAudit({}, {}),
        )

    def normalize_canonical(
        self,
        value: object,
        *,
        project_id: str = "benchmark",
    ) -> ModelGraph:
        """Parse an already-governed Harness graph without rewriting status."""

        candidate = value.get("graph", value) if isinstance(value, Mapping) else value
        if isinstance(candidate, ModelGraph):
            return candidate
        if isinstance(candidate, Mapping) and "entities" in candidate:
            return self._graph_from_mapping(
                candidate,
                project_id,
                enforce_model_authority=False,
            ).graph
        return ModelGraph(project_id, (), (), 0)

    @staticmethod
    def semantic_projection(graph: ModelGraph) -> ModelGraph:
        """Return a private status-neutral graph for semantic scoring only."""

        entities = tuple(
            replace(
                entity,
                meta=replace(
                    entity.meta,
                    status=(
                        EntityStatus.VALIDATED
                        if entity.meta.status is EntityStatus.CANDIDATE
                        else entity.meta.status
                    ),
                ),
            )
            for entity in graph.entities
        )
        return ModelGraph(graph.project_id, entities, graph.relations, graph.revision)

    def payload(self, graph: ModelGraph) -> dict[str, object]:
        return {
            "project_id": graph.project_id,
            "revision": graph.revision,
            "snapshot_hash": graph.snapshot_hash,
            "entities": [item.as_dict() for item in graph.entities],
            "relations": [
                {
                    "id": item.id,
                    "source_id": item.source_id,
                    "predicate": item.predicate.value,
                    "target_id": item.target_id,
                    "evidence_ids": list(item.evidence_ids),
                }
                for item in graph.relations
            ],
        }

    def _graph_from_mapping(
        self,
        value: Mapping[str, object],
        project_id: str,
        *,
        enforce_model_authority: bool = True,
    ) -> NormalizedGraph:
        raw_entities = [item for item in value.get("entities", ()) if isinstance(item, Mapping)]
        entities = []
        id_map: dict[str, str] = {}
        claimed_statuses: dict[str, str] = {}
        claimed_producers: dict[str, str] = {}
        lifecycle_claims: list[str] = []
        authority_violations: list[str] = []
        for item in raw_entities:
            entity, raw_id, raw_status, raw_producer = self._entity_from_mapping(
                item,
                enforce_model_authority=enforce_model_authority,
            )
            entities.append(entity)
            if raw_id:
                id_map[raw_id] = entity.id
                claimed_statuses[raw_id] = raw_status
                claimed_producers[raw_id] = raw_producer
                if enforce_model_authority and raw_status != EntityStatus.CANDIDATE.value:
                    lifecycle_claims.append(raw_id)
                if enforce_model_authority and (
                    raw_status in {EntityStatus.ACCEPTED.value, EntityStatus.LOCKED.value}
                    or raw_producer == Producer.USER.value
                ):
                    authority_violations.append(raw_id)
        relations = []
        for item in value.get("relations", ()):
            if not isinstance(item, Mapping):
                continue
            source_id = id_map.get(str(item.get("source_id", "")), str(item.get("source_id", "")))
            target_id = id_map.get(str(item.get("target_id", "")), str(item.get("target_id", "")))
            if not source_id or not target_id:
                continue
            try:
                predicate = RelationPredicate(str(item.get("predicate", "")))
            except ValueError:
                continue
            relations.append(Relation(
                str(item.get("id", f"relation-{len(relations) + 1:04d}")),
                source_id,
                predicate,
                target_id,
                tuple(str(item_id) for item_id in item.get("evidence_ids", ()) if str(item_id)),
            ))
        return NormalizedGraph(
            ModelGraph(
                str(value.get("project_id", project_id)),
                tuple(entities),
                tuple(relations),
                int(value.get("revision", 0) or 0),
            ),
            NormalizationAudit(
                claimed_statuses,
                claimed_producers,
                tuple(dict.fromkeys(lifecycle_claims)),
                tuple(dict.fromkeys(authority_violations)),
            ),
        )

    @staticmethod
    def _entity_from_mapping(
        value: Mapping[str, object],
        *,
        enforce_model_authority: bool = True,
    ):
        try:
            kind = EntityKind(str(value.get("kind", EntityKind.REQUIREMENT.value)))
        except ValueError:
            kind = EntityKind.REQUIREMENT
        raw_status = str(value.get("status", EntityStatus.CANDIDATE.value))
        raw_producer = str(value.get("producer", Producer.LLM.value))
        if enforce_model_authority:
            status = EntityStatus.CANDIDATE
            producer = Producer.LLM
        else:
            try:
                status = EntityStatus(raw_status)
            except ValueError:
                status = EntityStatus.CANDIDATE
            try:
                producer = Producer(raw_producer)
            except ValueError:
                producer = Producer.LLM
        entity = make_entity(
            kind,
            str(value.get("name", kind.value)),
            value.get("payload", {}) if isinstance(value.get("payload", {}), Mapping) else {},
            status=status,
            producer=producer,
            confidence=value.get("confidence"),
            source_ids=tuple(str(item) for item in value.get("source_ids", ()) if str(item)),
            evidence_ids=tuple(str(item) for item in value.get("evidence_ids", ()) if str(item)),
        )
        raw_id = str(value.get("id", "")).strip()
        if raw_id:
            entity = replace(entity, meta=replace(entity.meta, id=raw_id))
        return entity, raw_id, raw_status, raw_producer

    @staticmethod
    def _force_graph_authority(graph: ModelGraph) -> NormalizedGraph:
        claimed_statuses = {entity.id: entity.meta.status.value for entity in graph.entities}
        claimed_producers = {entity.id: entity.meta.producer.value for entity in graph.entities}
        lifecycle_claims = tuple(
            entity.id
            for entity in graph.entities
            if entity.meta.status is not EntityStatus.CANDIDATE
        )
        authority_violations = tuple(
            entity.id
            for entity in graph.entities
            if entity.meta.status in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}
            or entity.meta.producer is Producer.USER
        )
        entities = tuple(
            replace(
                entity,
                meta=replace(entity.meta, status=EntityStatus.CANDIDATE, producer=Producer.LLM),
            )
            for entity in graph.entities
        )
        return NormalizedGraph(
            ModelGraph(graph.project_id, entities, graph.relations, graph.revision),
            NormalizationAudit(
                claimed_statuses,
                claimed_producers,
                lifecycle_claims,
                authority_violations,
            ),
        )


class ExternalEvaluator:
    """Evaluate only normalized graphs against the shared case contract."""

    evaluator_id = EXTERNAL_EVALUATOR_ID

    def __init__(self, normalizer: ModelGraphNormalizer | None = None):
        self.normalizer = normalizer or ModelGraphNormalizer()

    def evaluate(
        self,
        case: Mapping[str, object] | BenchmarkInputEnvelope,
        graph: ModelGraph,
        expectations: Mapping[str, object] | EvaluationSpec,
        *,
        execution: Mapping[str, object] | None = None,
        raw_result: Mapping[str, object] | None = None,
        repeats: list[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        input_envelope = (
            case
            if isinstance(case, BenchmarkInputEnvelope)
            else BenchmarkInputEnvelope.from_case(case)
        )
        evaluation_spec = (
            expectations
            if isinstance(expectations, EvaluationSpec)
            else EvaluationSpec.from_expectations(expectations)
        )
        observed = dict(raw_result or {})
        observed.update({
            "graph": self.normalizer.payload(graph),
            "execution": dict(execution or observed.get("execution", {"status": "completed"})),
        })
        semantic_graph = self.normalizer.semantic_projection(graph)
        semantic_observed = dict(observed)
        semantic_observed["graph"] = self.normalizer.payload(semantic_graph)
        result = validate_case(
            input_envelope.payload,
            semantic_observed,
            evaluation_spec.payload,
            repeats=repeats,
        )
        raw_audit = observed.get("normalization_audit")
        audit = (
            raw_audit.as_dict()
            if isinstance(raw_audit, NormalizationAudit)
            else dict(raw_audit)
            if isinstance(raw_audit, Mapping)
            else {}
        )
        technical = evaluate_technical_closure(graph)
        release = evaluate_release_closure(graph)
        semantic_metrics = dict(result.get("metrics", {}))
        governance_metrics = {
            "authority_violation_count": len(audit.get("authority_violations", ())),
            "lifecycle_claim_count": len(audit.get("lifecycle_claims", ())),
            "authority_violations": list(audit.get("authority_violations", ())),
            "technical_closure": technical.as_dict(),
            "release_closure": release.as_dict(),
            "verifier_enabled": observed.get("verifier_enabled"),
            "gate_enabled": observed.get("gate_enabled"),
            "repair_enabled": observed.get("repair_enabled"),
            "cas_enabled": observed.get("cas_enabled"),
        }
        result["semantic_metrics"] = semantic_metrics
        result["governance_metrics"] = governance_metrics
        result.setdefault("details", {})["governance"] = governance_metrics
        result["input_hash"] = input_envelope.input_hash
        result["evaluation_spec_hash"] = evaluation_spec.evaluation_spec_hash
        return result


class ScenarioRunner:
    """Run bare A/B model calls with no Harness or expected-graph shortcut."""

    def __init__(self, normalizer: ModelGraphNormalizer | None = None):
        self.normalizer = normalizer or ModelGraphNormalizer()

    def run(
        self,
        case: Mapping[str, object] | BenchmarkInputEnvelope,
        contract: ScenarioContract,
        model: GenerativeModel,
        *,
        project_id: str,
        token_budget: int = 3000,
        evaluation_spec: EvaluationSpec | None = None,
    ) -> ScenarioOutput:
        if contract.scenario not in {
            BenchmarkScenario.A_BARE_ONE_SHOT,
            BenchmarkScenario.B_BARE_STAGED,
        }:
            raise ValueError(f"ScenarioRunner only owns bare scenarios: {contract.scenario.value}")
        input_envelope = (
            case
            if isinstance(case, BenchmarkInputEnvelope)
            else BenchmarkInputEnvelope.from_case(case)
        )
        model_input = dict(input_envelope.payload)
        visible_spec = evaluation_spec or EvaluationSpec.from_expectations({})
        responses: list[GenerationResponse] = []
        requests: list[GenerationRequest] = []
        payload: Mapping[str, object] = {
            "project_id": project_id,
            "revision": 0,
            "entities": [],
            "relations": [],
        }
        stages = ("one_shot",) if contract.scenario is BenchmarkScenario.A_BARE_ONE_SHOT else (
            "requirements", "functional", "logical", "physical", "verification_validation",
        )
        started = time.monotonic()
        for stage in stages:
            system_prompt = _system_prompt(stage)
            user_payload: dict[str, object] = {
                "task_spec": dict(TASK_SPEC),
                "case_input": model_input,
                "current_graph": payload,
                "stage": stage,
            }
            request = GenerationRequest(
                f"benchmark.{contract.scenario.value}.{stage}",
                system_prompt,
                user_payload,
                MODEL_GRAPH_SCHEMA,
                token_budget,
            )
            assert_model_visible_payload(user_payload, visible_spec)
            requests.append(request)
            response = model.complete_json(request)
            responses.append(response)
            response_payload = response.payload if isinstance(response.payload, Mapping) else {}
            payload = _merge_graph_payload(payload, response_payload, project_id)
        normalized = self.normalizer.normalize_with_audit(payload, project_id=project_id)
        graph = normalized.graph
        duration_ms = max(0, int((time.monotonic() - started) * 1000))
        usage = _sum_usage(responses)
        last = responses[-1] if responses else None
        provider = str(getattr(last, "provider_id", "") or _config_value(model, "provider", "offline"))
        model_id = str(getattr(last, "model_id", "") or _config_value(model, "model", "unknown"))
        temperature = _config_float(model, "temperature")
        metadata = RunMetadata(
            scenario=contract.scenario.value,
            model=model_id,
            provider=provider,
            prompt_hash=canonical_hash([
                (item.lens_id, item.system_prompt, item.user_payload)
                for item in requests
            ]),
            task_spec_hash=canonical_hash(TASK_SPEC),
            temperature=temperature,
            input_hash=input_envelope.input_hash,
            token_usage=usage,
            latency_ms=sum(int(getattr(item, "duration_ms", 0) or 0) for item in responses) or duration_ms,
            graph_hash=graph.snapshot_hash,
            verifier_enabled=contract.has_verifier,
            gate_enabled=contract.gate_enabled,
            repair_enabled=contract.has_repair,
            cas_enabled=contract.has_cas,
        )
        return ScenarioOutput(graph, metadata, tuple(responses), normalized.audit)


def model_input_for_case(case: Mapping[str, object] | BenchmarkInputEnvelope) -> dict[str, object]:
    """Return the complete declared input, including visible requirements."""

    if isinstance(case, BenchmarkInputEnvelope):
        return dict(case.payload)
    return dict(BenchmarkInputEnvelope.from_case(case).payload)


def _system_prompt(stage: str) -> str:
    if stage == "one_shot":
        return "根据 case_input 一次性生成完整 ModelGraph，覆盖 R→F→L→P→V&V；不要读取或假设任何 expected graph。"
    return f"根据 case_input 生成 {stage} 阶段可观察的 ModelGraph 增量；只使用 current_graph 和 case_input，不要读取 expected graph。"


def _merge_graph_payload(
    current: Mapping[str, object],
    incoming: Mapping[str, object],
    project_id: str,
) -> dict[str, object]:
    candidate = incoming.get("graph", incoming)
    if not isinstance(candidate, Mapping):
        return dict(current)
    entities: dict[str, Mapping[str, object]] = {}
    for item in (*current.get("entities", ()), *candidate.get("entities", ())):
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("id") or f"{item.get('kind', '')}:{item.get('name', '')}")
        entities[key] = item
    relations: dict[str, Mapping[str, object]] = {}
    for item in (*current.get("relations", ()), *candidate.get("relations", ())):
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("id") or canonical_hash(item))
        relations[key] = item
    return {
        "project_id": str(candidate.get("project_id", current.get("project_id", project_id))),
        "revision": int(candidate.get("revision", current.get("revision", 0)) or 0),
        "entities": list(entities.values()),
        "relations": list(relations.values()),
    }


def _sum_usage(responses: list[GenerationResponse]) -> dict[str, object] | None:
    usage: dict[str, int] = {}
    for response in responses:
        raw = getattr(response, "usage", {})
        if not isinstance(raw, Mapping):
            continue
        for key, value in raw.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[str(key)] = usage.get(str(key), 0) + int(value)
    return usage or None


def _config_value(model: object, key: str, default: object) -> object:
    config = getattr(model, "_config", {})
    return config.get(key, default) if isinstance(config, Mapping) else default


def _config_float(model: object, key: str) -> float | None:
    value = _config_value(model, key, None)
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "EXTERNAL_EVALUATOR_ID",
    "MODEL_GRAPH_NORMALIZER_ID",
    "ExternalEvaluator",
    "MODEL_GRAPH_SCHEMA",
    "ModelGraphNormalizer",
    "NormalizationAudit",
    "NormalizedGraph",
    "RunMetadata",
    "ScenarioOutput",
    "ScenarioRunner",
    "TASK_SPEC",
    "model_input_for_case",
]
