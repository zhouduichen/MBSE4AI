from __future__ import annotations

from dataclasses import dataclass, field


KeyValue = tuple[str, object]


@dataclass(frozen=True, slots=True)
class Artifact:
    id: str
    kind: str
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class TextSpan:
    id: str
    artifact_id: str
    locator: str
    text: str


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    span_id: str
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    status: str = "candidate"


@dataclass(frozen=True, slots=True)
class ModelElement:
    id: str
    layer: str
    name: str
    status: str = "approved"
    kind: str = "element"
    attributes: tuple[KeyValue, ...] = ()


@dataclass(frozen=True, slots=True)
class Relation:
    id: str
    source_id: str
    predicate: str
    target_id: str


@dataclass(frozen=True, slots=True)
class Candidate:
    id: str
    pattern: str
    components: tuple[str, ...]
    score: int
    rationale: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    id: str
    candidate_id: str
    score: int
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    time: int
    priority: int
    sequence: int
    kind: str
    target: str
    payload: tuple[KeyValue, ...] = ()


@dataclass(frozen=True, slots=True)
class SimulationRun:
    id: str
    candidate_id: str
    events: tuple[SimulationEvent, ...]
    metrics: tuple[KeyValue, ...]
    passed: bool
    trace_hash: str


@dataclass(frozen=True, slots=True)
class Baseline:
    id: str
    status: str
    elements: tuple[ModelElement, ...]
    relations: tuple[Relation, ...]
    payload: tuple[KeyValue, ...]
    hash: str


@dataclass(frozen=True, slots=True)
class DeltaItem:
    id: str
    kind: str
    target_id: str
    description: str


@dataclass(frozen=True, slots=True)
class Delta:
    id: str
    baseline_hash: str
    items: tuple[DeltaItem, ...]


@dataclass(frozen=True, slots=True)
class TaskContract:
    id: str
    target_ids: tuple[str, ...]
    read_set: tuple[str, ...]
    write_set: tuple[str, ...]
    invariants: tuple[str, ...]
    acceptance: tuple[str, ...]
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    kind: str
    source: str
    target_id: str
    status: str
    artifact_hash: str
    details: tuple[KeyValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ActualElement:
    id: str
    kind: str
    name: str
    source: str
    artifact_hash: str
    status: str = "observed"
    details: tuple[KeyValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ActualModel:
    id: str
    source_root: str
    elements: tuple[ActualElement, ...]
    hash: str


@dataclass(frozen=True, slots=True)
class DemoResult:
    artifacts: tuple[Artifact, ...]
    spans: tuple[TextSpan, ...]
    claims: tuple[Claim, ...]
    elements: tuple[ModelElement, ...]
    relations: tuple[Relation, ...]
    candidates: tuple[Candidate, ...]
    decision: Decision
    simulation: SimulationRun
    baseline: Baseline
    delta: Delta
    task_contracts: tuple[TaskContract, ...]
    evidence: tuple[Evidence, ...]
    manifest_path: str
    result_hash: str

