"""Block merge registry.

The registry is deliberately pure: it returns a new Workbench state and never
opens a repository or performs a save.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module

from rflp_lite.application.intelligence.validated_result import ValidatedBlockResult
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


MergeFunction = Callable[
    [dict[str, object], ValidatedBlockResult | str, GenerationResponse | None],
    dict[str, object],
]


def _legacy_merge(
    state: dict[str, object],
    result: ValidatedBlockResult | str,
    response: GenerationResponse | None,
) -> dict[str, object]:
    module = import_module("rflp_lite.application.intelligence.analysis_blocks")
    return module._legacy_merge_block_result(state, result, response)


MERGERS: dict[str, MergeFunction] = {
    block_id: _legacy_merge
    for block_id in (
        "system_scope",
        "stakeholders",
        "concerns_needs",
        "requirements",
        "scenarios",
        "architecture",
    )
}


def dispatch_merge(
    state: dict[str, object],
    result: ValidatedBlockResult | str,
    response: GenerationResponse | None = None,
) -> dict[str, object]:
    block_id = result.block_id if isinstance(result, ValidatedBlockResult) else str(result)
    merger = MERGERS.get(block_id)
    if merger is None:
        raise ContractViolation(f"未知分析块: {block_id}")
    return merger(state, result, response)
