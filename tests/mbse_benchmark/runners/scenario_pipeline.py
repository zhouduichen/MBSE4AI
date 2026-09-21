"""Single scenario, normalization, and evaluator boundary for A–E."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse, GenerativeModel

from tests.mbse_benchmark.scenarios import BenchmarkScenario, ScenarioContract
from tests.mbse_benchmark.validators.case import validate_case


TASK_SPEC: Mapping[str, object] = {
    "methodology_version": "v0.3.1",
    "input_rule": "Generate only from the supplied system brief and context; do not use reference outputs.",
    "graph_rule": "Return a typed ModelGraph with RFLP and verification/validation relations.",
}

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
    repair_enabled: bool
    cas_enabled: bool

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
            "repair_enabled": self.repair_enabled,
            "cas_enabled": self.cas_enabled,
        }


@dataclass(frozen=True, slots=True)
class ScenarioOutput:
    graph: ModelGraph
    metadata: RunMetadata
    responses: tuple[GenerationResponse, ...]


class ModelGraphNormalizer:
    """Convert every scenario output to the canonical ModelGraph shape."""

    def normalize(self, value: object, *, project_id: str = "benchmark") -> ModelGraph:
        if isinstance(value, ModelGraph):
            return value
        candidate = value.get("graph", value) if isinstance(value, Mapping) else value
        if isinstance(candidate, ModelGraph):
            return candidate
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
        return ModelGraph(project_id, tuple(entities), (), 0)

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

    def _graph_from_mapping(self, value: Mapping[str, object], project_id: str) -> ModelGraph:
        raw_entities = [item for item in value.get("entities", ()) if isinstance(item, Mapping)]
        entities = []
        id_map: dict[str, str] = {}
        for item in raw_entities:
            entity = self._entity_from_mapping(item)
            entities.append(entity)
            raw_id = str(item.get("id", "")).strip()
            if raw_id:
                id_map[raw_id] = entity.id
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
        return ModelGraph(
            str(value.get("project_id", project_id)),
            tuple(entities),
            tuple(relations),
            int(value.get("revision", 0) or 0),
        )

    @staticmethod
    def _entity_from_mapping(value: Mapping[str, object]):
        try:
            kind = EntityKind(str(value.get("kind", EntityKind.REQUIREMENT.value)))
        except ValueError:
            kind = EntityKind.REQUIREMENT
        try:
            status = EntityStatus(str(value.get("status", EntityStatus.CANDIDATE.value)))
        except ValueError:
            status = EntityStatus.CANDIDATE
        try:
            producer = Producer(str(value.get("producer", Producer.LLM.value)))
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
            from dataclasses import replace

            entity = replace(entity, meta=replace(entity.meta, id=raw_id))
        return entity


class ExternalEvaluator:
    """Evaluate only normalized graphs against the shared case contract."""

    def __init__(self, normalizer: ModelGraphNormalizer | None = None):
        self.normalizer = normalizer or ModelGraphNormalizer()

    def evaluate(
        self,
        case: Mapping[str, object],
        graph: ModelGraph,
        expectations: Mapping[str, object],
        *,
        execution: Mapping[str, object] | None = None,
        raw_result: Mapping[str, object] | None = None,
        repeats: list[Mapping[str, object]] | None = None,
    ) -> dict[str, object]:
        observed = dict(raw_result or {})
        observed.update({
            "graph": self.normalizer.payload(graph),
            "execution": dict(execution or observed.get("execution", {"status": "completed"})),
        })
        return validate_case(case, observed, expectations, repeats=repeats)


class ScenarioRunner:
    """Run bare A/B model calls with no Harness or expected-graph shortcut."""

    def __init__(self, normalizer: ModelGraphNormalizer | None = None):
        self.normalizer = normalizer or ModelGraphNormalizer()

    def run(
        self,
        case: Mapping[str, object],
        contract: ScenarioContract,
        model: GenerativeModel,
        *,
        project_id: str,
        token_budget: int = 3000,
    ) -> ScenarioOutput:
        if contract.scenario not in {
            BenchmarkScenario.A_BARE_ONE_SHOT,
            BenchmarkScenario.B_BARE_STAGED,
        }:
            raise ValueError(f"ScenarioRunner only owns bare scenarios: {contract.scenario.value}")
        model_input = model_input_for_case(case)
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
            requests.append(request)
            response = model.complete_json(request)
            responses.append(response)
            response_payload = response.payload if isinstance(response.payload, Mapping) else {}
            payload = _merge_graph_payload(payload, response_payload, project_id)
        graph = self.normalizer.normalize(payload, project_id=project_id)
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
            input_hash=canonical_hash(model_input),
            token_usage=usage,
            latency_ms=sum(int(getattr(item, "duration_ms", 0) or 0) for item in responses) or duration_ms,
            graph_hash=graph.snapshot_hash,
            verifier_enabled=contract.has_verifier,
            repair_enabled=contract.has_repair,
            cas_enabled=contract.has_cas,
        )
        return ScenarioOutput(graph, metadata, tuple(responses))


def model_input_for_case(case: Mapping[str, object]) -> dict[str, object]:
    return {
        key: case.get(key)
        for key in ("case_id", "system", "brief", "stakeholders", "lifecycle_stages", "scenarios")
        if key in case
    }


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
    "ExternalEvaluator",
    "MODEL_GRAPH_SCHEMA",
    "ModelGraphNormalizer",
    "RunMetadata",
    "ScenarioOutput",
    "ScenarioRunner",
    "TASK_SPEC",
    "model_input_for_case",
]
