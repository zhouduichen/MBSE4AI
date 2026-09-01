"""Static dispatch for persistence-free intelligence block mergers."""

from __future__ import annotations

from collections.abc import Callable

from rflp_lite.application.intelligence.merge.architecture import merge_architecture
from rflp_lite.application.intelligence.merge.common import State
from rflp_lite.application.intelligence.merge.concerns_needs import merge_concerns_needs
from rflp_lite.application.intelligence.merge.requirements import merge_requirements
from rflp_lite.application.intelligence.merge.requirement_details import merge_requirement_details
from rflp_lite.application.intelligence.merge.implicit_constraints import merge_implicit_constraints
from rflp_lite.application.intelligence.merge.scenarios import merge_scenarios
from rflp_lite.application.intelligence.merge.stakeholders import merge_stakeholders
from rflp_lite.application.intelligence.merge.system_scope import merge_system_scope
from rflp_lite.application.intelligence.validated_result import ValidatedBlockResult
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


MergeFunction = Callable[
    [State, ValidatedBlockResult | str, GenerationResponse | None],
    State,
]


# The original six entries remain the public iterable catalog for older
# integrations.  Enhanced blocks are available through ``ALL_MERGERS`` and
# the dispatcher, so callers can adopt them without breaking exact catalog
# checks in legacy clients.
MERGERS: dict[str, MergeFunction] = {
    "system_scope": merge_system_scope,
    "stakeholders": merge_stakeholders,
    "concerns_needs": merge_concerns_needs,
    "requirements": merge_requirements,
    "scenarios": merge_scenarios,
    "architecture": merge_architecture,
}

ALL_MERGERS: dict[str, MergeFunction] = {
    **MERGERS,
    "requirement_details": merge_requirement_details,
    "implicit_constraints": merge_implicit_constraints,
}


def dispatch_merge(
    state: State,
    result: ValidatedBlockResult | str,
    response: GenerationResponse | None = None,
) -> State:
    block_id = result.block_id if isinstance(result, ValidatedBlockResult) else str(result)
    merger = ALL_MERGERS.get(block_id)
    if merger is None:
        raise ContractViolation(f"未知分析块: {block_id}")
    return merger(state, result, response)
