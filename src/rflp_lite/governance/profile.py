from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class Profile:
    name: str = "local-demo"
    solver: str = "heuristic"
    seed: int = 42
    candidate_limit: int = 3
    timeout_seconds: int = 5

    def __post_init__(self) -> None:
        if self.solver not in {"heuristic", "cp-sat"}:
            raise ContractViolation(f"unsupported solver: {self.solver}")
        if self.seed < 0:
            raise ContractViolation("seed must be non-negative")
        if not 2 <= self.candidate_limit <= 3:
            raise ContractViolation("candidate_limit must be between 2 and 3")
        if self.timeout_seconds <= 0:
            raise ContractViolation("timeout_seconds must be positive")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "solver": self.solver,
            "seed": self.seed,
            "candidate_limit": self.candidate_limit,
            "timeout_seconds": self.timeout_seconds,
        }

