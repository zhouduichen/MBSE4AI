from __future__ import annotations

import math

import pytest

from rflp_lite.adapters.disciplines import (
    AerodynamicsAdapter,
    StructuresAdapter,
    WeightBalanceAdapter,
    discipline_registry,
)
from rflp_lite.domain.concept_design import LayoutCandidate


def _candidate(**overrides: object) -> LayoutCandidate:
    values: dict[str, object] = {
        "mass_kg": 120.0,
        "payload_kg": 30.0,
        "wing_area_m2": 20.0,
        "span_m": 10.0,
        "fuselage_length_m": 8.0,
        "cruise_speed_mps": 60.0,
        "air_density_kg_m3": 1.225,
        "cd0": 0.025,
        "oswald_efficiency": 0.8,
        "load_factor": 3.5,
        "section_modulus_m3": 0.002,
        "allowable_stress_pa": 250_000_000.0,
        "cg_x_m": 2.4,
    }
    values.update(overrides)
    return LayoutCandidate(
        id="FW-C-1",
        envelope_id="FW-E-1",
        domain_pack_id="fixed-wing",
        domain_pack_version=1,
        reference_ids=(),
        similarity_matches=(),
        parameters=tuple(sorted(values.items())),
        parameter_sources=(),
        geometry=(),
        svg="<svg></svg>",
        constraints=(),
        feasible=True,
        infeasible_reasons=(),
        status="feasible",
        generator_version="test",
        seed=42,
        input_hash="input",
        result_hash="result",
    )


@pytest.mark.parametrize(
    "adapter_id",
    [
        "builtin.aerodynamics.v1",
        "builtin.structures.v1",
        "builtin.weight-balance.v1",
    ],
)
def test_builtin_adapter_returns_versioned_metrics(adapter_id: str):
    candidate = _candidate()
    result = discipline_registry()[adapter_id].evaluate(candidate, {})
    assert result.status == "succeeded"
    assert result.adapter_id == adapter_id
    assert result.adapter_version == "1"
    assert result.source_kind == "analytical"
    assert result.evidence_status == "development"
    assert result.input_hash and result.output_hash
    assert result.candidate_id == candidate.id
    assert result.discipline in {"aerodynamics", "structures", "weight_balance"}


def test_weight_balance_formula_is_transparent():
    result = WeightBalanceAdapter().evaluate(_candidate(), {})
    metrics = dict(result.metrics)
    assert metrics["weight_balance.total_mass_kg"] == pytest.approx(150.0)
    assert metrics["weight_balance.cg_fraction"] == pytest.approx(0.3)


def test_aerodynamics_formula_is_transparent():
    candidate = _candidate()
    result = AerodynamicsAdapter().evaluate(candidate, {})
    metrics = dict(result.metrics)
    total_mass = 150.0
    aspect_ratio = 10.0**2 / 20.0
    dynamic_pressure = 0.5 * 1.225 * 60.0**2
    cl = total_mass * 9.80665 / (dynamic_pressure * 20.0)
    cd = 0.025 + cl**2 / (math.pi * 0.8 * aspect_ratio)
    assert metrics["aerodynamics.aspect_ratio"] == pytest.approx(aspect_ratio)
    assert metrics["aerodynamics.cl"] == pytest.approx(cl)
    assert metrics["aerodynamics.cd"] == pytest.approx(cd)
    assert metrics["aerodynamics.lift_to_drag"] == pytest.approx(cl / cd)


def test_structural_formula_is_transparent():
    result = StructuresAdapter().evaluate(_candidate(), {})
    metrics = dict(result.metrics)
    root_moment = 3.5 * 150.0 * 9.80665 * 10.0 / 4
    stress = root_moment / 0.002
    assert metrics["structures.root_bending_moment_nm"] == pytest.approx(root_moment)
    assert metrics["structures.stress_pa"] == pytest.approx(stress)
    assert metrics["structures.stress_margin"] == pytest.approx(250_000_000.0 / stress - 1)


@pytest.mark.parametrize(
    "field, value, diagnostic",
    [
        ("mass_kg", None, "missing required parameter 'mass_kg'"),
        ("mass_kg", "120", "parameter 'mass_kg' must be numeric"),
        ("mass_kg", 0, "parameter 'mass_kg' must be > 0"),
        ("span_m", -1, "parameter 'span_m' must be > 0"),
    ],
)
def test_invalid_required_input_is_a_structured_failure(
    field: str, value: object, diagnostic: str
):
    result = AerodynamicsAdapter().evaluate(_candidate(**{field: value}), {})
    assert result.status == "failed"
    assert diagnostic in result.diagnostics
    assert result.metrics == ()
    assert result.input_hash and result.output_hash


def test_profile_defaults_fill_omitted_optional_like_inputs():
    candidate = _candidate()
    values = dict(candidate.parameters)
    for field in ("air_density_kg_m3", "cd0", "oswald_efficiency"):
        values.pop(field)
    candidate = _candidate(**values)
    result = AerodynamicsAdapter().evaluate(
        candidate,
        {"defaults": {"air_density_kg_m3": 1.225, "cd0": 0.025, "oswald_efficiency": 0.8}},
    )
    assert result.status == "succeeded"


def test_same_candidate_produces_same_evaluation_hashes():
    candidate = _candidate()
    adapter = AerodynamicsAdapter()
    first = adapter.evaluate(candidate, {})
    second = adapter.evaluate(candidate, {})
    assert first == second
    assert first.input_hash == second.input_hash
    assert first.output_hash == second.output_hash

