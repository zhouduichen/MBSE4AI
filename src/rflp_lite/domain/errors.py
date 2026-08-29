class RflpError(Exception):
    """Base error for stable CLI error reporting."""


class InvariantViolation(RflpError):
    """Raised when a domain invariant is violated."""


class ContractViolation(RflpError):
    """Raised when an external contract fails validation."""


class AdapterFailure(RflpError):
    """Raised when an adapter fails at a controlled boundary."""


class ConcurrentModificationError(RflpError):
    """Raised when a Workbench write observes a stale revision."""


class ValidationError(ContractViolation):
    """Typed validation failure at an application boundary."""


class NotFoundError(ContractViolation):
    """Requested workspace or entity does not exist."""


class ConflictError(RflpError):
    """A valid command conflicts with current business state."""


class CapabilityUnavailableError(RflpError):
    """An optional local capability is not available."""


class ExternalServiceError(AdapterFailure):
    """A controlled failure from an external provider."""
