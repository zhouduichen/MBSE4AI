class RflpError(Exception):
    """Base error for stable CLI error reporting."""


class InvariantViolation(RflpError):
    """Raised when a domain invariant is violated."""


class ContractViolation(RflpError):
    """Raised when an external contract fails validation."""


class InputRequired(ContractViolation):
    """Raised when analysis is requested before user/project input exists."""


class AdapterFailure(RflpError):
    """Raised when an adapter fails at a controlled boundary."""


class StructuredOutputFailure(AdapterFailure):
    """Raised when a model response cannot cross the structural JSON boundary."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "structured_output",
        raw_response: str = "",
        initial_raw_response: str = "",
        schema_hash: str = "",
        retry_count: int = 0,
        provider_id: str = "",
        model_id: str = "",
    ) -> None:
        self.stage = "structural"
        self.code = str(code)
        self.raw_response = str(raw_response)[:12000]
        self.initial_raw_response = str(initial_raw_response)[:12000]
        self.schema_hash = str(schema_hash)
        self.retry_count = int(retry_count)
        self.provider_id = str(provider_id)
        self.model_id = str(model_id)
        super().__init__(message)


class ProposalCompileFailure(ContractViolation):
    """Raised when a valid semantic proposal cannot become a domain Patch."""

    def __init__(self, message: str, *, code: str = "proposal_compile") -> None:
        self.stage = "compiler"
        self.code = str(code)
        super().__init__(message)


class ConcurrentModificationError(RflpError):
    """Raised when a Workbench write observes a stale revision."""


class ValidationError(ContractViolation):
    """Typed validation failure at an application boundary."""


class MethodologyValidationError(ValidationError):
    """A deterministic methodology contract failure with a routable code."""

    def __init__(self, code: str, message: str):
        self.code = str(code)
        super().__init__(f"{self.code}: {message}")


class NotFoundError(ContractViolation):
    """Requested workspace or entity does not exist."""


class ConflictError(ContractViolation):
    """A valid command conflicts with current business state."""


class CapabilityUnavailableError(RflpError):
    """An optional local capability is not available."""


class ExternalServiceError(AdapterFailure):
    """A controlled failure from an external provider."""
