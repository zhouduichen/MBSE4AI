"""Central mapping from typed application errors to stable HTTP payloads."""

from __future__ import annotations

from rflp_lite.domain.errors import (
    AdapterFailure,
    CapabilityUnavailableError,
    ConcurrentModificationError,
    ConflictError,
    ContractViolation,
    ExternalServiceError,
    InvariantViolation,
    NotFoundError,
    RflpError,
    ValidationError,
)


_ERRORS: tuple[tuple[type[BaseException], str, int], ...] = (
    (NotFoundError, "not_found", 404),
    (ConcurrentModificationError, "conflict", 409),
    (ConflictError, "conflict", 409),
    (ValidationError, "validation_error", 422),
    (ContractViolation, "contract_violation", 422),
    (CapabilityUnavailableError, "capability_unavailable", 503),
    (ExternalServiceError, "external_service_error", 502),
    (AdapterFailure, "adapter_failure", 502),
    (InvariantViolation, "invariant_violation", 422),
)


def map_error(error: BaseException) -> tuple[int, dict[str, object]]:
    for error_type, code, status in _ERRORS:
        if isinstance(error, error_type):
            return status, {"error_code": code, "message": str(error), "diagnostics": ()}
    if isinstance(error, RflpError):
        return 422, {"error_code": "rflp_error", "message": str(error), "diagnostics": ()}
    return 500, {"error_code": "internal_error", "message": "内部错误", "diagnostics": ()}
