"""Transparent, dependency-free discipline evaluators.

These calculators intentionally stay small and auditable.  They are useful
for local development and workflow integration; their ``evidence_status`` is
always ``development`` until a customer-approved evaluator profile promotes a
result to formal evidence.  A malformed candidate never leaks an exception
past the adapter boundary: it becomes a structured ``failed`` evaluation with
an actionable diagnostic.
"""

from __future__ import annotations

import math
from typing import Callable

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import DisciplineEvaluation, LayoutCandidate


_GRAVITY_MPS2 = 9.80665
_SOURCE_KIND = "analytical"
_EVIDENCE_STATUS = "development"


def _candidate_values(
    candidate: LayoutCandidate, profile: dict[str, object]
) -> dict[str, object]:
    """Merge profile defaults and candidate values into a flat value mapping.

    Candidate parameters are authoritative.  Geometry is accepted as a
    fallback because layout renderers may store dimensional values there,
    while a profile's ``defaults`` mapping is only used for omitted optional
    inputs.  This keeps the adapter useful across both the generated-candidate
    and hand-authored test paths without changing the core record.
    """

    values: dict[str, object] = {}
    defaults = profile.get("defaults", {})
    if isinstance(defaults, dict):
        values.update(defaults)
    values.update(dict(candidate.geometry))
    values.update(dict(candidate.parameters))
    return values


def _input_hash(
    candidate: LayoutCandidate, adapter_id: str, adapter_version: str, values: dict[str, object]
) -> str:
    return canonical_hash(
        {
            "candidate_id": candidate.id,
            "candidate_result_hash": candidate.result_hash,
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "values": values,
        }
    )


def _evaluation_id(candidate: LayoutCandidate, adapter_id: str) -> str:
    return f"{candidate.id}:{adapter_id}"


def _make_evaluation(
    *,
    candidate: LayoutCandidate,
    adapter_id: str,
    adapter_version: str,
    input_hash: str,
    status: str,
    metrics: tuple[tuple[str, float], ...] = (),
    diagnostics: tuple[str, ...] = (),
) -> DisciplineEvaluation:
    output_hash = canonical_hash(
        {
            "adapter_id": adapter_id,
            "adapter_version": adapter_version,
            "candidate_id": candidate.id,
            "input_hash": input_hash,
            "status": status,
            "metrics": metrics,
            "diagnostics": diagnostics,
        }
    )
    return DisciplineEvaluation(
        id=_evaluation_id(candidate, adapter_id),
        candidate_id=candidate.id,
        discipline="",
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        source_kind=_SOURCE_KIND,
        input_hash=input_hash,
        output_hash=output_hash,
        metrics=metrics,
        status=status,
        evidence_status=_EVIDENCE_STATUS,
        validity=(),
        diagnostics=diagnostics,
        log_ref="",
    )


def _numeric_inputs(
    values: dict[str, object], required: tuple[str, ...]
) -> tuple[dict[str, float] | None, tuple[str, ...]]:
    """Validate required positive finite numeric values without raising."""

    normalized: dict[str, float] = {}
    errors: list[str] = []
    for name in required:
        if name not in values or values[name] is None:
            errors.append(f"missing required parameter '{name}'")
            continue
        raw = values[name]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            errors.append(f"parameter '{name}' must be numeric")
            continue
        number = float(raw)
        if not math.isfinite(number):
            errors.append(f"parameter '{name}' must be finite")
            continue
        if number <= 0:
            errors.append(f"parameter '{name}' must be > 0")
            continue
        normalized[name] = number
    return (normalized if not errors else None), tuple(errors)


def _run_safe(
    *,
    candidate: LayoutCandidate,
    adapter_id: str,
    adapter_version: str,
    discipline: str,
    required: tuple[str, ...],
    profile: dict[str, object],
    calculate: Callable[[dict[str, float]], tuple[tuple[str, float], ...]],
) -> DisciplineEvaluation:
    values = _candidate_values(candidate, profile)
    input_hash = _input_hash(candidate, adapter_id, adapter_version, values)
    numeric, errors = _numeric_inputs(values, required)
    if errors:
        result = _make_evaluation(
            candidate=candidate,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            input_hash=input_hash,
            status="failed",
            diagnostics=errors,
        )
        return DisciplineEvaluation(
            id=result.id,
            candidate_id=result.candidate_id,
            discipline=discipline,
            adapter_id=result.adapter_id,
            adapter_version=result.adapter_version,
            source_kind=result.source_kind,
            input_hash=result.input_hash,
            output_hash=result.output_hash,
            metrics=result.metrics,
            status=result.status,
            evidence_status=result.evidence_status,
            validity=result.validity,
            diagnostics=result.diagnostics,
            log_ref=result.log_ref,
        )
    try:
        metrics = calculate(numeric)
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        diagnostics = (f"{discipline} calculation failed: {exc}",)
        result = _make_evaluation(
            candidate=candidate,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            input_hash=input_hash,
            status="failed",
            diagnostics=diagnostics,
        )
        return DisciplineEvaluation(
            id=result.id,
            candidate_id=result.candidate_id,
            discipline=discipline,
            adapter_id=result.adapter_id,
            adapter_version=result.adapter_version,
            source_kind=result.source_kind,
            input_hash=result.input_hash,
            output_hash=result.output_hash,
            metrics=result.metrics,
            status=result.status,
            evidence_status=result.evidence_status,
            validity=result.validity,
            diagnostics=result.diagnostics,
            log_ref=result.log_ref,
        )
    result = _make_evaluation(
        candidate=candidate,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        input_hash=input_hash,
        status="succeeded",
        metrics=metrics,
    )
    return DisciplineEvaluation(
        id=result.id,
        candidate_id=result.candidate_id,
        discipline=discipline,
        adapter_id=result.adapter_id,
        adapter_version=result.adapter_version,
        source_kind=result.source_kind,
        input_hash=result.input_hash,
        output_hash=result.output_hash,
        metrics=result.metrics,
        status=result.status,
        evidence_status=result.evidence_status,
        validity=result.validity,
        diagnostics=result.diagnostics,
        log_ref=result.log_ref,
    )


class AerodynamicsAdapter:
    """Low-order fixed-wing aerodynamic calculator."""

    id = "builtin.aerodynamics.v1"
    version = "1"
    source_kind = _SOURCE_KIND
    implementation_hash = "builtin-aerodynamics-v1-low-order-analytical"

    def evaluate(
        self, candidate: LayoutCandidate, profile: dict[str, object]
    ) -> DisciplineEvaluation:
        required = (
            "mass_kg",
            "payload_kg",
            "wing_area_m2",
            "span_m",
            "cruise_speed_mps",
            "air_density_kg_m3",
            "cd0",
            "oswald_efficiency",
        )

        def calculate(values: dict[str, float]) -> tuple[tuple[str, float], ...]:
            total_mass = values["mass_kg"] + values["payload_kg"]
            aspect_ratio = values["span_m"] ** 2 / values["wing_area_m2"]
            dynamic_pressure = 0.5 * values["air_density_kg_m3"] * values["cruise_speed_mps"] ** 2
            cl = total_mass * _GRAVITY_MPS2 / (dynamic_pressure * values["wing_area_m2"])
            cd = values["cd0"] + cl**2 / (
                math.pi * values["oswald_efficiency"] * aspect_ratio
            )
            lift_to_drag = cl / cd
            return (
                ("aerodynamics.aspect_ratio", aspect_ratio),
                ("aerodynamics.cl", cl),
                ("aerodynamics.cd", cd),
                ("aerodynamics.lift_to_drag", lift_to_drag),
            )

        return _run_safe(
            candidate=candidate,
            adapter_id=self.id,
            adapter_version=self.version,
            discipline="aerodynamics",
            required=required,
            profile=profile,
            calculate=calculate,
        )


class StructuresAdapter:
    """Transparent cantilever-root structural stress calculator."""

    id = "builtin.structures.v1"
    version = "1"
    source_kind = _SOURCE_KIND
    implementation_hash = "builtin-structures-v1-low-order-analytical"

    def evaluate(
        self, candidate: LayoutCandidate, profile: dict[str, object]
    ) -> DisciplineEvaluation:
        required = (
            "mass_kg",
            "payload_kg",
            "span_m",
            "load_factor",
            "section_modulus_m3",
            "allowable_stress_pa",
        )

        def calculate(values: dict[str, float]) -> tuple[tuple[str, float], ...]:
            total_mass = values["mass_kg"] + values["payload_kg"]
            root_bending_moment = (
                values["load_factor"]
                * total_mass
                * _GRAVITY_MPS2
                * values["span_m"]
                / 4
            )
            stress = root_bending_moment / values["section_modulus_m3"]
            stress_margin = values["allowable_stress_pa"] / stress - 1
            return (
                ("structures.root_bending_moment_nm", root_bending_moment),
                ("structures.stress_pa", stress),
                ("structures.stress_margin", stress_margin),
            )

        return _run_safe(
            candidate=candidate,
            adapter_id=self.id,
            adapter_version=self.version,
            discipline="structures",
            required=required,
            profile=profile,
            calculate=calculate,
        )


class WeightBalanceAdapter:
    """Mass and longitudinal centre-of-gravity calculator."""

    id = "builtin.weight-balance.v1"
    version = "1"
    source_kind = _SOURCE_KIND
    implementation_hash = "builtin-weight-balance-v1-low-order-analytical"

    def evaluate(
        self, candidate: LayoutCandidate, profile: dict[str, object]
    ) -> DisciplineEvaluation:
        required = ("mass_kg", "payload_kg", "fuselage_length_m", "cg_x_m")

        def calculate(values: dict[str, float]) -> tuple[tuple[str, float], ...]:
            total_mass = values["mass_kg"] + values["payload_kg"]
            cg_fraction = values["cg_x_m"] / values["fuselage_length_m"]
            return (
                ("weight_balance.total_mass_kg", total_mass),
                ("weight_balance.cg_fraction", cg_fraction),
            )

        return _run_safe(
            candidate=candidate,
            adapter_id=self.id,
            adapter_version=self.version,
            discipline="weight_balance",
            required=required,
            profile=profile,
            calculate=calculate,
        )


def discipline_registry() -> dict[str, object]:
    """Return the built-in registry keyed by stable adapter ID."""

    return {
        AerodynamicsAdapter.id: AerodynamicsAdapter(),
        StructuresAdapter.id: StructuresAdapter(),
        WeightBalanceAdapter.id: WeightBalanceAdapter(),
    }


__all__ = [
    "AerodynamicsAdapter",
    "StructuresAdapter",
    "WeightBalanceAdapter",
    "discipline_registry",
]
