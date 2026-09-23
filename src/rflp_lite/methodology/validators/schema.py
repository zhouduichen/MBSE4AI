"""Structural checks after a runtime has converted output to a Patch."""

from __future__ import annotations

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import Patch
from rflp_lite.methodology.validation import ValidationContext


_TRUSTED_BATCH_DIAGNOSTICS = frozenset({
    "offline:lifecycle-runtime",
    "offline:vertical-runtime",
})
_VERTICAL_OPERATION_LIMIT = 64
_DEFAULT_OPERATION_LIMIT = 32
_TASK_OPERATION_LIMITS = {
    # Scenario exploration is a bounded fan-out task: one compact hypothesis
    # per supported scenario class plus its source edges can legitimately
    # exceed the legacy fine-grained 32-operation envelope.
    "scenario_exploration": 64,
}


def validate(context: ValidationContext) -> None:
    response = context.response
    if not hasattr(response, "status"):
        raise MethodologyValidationError("schema_invalid", "task response is not a TaskExecutionResponse")
    if response.patch is not None and not isinstance(response.patch, Patch):
        raise MethodologyValidationError("schema_invalid", "task response patch is not a Patch")
    if response.patch is None:
        return
    if response.status.value != "completed":
        raise MethodologyValidationError(
            "schema_invalid", "non-completed response cannot carry a committable patch"
        )
    if not isinstance(response.patch.operations, tuple):
        raise MethodologyValidationError("schema_invalid", "patch operations must be a tuple")
    # Vertical generation is a product-level closure: the Requirements stage
    # may legitimately add the operational entities and their typed relations
    # in one response. Keep that envelope bounded, but do not make the
    # entity-count and relation-count limits add up to an impossible total.
    # Legacy fine-grained tasks retain the smaller limit.
    operation_limit = _TASK_OPERATION_LIMITS.get(
        context.task.id,
        _VERTICAL_OPERATION_LIMIT
        if context.task.id.startswith("vertical.")
        else _DEFAULT_OPERATION_LIMIT,
    )
    if (
        len(response.patch.operations) > operation_limit
        and not any(
            diagnostic in response.diagnostics
            for diagnostic in _TRUSTED_BATCH_DIAGNOSTICS
        )
        and not (
            context.task.id.startswith("vertical.")
            and any(
                diagnostic.startswith("batch_count=")
                for diagnostic in response.diagnostics
            )
        )
    ):
        raise MethodologyValidationError(
            "schema_invalid",
            f"patch exceeds the {operation_limit}-operation contract",
        )
