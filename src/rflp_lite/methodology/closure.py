"""Strict, non-vacuous Closure semantics for a ModelGraph."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from rflp_lite.domain.entities import Entity, EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.vertical_coverage import resolve_requirement_trace
from rflp_lite.methodology.vv_contract import missing_vv_plan_fields


_ACTIVE_STATUSES = frozenset({
    EntityStatus.CANDIDATE,
    EntityStatus.VALIDATED,
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})
_TECHNICAL_READY_STATUSES = frozenset({
    EntityStatus.VALIDATED,
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})
_RELEASE_READY_STATUSES = frozenset({
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})
_RESOLVED_ISSUE_STATUSES = frozenset({"resolved", "closed", "fixed", "waived"})


class ClosureGate(StrEnum):
    TECHNICAL = "technical"
    RELEASE = "release"


@dataclass(frozen=True, slots=True)
class ClosureIssue:
    code: str
    message: str
    entity_ids: tuple[str, ...] = ()
    details: Mapping[str, object] = None

    def __post_init__(self) -> None:
        if self.details is None:
            object.__setattr__(self, "details", {})

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "entity_ids": list(self.entity_ids),
            "details": dict(self.details or {}),
        }


@dataclass(frozen=True, slots=True)
class ClosureAssessment:
    passed: bool
    requirement_ids: tuple[str, ...]
    accepted_requirement_count: int
    issues: tuple[ClosureIssue, ...] = ()
    gate: ClosureGate = ClosureGate.RELEASE
    ready_statuses: frozenset[EntityStatus] = _RELEASE_READY_STATUSES
    ready_requirement_count: int = 0

    @property
    def metrics(self) -> Mapping[str, object]:
        return {
            "requirement_count": len(self.requirement_ids),
            "accepted_requirement_count": self.accepted_requirement_count,
            "ready_requirement_count": self.ready_requirement_count,
            "ready_statuses": sorted(status.value for status in self.ready_statuses),
            "closure_gate": self.gate.value,
            "closure_passed": self.passed,
            "issue_count": len(self.issues),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "requirement_ids": list(self.requirement_ids),
            "accepted_requirement_count": self.accepted_requirement_count,
            "ready_requirement_count": self.ready_requirement_count,
            "gate": self.gate.value,
            "ready_statuses": sorted(status.value for status in self.ready_statuses),
            "issues": [issue.as_dict() for issue in self.issues],
            "metrics": dict(self.metrics),
        }


def evaluate_strict_closure(
    graph: ModelGraph,
    *,
    issue_records: Iterable[Mapping[str, object]] = (),
    requirement_ids: Iterable[str] | None = None,
) -> ClosureAssessment:
    """Compatibility alias for the strict ReleaseClosure gate.

    New callers should select ``evaluate_technical_closure`` or
    ``evaluate_release_closure`` explicitly.
    """

    return evaluate_release_closure(
        graph,
        issue_records=issue_records,
        requirement_ids=requirement_ids,
    )


def evaluate_technical_closure(
    graph: ModelGraph,
    *,
    issue_records: Iterable[Mapping[str, object]] = (),
    requirement_ids: Iterable[str] | None = None,
) -> ClosureAssessment:
    """Evaluate a technically complete, automation-ready fact scope."""

    return _evaluate_closure(
        graph,
        gate=ClosureGate.TECHNICAL,
        ready_statuses=_TECHNICAL_READY_STATUSES,
        issue_records=issue_records,
        requirement_ids=requirement_ids,
    )


def evaluate_release_closure(
    graph: ModelGraph,
    *,
    issue_records: Iterable[Mapping[str, object]] = (),
    requirement_ids: Iterable[str] | None = None,
) -> ClosureAssessment:
    """Evaluate the final releasable engineering fact scope."""

    return _evaluate_closure(
        graph,
        gate=ClosureGate.RELEASE,
        ready_statuses=_RELEASE_READY_STATUSES,
        issue_records=issue_records,
        requirement_ids=requirement_ids,
    )


def _evaluate_closure(
    graph: ModelGraph,
    *,
    gate: ClosureGate,
    ready_statuses: frozenset[EntityStatus],
    issue_records: Iterable[Mapping[str, object]],
    requirement_ids: Iterable[str] | None,
) -> ClosureAssessment:
    """Evaluate one explicit closure policy without vacuous truth.

    By default every active Requirement is in scope. Callers may provide an
    explicit scope, but an explicit scope still has to contain only existing
    Requirement entities and at least one requirement ready for this gate.
    """

    index = graph.entity_index
    all_requirements = tuple(sorted(
        (
            entity
            for entity in graph.entities
            if entity.kind is EntityKind.REQUIREMENT
            and entity.meta.status in _ACTIVE_STATUSES
        ),
        key=lambda entity: entity.id,
    ))
    if requirement_ids is None:
        scope = all_requirements
    else:
        requested = tuple(dict.fromkeys(str(item).strip() for item in requirement_ids if str(item).strip()))
        scope = tuple(index[item] for item in requested if item in index and index[item].kind is EntityKind.REQUIREMENT)

    issues: list[ClosureIssue] = []
    if not scope:
        issues.append(ClosureIssue(
            "empty_requirement_scope",
            "Closure requires at least one active Requirement in scope",
        ))
    accepted_count = sum(
        entity.meta.status in _RELEASE_READY_STATUSES
        for entity in scope
    )
    ready_count = sum(entity.meta.status in ready_statuses for entity in scope)
    if scope and ready_count == 0:
        issues.append(ClosureIssue(
            "no_accepted_requirements"
            if gate is ClosureGate.RELEASE
            else "no_technical_ready_requirements",
            (
                "Closure requires at least one Accepted or Locked Requirement"
                if gate is ClosureGate.RELEASE
                else "Technical Closure requires at least one Validated, Accepted, or Locked Requirement"
            ),
            tuple(entity.id for entity in scope),
        ))

    if requirement_ids is not None:
        issues.extend(_unknown_scope_issues(index, requirement_ids))
    issues.extend(_requirement_issues(graph, scope, index, ready_statuses, gate))
    issues.extend(_open_issue_issues(issue_records))

    deduped: list[ClosureIssue] = []
    seen: set[tuple[object, ...]] = set()
    for issue in issues:
        identity = (issue.code, issue.entity_ids, repr(sorted((issue.details or {}).items())))
        if identity not in seen:
            seen.add(identity)
            deduped.append(issue)
    return ClosureAssessment(
        not deduped,
        tuple(entity.id for entity in scope),
        accepted_count,
        tuple(deduped),
        gate,
        ready_statuses,
        ready_count,
    )


def _unknown_scope_issues(
    index: Mapping[str, Entity],
    requirement_ids: Iterable[str],
) -> list[ClosureIssue]:
    requested = tuple(dict.fromkeys(str(item).strip() for item in requirement_ids if str(item).strip()))
    return [
        ClosureIssue(
            "unknown_requirement",
            f"Closure scope references a non-Requirement entity: {entity_id}",
            (entity_id,),
        )
        for entity_id in requested
        if (entity := index.get(entity_id)) is None
        or entity.kind is not EntityKind.REQUIREMENT
    ]


def _requirement_issues(
    graph: ModelGraph,
    scope: tuple[Entity, ...],
    index: Mapping[str, Entity],
    ready_statuses: frozenset[EntityStatus],
    gate: ClosureGate,
) -> list[ClosureIssue]:
    issues: list[ClosureIssue] = []
    for requirement in scope:
        if requirement.meta.status not in ready_statuses:
            issues.append(ClosureIssue(
                "requirement_not_accepted"
                if gate is ClosureGate.RELEASE
                else "requirement_not_validated",
                (
                    f"Requirement is not Accepted or Locked: {requirement.id}"
                    if gate is ClosureGate.RELEASE
                    else f"Requirement is not Validated, Accepted, or Locked: {requirement.id}"
                ),
                (requirement.id,),
                {"status": requirement.meta.status.value},
            ))
        trace = resolve_requirement_trace(graph, requirement.id)
        for stage, code in (
            ("functional", "missing_function"),
            ("logical", "missing_logical"),
            ("physical", "missing_physical"),
            ("verification", "missing_verification"),
            ("validation", "missing_validation"),
        ):
            if not trace.stage_coverage.get(stage, False):
                issues.append(ClosureIssue(
                    code,
                    f"Requirement lacks a complete {stage} trace: {requirement.id}",
                    (requirement.id,),
                    {"stage": stage, "gaps": list(trace.gaps)},
                ))
        trace_ids = (
            requirement.id,
            *trace.function_ids,
            *trace.logical_component_ids,
            *trace.physical_ids,
            *trace.verification_case_ids,
            *trace.validation_case_ids,
        )
        for entity_id in dict.fromkeys(trace_ids):
            entity = index.get(entity_id)
            if entity is not None:
                _append_entity_quality_issues(issues, entity, ready_statuses, gate)
        issues.extend(_vv_plan_issues(requirement.id, trace.verification_case_ids, index, "verification"))
        issues.extend(_vv_plan_issues(requirement.id, trace.validation_case_ids, index, "validation"))
    return issues


def _vv_plan_issues(
    requirement_id: str,
    case_ids: tuple[str, ...],
    index: Mapping[str, Entity],
    kind: str,
) -> list[ClosureIssue]:
    issues = []
    for entity_id in case_ids:
        case = index.get(entity_id)
        if case is None or case.payload.get("fallback_placeholder"):
            continue
        missing = missing_vv_plan_fields(case.payload)
        if missing:
            issues.append(ClosureIssue(
                f"{kind}_plan_incomplete",
                f"{kind.title()} case has no executable plan: {case.id}",
                (requirement_id, case.id),
                {"missing_fields": list(missing)},
            ))
    return issues


def _open_issue_issues(
    issue_records: Iterable[Mapping[str, object]],
) -> list[ClosureIssue]:
    issues = []
    for record in issue_records:
        status = str(record.get("status", "open")).strip().casefold()
        if status in _RESOLVED_ISSUE_STATUSES:
            continue
        issue_id = str(record.get("id", "")).strip()
        issues.append(ClosureIssue(
            "open_issue",
            f"Unresolved issue blocks Closure: {issue_id or 'anonymous'}",
            tuple(str(item) for item in record.get("entity_ids", ()) if str(item)),
            {"issue_id": issue_id, "status": status},
        ))
    return issues


def _append_entity_quality_issues(
    issues: list[ClosureIssue],
    entity: Entity,
    ready_statuses: frozenset[EntityStatus],
    gate: ClosureGate,
) -> None:
    if entity.meta.status is EntityStatus.CANDIDATE:
        issues.append(ClosureIssue(
            "unresolved_candidate",
            f"Candidate entity is present in Closure trace: {entity.id}",
            (entity.id,),
        ))
    elif entity.meta.status not in ready_statuses:
        issues.append(ClosureIssue(
            "fact_not_accepted"
            if gate is ClosureGate.RELEASE and entity.meta.status is EntityStatus.VALIDATED
            else "inactive_trace_entity",
            (
                f"Validated fact is not Accepted or Locked for Release Closure: {entity.id}"
                if gate is ClosureGate.RELEASE and entity.meta.status is EntityStatus.VALIDATED
                else f"Inactive entity is present in Closure trace: {entity.id}"
            ),
            (entity.id,),
            {"status": entity.meta.status.value},
        ))
    if bool(entity.payload.get("fallback_placeholder")):
        issues.append(ClosureIssue(
            "fallback_placeholder",
            f"Fallback placeholder is not a Closure fact: {entity.id}",
            (entity.id,),
        ))
    if bool(entity.payload.get("requires_human_review")):
        issues.append(ClosureIssue(
            "requires_human_review",
            f"Entity still requires human review: {entity.id}",
            (entity.id,),
        ))


__all__ = [
    "ClosureAssessment",
    "ClosureGate",
    "ClosureIssue",
    "evaluate_release_closure",
    "evaluate_strict_closure",
    "evaluate_technical_closure",
]
