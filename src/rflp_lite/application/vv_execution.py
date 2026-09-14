"""Record real Verification/Validation execution results.

The service accepts evidence supplied by a user or an external engineering
tool.  It never invents a pass result: a case is only considered executed
when a caller provides an explicit outcome and an evidence excerpt.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer, make_evidence_entity
from rflp_lite.domain.errors import ConflictError, ContractViolation, NotFoundError
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.controller import SystemsEngineeringController
from rflp_lite.methodology.engine import MethodologyEngine


_OUTCOMES = {
    "pass": "passed",
    "passed": "passed",
    "通过": "passed",
    "fail": "failed",
    "failed": "failed",
    "失败": "failed",
    "blocked": "blocked",
    "阻塞": "blocked",
    "inconclusive": "inconclusive",
    "不确定": "inconclusive",
}
_CASE_KINDS = frozenset({EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE})
_FAILURE_OUTCOMES = frozenset({"failed", "blocked", "inconclusive"})


@dataclass(frozen=True, slots=True)
class VvExecutionResult:
    project_id: str
    case_id: str
    case_type: str
    outcome: str
    evidence_id: str
    revision: int
    issue_id: str = ""
    methodology: Mapping[str, object] = None
    controller: Mapping[str, object] = None

    def as_dict(self) -> Mapping[str, object]:
        return {
            "project_id": self.project_id,
            "case_id": self.case_id,
            "case_type": self.case_type,
            "outcome": self.outcome,
            "evidence_id": self.evidence_id,
            "revision": self.revision,
            "issue_id": self.issue_id,
            "methodology": dict(self.methodology or {}),
            "controller": dict(self.controller or {}),
        }


class VvExecutionService:
    """Persist externally supplied V&V results through the ModelGraph CAS path."""

    def __init__(
        self,
        model_service,
        *,
        methodology_engine: MethodologyEngine | None = None,
        controller: SystemsEngineeringController | None = None,
    ) -> None:
        self.model_service = model_service
        self.repository = model_service.repository
        self.methodology_engine = methodology_engine or MethodologyEngine()
        self.controller = controller or SystemsEngineeringController(self.methodology_engine)

    def record_result(
        self,
        project_id: str,
        case_id: str,
        *,
        outcome: str,
        claim: str,
        excerpt: str,
        locator: str = "",
        source_type: str = "vv_execution",
        expected_revision: int | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> VvExecutionResult:
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
                f"stale V&V execution result: expected {revision}, current {graph.revision}"
            )
        normalized = _normalize_outcome(outcome)
        clean_claim = str(claim).strip()
        clean_excerpt = str(excerpt).strip()
        if not clean_claim or not clean_excerpt:
            raise ContractViolation("V&V execution requires claim and excerpt")
        clean_locator = str(locator).strip()
        clean_source_type = str(source_type).strip() or "vv_execution"
        evidence_id = f"evidence-vv-{canonical_hash((project_id, case_id, normalized, clean_claim, clean_excerpt, clean_locator))[:16]}"
        existing_ids = tuple(dict.fromkeys(
            [*case.meta.evidence_ids, *list(_evidence_ids(case.payload))]
        ))
        if evidence_id in existing_ids:
            return self._result(project_id, case, normalized, evidence_id, graph.revision, "")

        evidence = {
            "id": evidence_id,
            "source_type": clean_source_type,
            "source_id": case_id,
            "locator": clean_locator,
            "claim": clean_claim,
            "excerpt": clean_excerpt,
        }
        self.repository.save_evidence(project_id, evidence)
        record = {
            "evidence_id": evidence_id,
            "outcome": normalized,
            "claim": clean_claim,
            "locator": clean_locator,
            "source_type": clean_source_type,
            "metadata": dict(metadata or {}),
            "recorded_revision": graph.revision + 1,
        }
        records = case.payload.get("execution_records", ())
        previous_records = list(records) if isinstance(records, (list, tuple)) else []
        next_evidence_ids = list(dict.fromkeys([*existing_ids, evidence_id]))
        patch = Patch.create(
            project_id,
            "vv.execute",
            (
                *(
                    (
                        AddEntity(
                            make_evidence_entity(
                                evidence,
                                status=EntityStatus.ACCEPTED,
                                producer=Producer.USER,
                                revision=graph.revision,
                            )
                        ),
                    )
                    if evidence_id not in graph.entity_index
                    else ()
                ),
                UpdateEntity(case_id, {
                    "evidence_ids": next_evidence_ids,
                    "payload": {
                        "evidence_ids": next_evidence_ids,
                        "execution_status": normalized,
                        "last_execution": record,
                        "execution_records": [*previous_records, record],
                    },
                }),
                *(
                    (Relate(case_id, RelationPredicate.DESCRIBED_BY, evidence_id),)
                    if evidence_id not in {
                        relation.target_id
                        for relation in graph.relations
                        if relation.source_id == case_id
                        and relation.predicate is RelationPredicate.DESCRIBED_BY
                    }
                    else ()
                ),
            ),
            f"记录 {case.kind.value} 执行结果：{normalized}",
            graph.revision,
        )
        next_revision = self.model_service.apply_patch(
            project_id, patch, graph.revision
        ).sequence
        issue_id = self._record_execution_issue(
            project_id, case, normalized, evidence_id, clean_excerpt
        )
        self.repository.record_audit(project_id, "vv.execution.recorded", {
            "case_id": case_id,
            "case_type": case.kind.value,
            "outcome": normalized,
            "evidence_id": evidence_id,
            "revision": next_revision,
            "issue_id": issue_id,
        })
        updated = self.model_service.graph(project_id)
        return self._result(project_id, updated.entity_index[case_id], normalized, evidence_id, next_revision, issue_id)

    def _result(self, project_id, case, outcome, evidence_id, revision, issue_id):
        report = self.methodology_engine.analyze(self.model_service.graph(project_id))
        return VvExecutionResult(
            project_id,
            case.id,
            case.kind.value,
            outcome,
            evidence_id,
            revision,
            issue_id,
            report.as_dict(),
            self.controller.plan(self.model_service.graph(project_id), report).as_dict(),
        )

    def _record_execution_issue(self, project_id, case, outcome, evidence_id, excerpt):
        requirement_ids = _requirement_ids(self.model_service.graph(project_id), case)
        issue_id = f"issue-vv-{canonical_hash((project_id, case.id))[:16]}"
        existing = next(
            (item for item in self.repository.list_issues(project_id) if item.get("id") == issue_id),
            None,
        )
        impact_ids = _execution_impact(
            self.methodology_engine.analyze(self.model_service.graph(project_id)),
            case.id,
        )
        entity_ids = tuple(
            str(item) for item in (existing or {}).get("entity_ids", ()) if str(item)
        ) or impact_ids or (case.id, *requirement_ids)
        case_label = (
            "verification"
            if case.kind is EntityKind.VERIFICATION_CASE
            else "validation"
        )
        code = f"{case_label}_execution_failed"
        issue = {
            "id": issue_id,
            "code": code,
            "severity": "error" if outcome == "failed" else "warning",
            "entity_ids": list(entity_ids),
            "evidence_ids": [evidence_id],
            "status": "open" if outcome in _FAILURE_OUTCOMES else "resolved",
            "outcome": outcome,
            "message": f"{case.meta.name} 执行结果为 {outcome}：{excerpt}",
            "suggested_rollback": "verification_validation",
        }
        if outcome in _FAILURE_OUTCOMES or any(
            item.get("id") == issue_id
            for item in self.repository.list_issues(project_id)
        ):
            self.repository.save_issue(project_id, issue)
            return issue_id
        return ""


def _execution_impact(report, case_id: str):
    finding = next(
        (
            item for item in report.findings
            if item.code in {"verification_execution_failed", "validation_execution_failed"}
            and case_id in item.entity_ids
        ),
        None,
    )
    if finding is None:
        return ()
    return tuple(finding.entity_ids)


def _normalize_outcome(value: str) -> str:
    normalized = _OUTCOMES.get(str(value).strip().casefold())
    if normalized is None:
        raise ContractViolation(
            "outcome must be one of passed, failed, blocked, inconclusive"
        )
    return normalized


def _evidence_ids(payload: Mapping[str, object]):
    values = payload.get("evidence_ids", ())
    if isinstance(values, (list, tuple)):
        return tuple(str(item) for item in values if str(item).strip())
    return ()


def _requirement_ids(graph, case):
    ids = {
        str(item) for item in case.payload.get("requirement_ids", ())
        if str(item) in graph.entity_index
    }
    predicates = {
        RelationPredicate.VERIFIED_BY,
        RelationPredicate.VALIDATED_BY,
    }
    ids.update(
        relation.source_id
        for relation in graph.relations
        if relation.target_id == case.id
        and relation.predicate in predicates
        and relation.source_id in graph.entity_index
    )
    return tuple(sorted(ids))
