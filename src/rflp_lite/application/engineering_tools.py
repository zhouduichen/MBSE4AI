"""Registered engineering-tool adapters and their V&V result boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.errors import ConflictError, ContractViolation, NotFoundError
from rflp_lite.methodology.architecture_synthesis import synthesize_architecture
from rflp_lite.application.vv_execution import VvExecutionResult, VvExecutionService


_CASE_KINDS = frozenset({EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE})


@dataclass(frozen=True, slots=True)
class ToolExecutionRequest:
    """Read-only input passed to a registered tool adapter."""

    project_id: str
    case: Entity
    graph: object
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """Explicit tool output that can be promoted to V&V evidence."""

    outcome: str
    claim: str
    excerpt: str
    locator: str = ""
    source_type: str = "engineering_tool"
    metadata: Mapping[str, object] = field(default_factory=dict)


class EngineeringTool(Protocol):
    tool_id: str

    def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult: ...


class ModelConstraintCheckTool:
    """Check propagated model constraints without inventing measurements."""

    tool_id = "model.constraint_check"
    description = "检查物理候选的已传播约束；缺少实测字段时返回 inconclusive。"
    case_kinds = (EntityKind.VERIFICATION_CASE.value,)

    def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        if request.case.kind is not EntityKind.VERIFICATION_CASE:
            raise ContractViolation("model.constraint_check only supports VerificationCase")
        requirement_ids = _case_requirement_ids(request.graph, request.case)
        synthesis = synthesize_architecture(request.graph)
        rows = tuple(
            row for row in synthesis.physical_rows
            if set(row.requirement_ids) & set(requirement_ids)
        )
        outcome = _constraint_outcome(requirement_ids, rows)
        summaries = tuple(_row_summary(row) for row in rows)
        excerpt = canonical_json({
            "tool_id": self.tool_id,
            "graph_revision": request.graph.revision,
            "requirement_ids": list(requirement_ids),
            "rows": list(summaries),
            "measurement": False,
        })
        return ToolExecutionResult(
            outcome,
            _constraint_claim(outcome),
            excerpt,
            f"modelgraph://{request.project_id}/revision/{request.graph.revision}",
            "model_constraint_analysis",
            {
                "tool_id": self.tool_id,
                "analysis_type": "propagated_constraint_check",
                "measurement": False,
                "graph_revision": request.graph.revision,
                "requirement_ids": list(requirement_ids),
                "physical_ids": [row.physical_id for row in rows],
                "rows": list(summaries),
            },
        )


class EngineeringToolRegistry:
    """Resolve only explicitly registered adapters."""

    def __init__(self, tools: Sequence[EngineeringTool] = ()) -> None:
        self._tools: dict[str, EngineeringTool] = {}
        for tool in tools:
            tool_id = str(getattr(tool, "tool_id", "")).strip()
            if not tool_id:
                raise ContractViolation("engineering tool requires tool_id")
            self._tools[tool_id] = tool

    def get(self, tool_id: str) -> EngineeringTool:
        tool = self._tools.get(str(tool_id).strip())
        if tool is None:
            raise NotFoundError(f"engineering tool not found: {tool_id}")
        return tool

    def descriptors(self) -> tuple[Mapping[str, object], ...]:
        return tuple(
            _tool_descriptor(tool)
            for tool in sorted(self._tools.values(), key=lambda item: str(item.tool_id))
        )


@dataclass(frozen=True, slots=True)
class EngineeringToolRun:
    """Combined adapter output and persisted V&V execution result."""

    tool_id: str
    case_id: str
    outcome: str
    claim: str
    excerpt: str
    evidence_id: str
    revision: int
    metadata: Mapping[str, object]
    methodology: Mapping[str, object]
    controller: Mapping[str, object]

    def as_dict(self) -> Mapping[str, object]:
        return {
            "tool_id": self.tool_id,
            "case_id": self.case_id,
            "outcome": self.outcome,
            "claim": self.claim,
            "excerpt": self.excerpt,
            "evidence_id": self.evidence_id,
            "revision": self.revision,
            "metadata": dict(self.metadata),
            "methodology": dict(self.methodology),
            "controller": dict(self.controller),
        }


class EngineeringToolService:
    """Execute a registered adapter, then persist its explicit result via V&V."""

    def __init__(
        self,
        model_service,
        vv_execution: VvExecutionService,
        *,
        tools: Sequence[EngineeringTool] = (),
    ) -> None:
        self.model_service = model_service
        self.vv_execution = vv_execution
        self.registry = EngineeringToolRegistry(
            (ModelConstraintCheckTool(), *tuple(tools))
        )

    def list_tools(self) -> tuple[Mapping[str, object], ...]:
        return self.registry.descriptors()

    def execute(
        self,
        project_id: str,
        case_id: str,
        tool_id: str,
        *,
        parameters: Mapping[str, object] | None = None,
        expected_revision: int | None = None,
    ) -> EngineeringToolRun:
        graph = self.model_service.graph(project_id)
        case = graph.entity_index.get(case_id)
        if case is None:
            raise NotFoundError(f"V&V case not found: {case_id}")
        if case.kind not in _CASE_KINDS:
            raise ContractViolation("case_id must reference a VerificationCase or ValidationCase")
        if case.meta.status is EntityStatus.LOCKED or bool(case.payload.get("user_modified")):
            raise ConflictError(f"V&V case is locked: {case_id}")
        revision = graph.revision if expected_revision is None else int(expected_revision)
        if revision != graph.revision:
            raise ConflictError(
                f"stale engineering tool request: expected {revision}, current {graph.revision}"
            )
        tool = self.registry.get(tool_id)
        output = tool.execute(ToolExecutionRequest(
            project_id, case, graph, dict(parameters or {})
        ))
        if not isinstance(output, ToolExecutionResult):
            raise ContractViolation("engineering tool must return ToolExecutionResult")
        if not isinstance(output.metadata, Mapping):
            raise ContractViolation("engineering tool metadata must be an object")
        metadata = {
            "tool_id": str(tool.tool_id),
            "tool_request_revision": graph.revision,
            **dict(output.metadata),
        }
        execution = self.vv_execution.record_result(
            project_id,
            case_id,
            outcome=output.outcome,
            claim=output.claim,
            excerpt=output.excerpt,
            locator=output.locator,
            source_type=output.source_type,
            expected_revision=graph.revision,
            metadata=metadata,
        )
        self.model_service.repository.record_audit(project_id, "engineering_tool.executed", {
            "tool_id": str(tool.tool_id),
            "case_id": case_id,
            "outcome": execution.outcome,
            "evidence_id": execution.evidence_id,
            "revision": execution.revision,
        })
        return _tool_run(tool, output, execution, metadata)


def _tool_descriptor(tool: EngineeringTool) -> Mapping[str, object]:
    raw_kinds = getattr(tool, "case_kinds", tuple(item.value for item in _CASE_KINDS))
    if isinstance(raw_kinds, str):
        raw_kinds = (raw_kinds,)
    return {
        "tool_id": str(tool.tool_id),
        "description": str(getattr(tool, "description", "")),
        "case_kinds": sorted(str(item) for item in raw_kinds),
    }


def _tool_run(tool, output, execution: VvExecutionResult, metadata):
    return EngineeringToolRun(
        str(tool.tool_id),
        execution.case_id,
        execution.outcome,
        output.claim,
        output.excerpt,
        execution.evidence_id,
        execution.revision,
        metadata,
        execution.methodology or {},
        execution.controller or {},
    )


def _case_requirement_ids(graph, case: Entity) -> tuple[str, ...]:
    raw_ids = case.payload.get("requirement_ids", ())
    if isinstance(raw_ids, str):
        raw_ids = (raw_ids,)
    ids = {
        str(item) for item in raw_ids
        if str(item) in graph.entity_index
        and graph.entity_index[str(item)].kind is EntityKind.REQUIREMENT
    }
    predicates = {"verifiedBy", "validatedBy"}
    ids.update(
        relation.source_id
        for relation in graph.relations
        if relation.target_id == case.id
        and relation.predicate.value in predicates
        and relation.source_id in graph.entity_index
        and graph.entity_index[relation.source_id].kind is EntityKind.REQUIREMENT
    )
    return tuple(sorted(ids))


def _constraint_outcome(requirement_ids, rows) -> str:
    if not requirement_ids or not rows:
        return "inconclusive"
    if any(row.conflicts for row in rows):
        return "failed"
    if any(row.missing_fields for row in rows):
        return "inconclusive"
    return "passed"


def _constraint_claim(outcome: str) -> str:
    return {
        "passed": "模型约束分析表明物理候选满足已传播约束。",
        "failed": "模型约束分析发现物理候选违反已传播约束。",
        "inconclusive": "模型约束分析无法判定，仍缺少可用的追溯或测量字段。",
    }[outcome]


def _row_summary(row) -> Mapping[str, object]:
    return {
        "physical_id": row.physical_id,
        "requirement_ids": list(row.requirement_ids),
        "status": row.status,
        "propagated_constraints": dict(row.propagated_constraints),
        "missing_fields": list(row.missing_fields),
        "conflicts": [dict(item) for item in row.conflicts],
    }
