class RflpError(Exception):
    """Base error for stable CLI error reporting."""


class InvariantViolation(RflpError):
    """Raised when a domain invariant is violated."""


class ContractViolation(RflpError):
    """Raised when an external contract fails validation."""


class AdapterFailure(RflpError):
    """Raised when an adapter fails at a controlled boundary."""

