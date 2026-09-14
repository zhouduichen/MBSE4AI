"""Structural checks after a runtime has converted output to a Patch."""

from __future__ import annotations

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import Patch
from rflp_lite.methodology.validation import ValidationContext


_OFFLINE_BATCH_DIAGNOSTIC = "offline:lifecycle-runtime"


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
    # The 32-operation limit bounds untrusted structured outputs.  The
    # deterministic lifecycle runtime already owns the typed Patch and needs
    # to batch one independent V&V pair per requirement in a single task.
    if (
        len(response.patch.operations) > 32
        and _OFFLINE_BATCH_DIAGNOSTIC not in response.diagnostics
    ):
        raise MethodologyValidationError("schema_invalid", "patch exceeds the 32-operation contract")
