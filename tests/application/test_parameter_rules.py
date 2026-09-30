import pytest

from rflp_lite.application.parameter_rules import (
    create_indicator_envelope,
    evaluate_constraints,
    evaluate_formula,
    normalize_parameters,
)
from rflp_lite.domain.errors import ContractViolation


@pytest.fixture
def pack() -> dict[str, object]:
    return {
        "schema_version": 1,
        "id": "test",
        "version": 1,
        "object_type": "layout",
        "id_prefix": "T",
        "parameters": [
            {"name": "span_m", "unit": "m", "type": "number", "required": True},
            {"name": "wing_area_m2", "unit": "m2", "type": "number", "required": True},
            {"name": "mass_kg", "unit": "kg", "type": "number", "required": True},
            {"name": "max_mass_kg", "unit": "kg", "type": "number", "required": True},
        ],
        "derived_parameters": [
            {"name": "aspect_ratio", "formula": "span_m ** 2 / wing_area_m2", "unit": "1"}
        ],
        "constraints": [
            {
                "id": "max-mass",
                "severity": "hard",
                "left": "mass_kg",
                "operator": "<=",
                "right": {"parameter": "max_mass_kg"},
                "message": "mass must be below the limit",
            },
            {
                "id": "ratio-positive",
                "severity": "soft",
                "left": "aspect_ratio",
                "operator": ">",
                "right": {"value": 0},
            },
        ],
        "mappings": {},
        "retrieval": {"features": []},
        "generation": {},
        "objectives": [],
        "disciplines": [],
    }


def test_unit_normalization_and_safe_formula(pack):
    values = normalize_parameters(pack, {"span_m": {"value": 1200, "unit": "mm"}, "wing_area_m2": 20, "mass_kg": 900, "max_mass_kg": 1000})
    assert values["span_m"] == 1.2
    assert evaluate_formula("span_m ** 2 / wing_area_m2", {"span_m": 10.0, "wing_area_m2": 20.0}) == 5.0


@pytest.mark.parametrize("formula", ["open('x')", "x.__class__", "x[0]"])
def test_formula_rejects_execution_features(formula):
    with pytest.raises(ContractViolation, match="formula"):
        evaluate_formula(formula, {"x": 1})


def test_formula_rejects_dynamic_large_exponent_and_nonfinite_result():
    with pytest.raises(ContractViolation, match="exponent"):
        evaluate_formula("x ** power", {"x": 2, "power": 9})
    with pytest.raises(ContractViolation, match="arithmetic|finite"):
        evaluate_formula("x / y", {"x": 1, "y": 0})


def test_hard_constraint_reports_value_limit_margin_and_status(pack):
    results = evaluate_constraints(pack, {"span_m": 10.0, "wing_area_m2": 20.0, "mass_kg": 900.0, "max_mass_kg": 1000.0}, "candidate-1")
    result = next(item for item in results if item.constraint_id == "max-mass")
    assert (result.actual, result.limit, result.margin, result.passed) == (900.0, 1000.0, 100.0, True)


def test_soft_constraint_missing_operand_is_a_failed_result(pack):
    pack = {**pack, "constraints": [
        {"id": "optional", "severity": "soft", "left": "missing", "operator": ">=", "right": {"value": 0}}
    ]}
    # The pack is intentionally hand-built for this focused rule test; the
    # runtime reports the missing operand instead of making it hard.
    pack["parameters"] = [item for item in pack["parameters"] if item["name"] != "max_mass_kg"]
    results = evaluate_constraints(pack, {"span_m": 10.0, "wing_area_m2": 20.0, "mass_kg": 900.0}, "candidate-1")
    assert len(results) == 1
    assert results[0].passed is False
    assert "unknown parameter" in results[0].message


def test_conflicting_envelope_is_rejected(pack):
    with pytest.raises(ContractViolation, match="minimum.*maximum"):
        create_indicator_envelope(pack, {"mass_kg": {"minimum": 1000, "maximum": 900}}, ())


def test_envelope_normalizes_bounds_and_generates_stable_identity(pack):
    payload = {
        "parameters": {
            "span_m": {"value": 1200, "unit": "cm"},
            "wing_area_m2": 20,
            "mass_kg": 900,
            "max_mass_kg": 1000,
        },
        "bounds": {"mass_kg": {"minimum": 800000, "maximum": 1000000, "unit": "g"}},
    }
    first = create_indicator_envelope(pack, payload, ("REQ-1",))
    second = create_indicator_envelope(pack, payload, ("REQ-1",))
    assert dict(first.parameters)["span_m"] == 12.0
    assert first.bounds == (("mass_kg", 800.0, 1000.0),)
    assert first.id == second.id
    assert first.input_hash == second.input_hash

