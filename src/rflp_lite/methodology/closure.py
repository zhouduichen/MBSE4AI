"""Strict, non-vacuous Closure semantics for a ModelGraph."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

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
_READY_STATUSES = frozenset({
    EntityStatus.VALIDATED,
    EntityStatus.ACCEPTED,
    EntityStatus.LOCKED,
})
_RESOLVED_ISSUE_STATUSES = frozenset({"resolved", "closed", "fixed", "waived"})


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

    @property
    def metrics(self) -> Mapping[str, object]:
        return {
            "requirement_count": len(self.requirement_ids),
            "accepted_requirement_count": self.accepted_requirement_count,
            "closure_passed": self.passed,
            "issue_count": len(self.issues),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "requirement_ids": list(self.requirement_ids),
            "accepted_requirement_count": self.accepted_requirement_count,
            "issues": [issue.as_dict() for issue in self.issues],
            "metrics": dict(self.metrics),
        }


def evaluate_strict_closure(
    graph: ModelGraph,
    *,
    issue_records: Iterable[Mapping[str, object]] = (),
    requirement_ids: Iterable[str] | None = None,
) -> ClosureAssessment:
    """Evaluate the final engineering fact scope without vacuous truth.

    By default every active Requirement is in scope. Callers may provide an
    explicit scope, but an explicit scope still has to contain only existing
    Requirement entities and at least one Accepted/Locked Requirement.
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
        entity.meta.status in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}
        for entity in scope
    )
    if scope and accepted_count == 0:
        issues.append(ClosureIssue(
            "no_accepted_requirements",
            "Closure requires at least one Accepted or Locked Requirement",
            tuple(entity.id for entity in scope),
        ))

    if requirement_ids is not None:
        requested = tuple(dict.fromkeys(str(item).strip() for item in requirement_ids if str(item).strip()))
        for entity_id in requested:
            entity = index.get(entity_id)
            if entity is None or entity.kind is not EntityKind.REQUIREMENT:
                issues.append(ClosureIssue(
                    "unknown_requirement",
                    f"Closure scope references a non-Requirement entity: {entity_id}",
                    (entity_id,),
                ))

    for requirement in scope:
        if requirement.meta.status not in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}:
            issues.append(ClosureIssue(
                "requirement_not_accepted",
                f"Requirement is not Accepted or Locked: {requirement.id}",
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
            if entity is None:
                continue
            _append_entity_quality_issues(issues, entity)

        for entity_id in trace.verification_case_ids:
            case = index.get(entity_id)
            if case is not None and not case.payload.get("fallback_placeholder"):
                missing = missing_vv_plan_fields(case.payload)
                if missing:
                    issues.append(ClosureIssue(
                        "verification_plan_incomplete",
                        f"Verification case has no executable plan: {case.id}",
                        (requirement.id, case.id),
                        {"missing_fields": list(missing)},
                    ))
        for entity_id in trace.validation_case_ids:
            case = index.get(entity_id)
            if case is not None and not case.payload.get("fallback_placeholder"):
                missing = missing_vv_plan_fields(case.payload)
                if missing:
                    issues.append(ClosureIssue(
                        "validation_plan_incomplete",
                        f"Validation case has no executable plan: {case.id}",
                        (requirement.id, case.id),
                        {"missing_fields": list(missing)},
                    ))

    for record in issue_records:
        status = str(record.get("status", "open")).strip().casefold()
        if status not in _RESOLVED_ISSUE_STATUSES:
            issue_id = str(record.get("id", "")).strip()
            issues.append(ClosureIssue(
                "open_issue",
                f"Unresolved issue blocks Closure: {issue_id or 'anonymous'}",
                tuple(str(item) for item in record.get("entity_ids", ()) if str(item)),
                {"issue_id": issue_id, "status": status},
            ))

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
    )


def _append_entity_quality_issues(issues: list[ClosureIssue], entity: Entity) -> None:
    if entity.meta.status is EntityStatus.CANDIDATE:
        issues.append(ClosureIssue(
            "unresolved_candidate",
            f"Candidate entity is present in Closure trace: {entity.id}",
            (entity.id,),
        ))
    elif entity.meta.status not in _READY_STATUSES:
        issues.append(ClosureIssue(
            "inactive_trace_entity",
            f"Inactive entity is present in Closure trace: {entity.id}",
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


__all__ = ["ClosureAssessment", "ClosureIssue", "evaluate_strict_closure"]
