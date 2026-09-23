"""Comparable benchmark scenario contracts.

Graph normalization and execution live in ``runners.scenario_pipeline`` so
every scenario uses one observable boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping

from rflp_lite.domain.model import ModelGraph


class BenchmarkScenario(StrEnum):
    A_BARE_ONE_SHOT = "A_bare_one_shot_full_rflp_vv"
    B_BARE_STAGED = "B_bare_staged_rflp_vv"
    C_HARNESS_NO_VERIFIER = "C_harness_without_verifier"
    D_HARNESS_NO_REPAIR = "D_harness_without_repair"
    E_FULL_HARNESS = "E_full_harness"


@dataclass(frozen=True, slots=True)
class ScenarioContract:
    scenario: BenchmarkScenario
    description: str
    generation_shape: str
    verifier_enabled: bool
    gate_enabled: bool
    repair_enabled: bool
    cas_enabled: bool

    @property
    def has_verifier(self) -> bool:
        return self.verifier_enabled

    @property
    def has_repair(self) -> bool:
        return self.repair_enabled

    @property
    def has_cas(self) -> bool:
        return self.cas_enabled


SCENARIO_CONTRACTS = (
    ScenarioContract(
        BenchmarkScenario.A_BARE_ONE_SHOT,
        "one-shot full RFLP+V&V model output",
        "one_shot",
        False,
        False,
        False,
        False,
    ),
    ScenarioContract(
        BenchmarkScenario.B_BARE_STAGED,
        "staged R→F→L→P→V&V output without Harness controls",
        "staged",
        False,
        False,
        False,
        False,
    ),
    ScenarioContract(
        BenchmarkScenario.C_HARNESS_NO_VERIFIER,
        "real Harness path with verifier disabled",
        "harness",
        False,
        True,
        True,
        True,
    ),
    ScenarioContract(
        BenchmarkScenario.D_HARNESS_NO_REPAIR,
        "real Harness path with repair disabled",
        "harness",
        True,
        True,
        False,
        True,
    ),
    ScenarioContract(
        BenchmarkScenario.E_FULL_HARNESS,
        "real Harness path with verifier, repair, gates, and CAS",
        "harness",
        True,
        True,
        True,
        True,
    ),
)


def scenario_contract(value: str | BenchmarkScenario) -> ScenarioContract:
    requested = BenchmarkScenario(value)
    return next(item for item in SCENARIO_CONTRACTS if item.scenario is requested)


def validate_ablation_contracts() -> None:
    """Fail closed when C/D/E are not one-control ablations of E."""

    full = next(item for item in SCENARIO_CONTRACTS if item.scenario is BenchmarkScenario.E_FULL_HARNESS)
    controls = ("verifier_enabled", "gate_enabled", "repair_enabled", "cas_enabled")
    expected_changes = {
        BenchmarkScenario.C_HARNESS_NO_VERIFIER: "verifier_enabled",
        BenchmarkScenario.D_HARNESS_NO_REPAIR: "repair_enabled",
    }
    for scenario, changed_control in expected_changes.items():
        candidate = next(item for item in SCENARIO_CONTRACTS if item.scenario is scenario)
        if candidate.generation_shape != full.generation_shape:
            raise ValueError(f"{scenario.value} changes generation shape relative to E")
        changes = [
            control
            for control in controls
            if getattr(candidate, control) != getattr(full, control)
        ]
        if changes != [changed_control]:
            raise ValueError(
                f"{scenario.value} is not an orthogonal ablation: {changes}"
            )


def normalize_to_model_graph(value: object, *, project_id: str = "benchmark") -> ModelGraph:
    """Compatibility wrapper for the one canonical normalizer."""

    from tests.mbse_benchmark.runners.scenario_pipeline import ModelGraphNormalizer

    return ModelGraphNormalizer().normalize(value, project_id=project_id)


def evaluate_normalized(
    value: object,
    evaluator: Callable[[ModelGraph], Mapping[str, object]],
    *,
    project_id: str = "benchmark",
) -> dict[str, object]:
    """Compatibility helper that evaluates through the canonical normalizer."""

    graph = normalize_to_model_graph(value, project_id=project_id)
    from tests.mbse_benchmark.runners.scenario_pipeline import ModelGraphNormalizer

    return {
        "graph": ModelGraphNormalizer().payload(graph),
        "metrics": dict(evaluator(graph)),
    }


__all__ = [
    "BenchmarkScenario",
    "SCENARIO_CONTRACTS",
    "ScenarioContract",
    "evaluate_normalized",
    "normalize_to_model_graph",
    "scenario_contract",
    "validate_ablation_contracts",
]
