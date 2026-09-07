"""Typed contracts shared by TaskSpecs, ContextBuilder and WorkflowRunner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Protocol

from rflp_lite.domain.entities import Entity, EntityKind
from rflp_lite.domain.model import Patch


class Phase(StrEnum):
    OPERATIONAL = "operational"
    FUNCTIONAL = "functional"
    LOGICAL_PHYSICAL = "logical_physical"
    ASSURANCE = "assurance"
    CLOSURE = "closure"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    COMPLETED = "completed"
    REPAIRING = "repairing"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DEGRADED = "degraded"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ContextQuery:
    entity_kinds: frozenset[EntityKind] = frozenset()
    neighborhood_hops: int = 1
    include_evidence: bool = True


@dataclass(frozen=True, slots=True)
class FailureRoute:
    issue_code: str
    rollback_phase: Phase


@dataclass(frozen=True, slots=True)
class CompletionCondition:
    required_output_kinds: frozenset[EntityKind] = frozenset()
    minimum_entities: int = 0


@dataclass(frozen=True, slots=True)
class TaskSpec:
    id: str
    phase: Phase
    input_kinds: frozenset[EntityKind]
    output_kinds: frozenset[EntityKind]
    context_query: ContextQuery
    prompt_template_id: str
    output_schema_id: str
    tools: tuple[str, ...] = ()
    validators: tuple[str, ...] = ()
    max_attempts: int = 2
    failure_routes: tuple[FailureRoute, ...] = ()
    completion_condition: CompletionCondition = field(default_factory=CompletionCondition)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("task id is required")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not self.context_query.entity_kinds <= self.input_kinds:
            raise ValueError("context query requests kinds outside task input kinds")


@dataclass(frozen=True, slots=True)
class ContextBundle:
    project_id: str
    task_id: str
    revision: int
    entities: tuple[Entity, ...]
    relations: tuple[object, ...] = ()
    evidence: tuple[Mapping[str, object], ...] = ()
    token_estimate: int = 0


@dataclass(frozen=True, slots=True)
class TaskExecutionRequest:
    task_id: str
    methodology_version: str
    context_bundle: ContextBundle
    evidence_bundle: tuple[Mapping[str, object], ...]
    output_contract: Mapping[str, object]
    token_budget: int
    tool_policy: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskExecutionResponse:
    status: StepStatus
    patch: Patch | None = None
    diagnostics: tuple[str, ...] = ()
    repaired: bool = False
    input_hash: str = ""
    output_hash: str = ""
    provider_id: str = ""
    model_id: str = ""


class TaskRuntime(Protocol):
    def execute(self, request: TaskExecutionRequest) -> TaskExecutionResponse: ...
