"""Parameter normalization, safe derived arithmetic, and envelope rules.

The concept-design workflow deliberately keeps this module small and
deterministic.  Domain packs describe parameter names, units, derived
expressions, and constraints; this module is the executable boundary that
interprets those declarations.  Formulas are evaluated with a tiny AST
interpreter rather than :func:`eval`, so a pack cannot execute Python code.
"""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Mapping
from typing import Any

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.concept_design import ConstraintResult, IndicatorEnvelope
from rflp_lite.domain.errors import ContractViolation


# This is intentionally a small, explicit table.  Adding a conversion is a
# domain decision and should be accompanied by a pack revision, rather than
# silently accepting arbitrary unit expressions.
_UNIT_SCALE: dict[tuple[str, str], float] = {
    ("mm", "m"): 0.001,
    ("cm", "m"): 0.01,
    ("g", "kg"): 0.001,
    ("kPa", "Pa"): 1000.0,
    ("km/h", "m/s"): 1 / 3.6,
}

_OPERATORS: dict[str, Any] = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "**": operator.pow,
}

_COMPARATORS: dict[str, Any] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}

_PARAMETER_META_KEYS = {"value", "unit"}
_FORMULA_NODE_TYPES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Name,
    ast.Constant,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)


def _contract(message: str) -> ContractViolation:
    return ContractViolation(message)


def _parameter_specs(pack: Mapping[str, object]) -> dict[str, dict[str, object]]:
    """Return parameter declarations indexed by name.

    ``domain_packs.validate_domain_pack`` normally runs before this module;
    these inexpensive checks keep failures clear when a caller supplies a
    hand-built pack in a unit test or integration boundary.
    """

    raw = pack.get("parameters")
    if not isinstance(raw, list):
        raise _contract("domain pack parameters must be an array")
    specs: dict[str, dict[str, object]] = {}
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise _contract(f"parameters[{index}] must be an object")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or name in specs:
            raise _contract(f"parameters[{index}].name is invalid or duplicated")
        unit = item.get("unit")
        type_name = item.get("type")
        if not isinstance(unit, str) or not unit.strip():
            raise _contract(f"parameters[{index}].unit must be a string")
        if type_name not in {"number", "string", "boolean"}:
            raise _contract(f"parameters[{index}].type is unsupported")
        specs[name] = dict(item)
    return specs


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise _contract(f"{label} must be numeric")
    if isinstance(value, str):
        if not value.strip():
            raise _contract(f"{label} must be numeric")
        try:
            value = float(value)
        except ValueError as exc:
            raise _contract(f"{label} must be numeric") from exc
    if not isinstance(value, (int, float)):
        raise _contract(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise _contract(f"{label} must be finite")
    return number


def _unit_scale(source: str, target: str) -> float:
    if source == target:
        return 1.0
    scale = _UNIT_SCALE.get((source, target))
    if scale is None:
        raise _contract(f"unsupported unit conversion: {source} -> {target}")
    return scale


def _convert_number(value: object, source_unit: str, target_unit: str, label: str) -> float:
    number = _finite_number(value, label)
    try:
        converted = number * _unit_scale(source_unit, target_unit)
    except (OverflowError, ValueError) as exc:
        raise _contract(f"{label} cannot be converted from {source_unit} to {target_unit}") from exc
    if not math.isfinite(converted):
        raise _contract(f"{label} must be finite after unit conversion")
    return converted


def _raw_value(raw: object, name: str) -> tuple[object, str | None]:
    """Extract a value and optional source unit from scalar/described input."""

    if not isinstance(raw, Mapping):
        return raw, None
    unknown = set(raw) - _PARAMETER_META_KEYS
    if unknown:
        fields = ", ".join(sorted(str(key) for key in unknown))
        raise _contract(f"parameter {name!r} contains unknown fields: {fields}")
    if "value" not in raw:
        raise _contract(f"parameter {name!r} requires value")
    unit = raw.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise _contract(f"parameter {name!r}.unit must be a string")
    return raw["value"], unit


def normalize_parameters(pack: Mapping[str, object], values: Mapping[str, object]) -> dict[str, object]:
    """Normalize parameter values to pack units and enforce declarations.

    A value may be supplied directly (``10.0``) or as ``{"value": 10,
    "unit": "mm"}``.  Missing optional parameters use their declared
    default; missing required parameters and unknown fields are rejected.
    """

    if not isinstance(values, Mapping):
        raise _contract("parameter values must be an object")
    # Accept the envelope's convenient wrapper while retaining the direct
    # mapping API used by generators and evaluators.
    raw_values: Mapping[str, object] = values
    if "parameters" in values:
        nested = values["parameters"]
        if not isinstance(nested, Mapping):
            raise _contract("parameters must be an object")
        extra = set(values) - {"parameters"}
        if extra:
            raise _contract("parameter envelope contains unknown fields")
        raw_values = nested

    specs = _parameter_specs(pack)
    unknown = set(raw_values) - set(specs)
    if unknown:
        fields = ", ".join(sorted(str(key) for key in unknown))
        raise _contract(f"unknown parameter: {fields}")

    normalized: dict[str, object] = {}
    for name, spec in specs.items():
        if name not in raw_values:
            if "default" in spec and spec.get("default") is not None:
                raw = spec["default"]
            elif bool(spec.get("required", False)):
                raise _contract(f"missing required parameter: {name}")
            else:
                continue
            source_unit = None
        else:
            raw, source_unit = _raw_value(raw_values[name], name)

        type_name = spec["type"]
        if type_name == "number":
            target_unit = str(spec["unit"])
            normalized_value = _convert_number(
                raw,
                source_unit or target_unit,
                target_unit,
                f"parameter {name!r}",
            )
            minimum = spec.get("minimum")
            maximum = spec.get("maximum")
            if minimum is not None and normalized_value < _finite_number(minimum, f"{name}.minimum"):
                raise _contract(f"parameter {name!r} is below minimum")
            if maximum is not None and normalized_value > _finite_number(maximum, f"{name}.maximum"):
                raise _contract(f"parameter {name!r} is above maximum")
            normalized[name] = normalized_value
        elif type_name == "string":
            if source_unit is not None:
                raise _contract(f"parameter {name!r} does not support units")
            if not isinstance(raw, str):
                raise _contract(f"parameter {name!r} must be a string")
            normalized[name] = raw
        else:  # boolean
            if source_unit is not None:
                raise _contract(f"parameter {name!r} does not support units")
            if not isinstance(raw, bool):
                raise _contract(f"parameter {name!r} must be boolean")
            normalized[name] = raw
    return normalized


def _validate_formula_tree(formula: str) -> ast.Expression:
    if not isinstance(formula, str) or not formula.strip():
        raise _contract("formula must be a non-empty string")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise _contract("formula syntax is invalid") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 64:
        raise _contract("formula is too complex")
    for node in nodes:
        if not isinstance(node, _FORMULA_NODE_TYPES):
            raise _contract("formula uses a forbidden operation")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise _contract("formula constants must be numeric")
            if not math.isfinite(float(node.value)):
                raise _contract("formula constants must be finite")
        if isinstance(node, ast.Name) and (not node.id or node.id.startswith("__")):
            raise _contract("formula contains an invalid name")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if isinstance(exponent, ast.Constant):
                try:
                    exponent_value = float(exponent.value)
                except (TypeError, ValueError) as exc:
                    raise _contract("formula exponent must be numeric") from exc
                if abs(exponent_value) > 8:
                    raise _contract("formula exponent is too large")
    return tree


def _formula_numeric(value: object, label: str = "formula result") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract(f"{label} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise _contract(f"{label} must be finite")
    return numeric


def evaluate_formula(formula: str, values: Mapping[str, object]) -> float:
    """Evaluate a safe arithmetic formula against numeric values.

    No Python evaluation or attribute/subscript/call capability is exposed.
    Every operation is checked for finite numeric output, including dynamic
    exponents supplied by a parameter name.
    """

    if not isinstance(values, Mapping):
        raise _contract("formula values must be an object")
    tree = _validate_formula_tree(formula)

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant):
            return _formula_numeric(node.value, "formula constant")
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise _contract(f"formula references unknown parameter: {node.id}")
            return _formula_numeric(values[node.id], f"formula parameter {node.id!r}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = visit(node.operand)
            result = +operand if isinstance(node.op, ast.UAdd) else -operand
            return _formula_numeric(result)
        if isinstance(node, ast.BinOp):
            if type(node.op) is ast.Pow:
                left = visit(node.left)
                exponent = visit(node.right)
                if abs(exponent) > 8:
                    raise _contract("formula exponent is too large")
                function = operator.pow
            else:
                function = None
                for symbol, candidate in _OPERATORS.items():
                    if type(node.op) is {"+": ast.Add, "-": ast.Sub, "*": ast.Mult, "/": ast.Div}.get(symbol):
                        function = candidate
                        break
                if function is None:
                    raise _contract("formula uses a forbidden operation")
                left = visit(node.left)
                right = visit(node.right)
            try:
                result = function(left, exponent) if type(node.op) is ast.Pow else function(left, right)
            except (ArithmeticError, OverflowError, ValueError, TypeError) as exc:
                raise _contract("formula arithmetic failed") from exc
            return _formula_numeric(result)
        raise _contract("formula uses a forbidden operation")

    return visit(tree)


def derive_parameters(pack: Mapping[str, object], values: Mapping[str, object]) -> dict[str, object]:
    """Normalize parameters and append pack-declared derived values."""

    normalized = normalize_parameters(pack, values)
    raw_derived = pack.get("derived_parameters", [])
    if not isinstance(raw_derived, list):
        raise _contract("domain pack derived_parameters must be an array")
    for index, item in enumerate(raw_derived):
        if not isinstance(item, Mapping):
            raise _contract(f"derived_parameters[{index}] must be an object")
        name = item.get("name")
        formula = item.get("formula")
        if not isinstance(name, str) or not name.strip() or not isinstance(formula, str):
            raise _contract(f"derived_parameters[{index}] is invalid")
        if name in normalized:
            raise _contract(f"derived parameter duplicates parameter: {name}")
        normalized[name] = evaluate_formula(formula, normalized)
    return normalized


def _right_operand(right: object, values: Mapping[str, object]) -> tuple[float, str | None]:
    if not isinstance(right, Mapping):
        raise _contract("constraint right operand must be an object")
    keys = set(right)
    if keys == {"value"}:
        return _finite_number(right["value"], "constraint limit"), None
    if keys == {"parameter"}:
        name = right["parameter"]
        if not isinstance(name, str) or name not in values:
            raise _contract(f"constraint references unknown parameter: {name}")
        return _finite_number(values[name], f"constraint parameter {name!r}"), name
    raise _contract("constraint right operand must contain value or parameter")


def _margin(operator_name: str, actual: float, limit: float) -> float:
    if operator_name in {">=", ">"}:
        return actual - limit
    if operator_name in {"<=", "<"}:
        return limit - actual
    if operator_name == "==":
        return -abs(actual - limit)
    return abs(actual - limit)


def evaluate_constraints(
    pack: Mapping[str, object], values: Mapping[str, object], candidate_id: str
) -> tuple[ConstraintResult, ...]:
    """Evaluate all declared constraints and return traceable results.

    A missing operand is a contract error for a hard constraint.  For a soft
    constraint, a failed result is emitted and the caller may continue; soft
    failures therefore never make a candidate infeasible by themselves.
    """

    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise _contract("candidate_id must be a non-empty string")
    try:
        all_values = derive_parameters(pack, values)
    except ContractViolation:
        # Normalization and derived arithmetic errors are contract failures;
        # constraints cannot be evaluated meaningfully without them.
        raise
    raw_constraints = pack.get("constraints", [])
    if not isinstance(raw_constraints, list):
        raise _contract("domain pack constraints must be an array")
    results: list[ConstraintResult] = []
    for index, item in enumerate(raw_constraints):
        if not isinstance(item, Mapping):
            raise _contract(f"constraints[{index}] must be an object")
        constraint_id = item.get("id")
        severity = item.get("severity", "hard")
        left_name = item.get("left")
        operator_name = item.get("operator")
        if not isinstance(constraint_id, str) or not constraint_id.strip():
            raise _contract(f"constraints[{index}].id is invalid")
        if severity not in {"hard", "soft"}:
            raise _contract(f"constraints[{index}].severity is unsupported")
        if not isinstance(left_name, str) or not left_name.strip():
            raise _contract(f"constraints[{index}].left is invalid")
        if operator_name not in _COMPARATORS:
            raise _contract(f"constraints[{index}].operator is unsupported")

        message = str(item.get("message") or f"constraint {constraint_id} failed")
        missing: str | None = None
        try:
            if left_name not in all_values:
                raise _contract(f"constraint references unknown parameter: {left_name}")
            actual = _finite_number(all_values[left_name], f"constraint parameter {left_name!r}")
            limit, _ = _right_operand(item.get("right"), all_values)
        except ContractViolation as exc:
            missing = str(exc)
            if severity == "hard":
                raise _contract(f"hard constraint {constraint_id} cannot be evaluated: {missing}") from exc
            results.append(
                ConstraintResult(
                    id=f"{candidate_id}:{constraint_id}",
                    candidate_id=candidate_id,
                    constraint_id=constraint_id,
                    severity=severity,
                    actual=0.0,
                    operator=str(operator_name),
                    limit=0.0,
                    margin=0.0,
                    passed=False,
                    message=f"{message}: {missing}",
                )
            )
            continue

        passed = bool(_COMPARATORS[str(operator_name)](actual, limit))
        results.append(
            ConstraintResult(
                id=f"{candidate_id}:{constraint_id}",
                candidate_id=candidate_id,
                constraint_id=constraint_id,
                severity=severity,
                actual=actual,
                operator=str(operator_name),
                limit=limit,
                margin=_margin(str(operator_name), actual, limit),
                passed=passed,
                message=message if passed else message,
            )
        )
    return tuple(results)


def _bounds_value(
    name: str,
    spec: Mapping[str, object],
    raw: object,
    key: str,
) -> tuple[float, float] | None:
    if not isinstance(raw, Mapping):
        return None
    if "minimum" not in raw and "maximum" not in raw:
        return None
    allowed = {"minimum", "maximum", "unit"}
    unknown = set(raw) - allowed
    if unknown:
        raise _contract(f"bounds for {name!r} contain unknown fields")
    if "minimum" not in raw or "maximum" not in raw:
        raise _contract(f"bounds for {name!r} require minimum and maximum")
    unit = raw.get("unit") or str(spec["unit"])
    if not isinstance(unit, str):
        raise _contract(f"bounds for {name!r}.unit must be a string")
    minimum = _convert_number(raw["minimum"], unit, str(spec["unit"]), f"{name}.minimum")
    maximum = _convert_number(raw["maximum"], unit, str(spec["unit"]), f"{name}.maximum")
    if minimum > maximum:
        raise _contract(f"bounds for {name!r} minimum must not exceed maximum")
    declared_min = spec.get("minimum")
    declared_max = spec.get("maximum")
    if declared_min is not None and minimum < _finite_number(declared_min, f"{name}.minimum"):
        raise _contract(f"bounds for {name!r} are below the declared minimum")
    if declared_max is not None and maximum > _finite_number(declared_max, f"{name}.maximum"):
        raise _contract(f"bounds for {name!r} are above the declared maximum")
    return minimum, maximum


def create_indicator_envelope(
    pack: Mapping[str, object], payload: Mapping[str, object], source_requirement_ids: tuple[str, ...] | list[str] | None
) -> IndicatorEnvelope:
    """Create a normalized, immutable indicator envelope from a JSON payload."""

    if not isinstance(payload, Mapping):
        raise _contract("indicator envelope payload must be an object")
    specs = _parameter_specs(pack)
    declared_ids = tuple(source_requirement_ids or payload.get("source_requirement_ids", ()))
    if any(not isinstance(item, str) or not item.strip() for item in declared_ids):
        raise _contract("source_requirement_ids must contain non-empty strings")

    raw_parameters: Mapping[str, object]
    if "parameters" in payload:
        candidate_parameters = payload["parameters"]
        if not isinstance(candidate_parameters, Mapping):
            raise _contract("indicator envelope parameters must be an object")
        raw_parameters = candidate_parameters
    else:
        metadata = {
            "id",
            "object_type",
            "schema_version",
            "revision",
            "status",
            "source_requirement_ids",
            "bounds",
        }
        raw_parameters = {key: value for key, value in payload.items() if key not in metadata}

    unknown = set(raw_parameters) - set(specs)
    if unknown:
        raise _contract(f"unknown parameter: {', '.join(sorted(str(key) for key in unknown))}")

    # A descriptor containing bounds but no value is a useful shorthand for an
    # indicator range.  Use its midpoint as the generation target while
    # retaining the explicit range in the envelope record.
    normalized_input: dict[str, object] = {}
    nested_bounds: dict[str, object] = {}
    for name, raw in raw_parameters.items():
        if isinstance(raw, Mapping) and ("minimum" in raw or "maximum" in raw) and "value" not in raw:
            nested_bounds[name] = raw
            if "minimum" in raw and "maximum" in raw:
                unit = raw.get("unit") or str(specs[name]["unit"])
                lo = _convert_number(raw["minimum"], str(unit), str(specs[name]["unit"]), f"{name}.minimum")
                hi = _convert_number(raw["maximum"], str(unit), str(specs[name]["unit"]), f"{name}.maximum")
                if lo > hi:
                    raise _contract(f"bounds for {name!r} minimum must not exceed maximum")
                normalized_input[name] = {"value": (lo + hi) / 2, "unit": str(specs[name]["unit"])}
            else:
                normalized_input[name] = raw
        else:
            normalized_input[name] = raw

    normalized = normalize_parameters(pack, normalized_input)

    explicit_bounds = payload.get("bounds", {})
    if explicit_bounds is None:
        explicit_bounds = {}
    if not isinstance(explicit_bounds, Mapping):
        raise _contract("indicator envelope bounds must be an object")
    all_bounds: dict[str, object] = {**nested_bounds, **dict(explicit_bounds)}
    bounds: list[tuple[str, float, float]] = []
    for name in sorted(all_bounds):
        if name not in specs:
            raise _contract(f"unknown bound parameter: {name}")
        pair = _bounds_value(name, specs[name], all_bounds[name], "bounds")
        if pair is not None:
            bounds.append((name, pair[0], pair[1]))

    # Validate any bounds against normalized values when a target value is
    # supplied.  A target outside its declared range is almost always a typo.
    for name, minimum, maximum in bounds:
        if name in normalized and not (minimum <= float(normalized[name]) <= maximum):
            raise _contract(f"parameter {name!r} is outside its indicator bounds")

    revision = payload.get("revision", 1)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise _contract("indicator envelope revision must be a positive integer")
    status = payload.get("status", "draft")
    if not isinstance(status, str) or not status.strip():
        raise _contract("indicator envelope status must be a non-empty string")
    object_type = payload.get("object_type", pack.get("object_type", "layout"))
    if not isinstance(object_type, str) or not object_type.strip():
        raise _contract("indicator envelope object_type must be a non-empty string")
    schema_version = payload.get("schema_version", pack.get("schema_version", 1))
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise _contract("indicator envelope schema_version must be a positive integer")
    pack_id = pack.get("id")
    pack_version = pack.get("version")
    if not isinstance(pack_id, str) or isinstance(pack_version, bool) or not isinstance(pack_version, int):
        raise _contract("domain pack identity is invalid")
    identity = {
        "pack": (pack_id, pack_version),
        "parameters": tuple(sorted(normalized.items())),
        "bounds": tuple(bounds),
        "source_requirement_ids": declared_ids,
        "revision": revision,
    }
    input_hash = canonical_hash(identity)
    prefix = str(pack.get("id_prefix", "ENVELOPE"))
    envelope_id = payload.get("id")
    if envelope_id is None:
        envelope_id = f"{prefix}-E-{input_hash[:12]}"
    if not isinstance(envelope_id, str) or not envelope_id.strip():
        raise _contract("indicator envelope id must be a non-empty string")
    return IndicatorEnvelope(
        id=envelope_id,
        object_type=object_type,
        schema_version=schema_version,
        domain_pack_id=pack_id,
        domain_pack_version=pack_version,
        revision=revision,
        status=status,
        source_requirement_ids=declared_ids,
        parameters=tuple(sorted(normalized.items())),
        bounds=tuple(bounds),
        input_hash=input_hash,
    )


__all__ = [
    "create_indicator_envelope",
    "derive_parameters",
    "evaluate_constraints",
    "evaluate_formula",
    "normalize_parameters",
]
