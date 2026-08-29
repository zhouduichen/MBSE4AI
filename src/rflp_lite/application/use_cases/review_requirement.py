"""Explicit requirement-review use case.

The compatibility facade still owns workspace lookup and persistence.  This
module owns the decision boundary and makes the required collaborators
visible to callers, so review behavior can be tested without constructing a
global application dependency bundle.
"""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.application.traceability import refresh_traceability
from rflp_lite.application.use_cases.dependencies import ReviewRequirementDeps
from rflp_lite.application.workbench import MutationKind, MutationResult, WorkbenchCommitCoordinator
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class ReviewRequirementCommand:
    group: str
    item_id: str
    decision: str
    value: str = ""
    category: str = ""
    expected_revision: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewRequirementResult:
    state: dict[str, object]
    changed_ids: tuple[str, ...]
    stale_groups: tuple[str, ...]


class ReviewRequirementUseCase:
    def __init__(self, dependencies: ReviewRequirementDeps):
        self.dependencies = dependencies

    def execute(
        self, state: dict[str, object], command: ReviewRequirementCommand
    ) -> ReviewRequirementResult:
        if command.expected_revision is not None:
            revision = int(state.get("revision", 0) or 0)
            if revision != command.expected_revision:
                raise ContractViolation("需求版本已变化，请刷新后再审查")
        if not command.group.strip() or not command.item_id.strip():
            raise ContractViolation("需求审查缺少 group 或 item_id")
        stale_groups = self.dependencies.staleness_policy(
            state, (command.item_id,)
        )
        changed = self.dependencies.review_policy(
            state,
            command.group,
            command.item_id,
            command.decision,
            command.value,
            command.category,
        )
        return ReviewRequirementResult(
            state=changed,
            changed_ids=(command.item_id,),
            stale_groups=tuple(stale_groups),
        )

    def commit(
        self, workspace: str, command: ReviewRequirementCommand
    ) -> ReviewRequirementResult:
        """Apply the existing review policy through the Workbench kernel."""
        coordinator = WorkbenchCommitCoordinator(self.dependencies.repository, workspace)
        snapshot = coordinator.snapshot()
        if snapshot is None:
            raise ContractViolation("requirements workbench is empty")
        expected_revision = (
            snapshot.revision
            if command.expected_revision is None
            else command.expected_revision
        )
        stale_groups: tuple[str, ...] = ()

        def mutation(state: dict[str, object]) -> MutationResult:
            nonlocal stale_groups
            result = self.execute(
                state,
                ReviewRequirementCommand(
                    group=command.group,
                    item_id=command.item_id,
                    decision=command.decision,
                    value=command.value,
                    category=command.category,
                    expected_revision=expected_revision,
                ),
            )
            stale_groups = result.stale_groups
            result.state.setdefault("review_diagnostics", []).append(
                {
                    "code": "requirement_reviewed",
                    "item_id": command.item_id,
                    "stale_groups": list(result.stale_groups),
                }
            )
            return MutationResult(
                state=refresh_traceability(result.state),
                changed_ids=result.changed_ids,
                invalidated_sections=result.stale_groups,
                mutation_kind=MutationKind.HUMAN_CONTENT,
            )

        committed = coordinator.commit(
            mutation,
            expected_revision=expected_revision,
            expected_content_revision=snapshot.content_revision,
            event="requirements.reviewed",
        )
        return ReviewRequirementResult(
            state=committed.state,
            changed_ids=committed.changed_ids,
            stale_groups=stale_groups,
        )


__all__ = [
    "ReviewRequirementCommand",
    "ReviewRequirementResult",
    "ReviewRequirementUseCase",
]
