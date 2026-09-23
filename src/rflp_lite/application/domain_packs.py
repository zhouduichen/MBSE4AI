"""Load and validate declaration-only concept-design domain packs.

Domain packs are data, not plugins.  This module performs strict validation
before a pack reaches an application service, including an AST allowlist for
derived arithmetic and a guard against overriding the platform's fixed core
fields.
"""

from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path
from typing import Any
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


_REQUIRED = {
    "id",
    "version",
    "object_type",
    "id_prefix",
    "parameters",
    "derived_parameters",
    "constraints",
    "mappings",
    "retrieval",
    "generation",
    "objectives",
    "disciplines",
}
_ALLOWED = _REQUIRED | {
    "schema_version",
    "display_name",
    "description",
    "requirement_mappings",
    "requirement_derivations",
}
_CORE_FIELDS = {
    "id",
    "object_type",
    "schema_version",
    "domain_pack_id",
    "domain_pack_version",
    "revision",
    "status",
    "source",
    "content_hash",
    "input_hash",
    "result_hash",
    "evidence_status",
    "formal_status",
    "generator_version",
    "seed",
    "parameters",
    "extensions",
}
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FORMULA_NODES = (
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
_OPERATORS = {"==", "!=", "<", "<=", ">", ">="}


def _contract(message: str) -> ContractViolation:
    return ContractViolation(f"invalid domain pack: {message}")


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _contract(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise _contract(f"{label} must be an array")
    return value


def _keys(value: dict[str, Any], required: set[str], allowed: set[str], label: str) -> None:
    keys = set(value)
    missing = required - keys
    extra = keys - allowed
    if missing:
        raise _contract(f"{label} missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise _contract(f"{label} contains unknown fields: {', '.join(sorted(extra))}")


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _contract(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise _contract(f"{label} must be finite")
    return number


def _validate_formula(formula: object, label: str) -> None:
    if not isinstance(formula, str) or not formula.strip():
        raise _contract(f"{label} formula must be a non-empty string")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise _contract(f"{label} formula syntax is invalid") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 64:
        raise _contract(f"{label} formula is too complex")
    for node in nodes:
        if not isinstance(node, _FORMULA_NODES):
            raise _contract(f"{label} formula uses a forbidden operation")
        if isinstance(node, ast.Name):
            if not _NAME_RE.fullmatch(node.id) or node.id.startswith("__"):
                raise _contract(f"{label} formula contains an invalid name")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise _contract(f"{label} formula constants must be numeric")
            if not math.isfinite(float(node.value)):
                raise _contract(f"{label} formula constants must be finite")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            literal_exponent: float | None = None
            if isinstance(exponent, ast.Constant) and isinstance(exponent.value, (int, float)):
                literal_exponent = float(exponent.value)
            elif (
                isinstance(exponent, ast.UnaryOp)
                and isinstance(exponent.op, (ast.UAdd, ast.USub))
                and isinstance(exponent.operand, ast.Constant)
                and isinstance(exponent.operand.value, (int, float))
            ):
                literal_exponent = float(exponent.operand.value)
                if isinstance(exponent.op, ast.USub):
                    literal_exponent = -literal_exponent
            if literal_exponent is not None and abs(literal_exponent) > 8:
                raise _contract(f"{label} formula exponent is too large")


def _validate_parameters(values: object) -> set[str]:
    items = _list(values, "parameters")
    if len(items) > 500:
        raise _contract("parameters exceed the limit of 500")
    names: set[str] = set()
    allowed = {
        "name",
        "unit",
        "type",
        "required",
        "minimum",
        "maximum",
        "default",
        "description",
        "choices",
        "perturbation",
    }
    for index, raw in enumerate(items):
        item = _mapping(raw, f"parameters[{index}]")
        _keys(item, {"name", "unit", "type", "required"}, allowed, f"parameters[{index}]")
        name = item["name"]
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise _contract(f"parameters[{index}].name is invalid")
        if name in names:
            raise _contract(f"duplicate parameter id: {name}")
        names.add(name)
        if not isinstance(item["unit"], str) or not item["unit"].strip():
            raise _contract(f"parameters[{index}].unit must be a string")
        if item["type"] not in {"number", "string", "boolean"}:
            raise _contract(f"parameters[{index}].type is unsupported")
        if not isinstance(item["required"], bool):
            raise _contract(f"parameters[{index}].required must be boolean")
        minimum = item.get("minimum")
        maximum = item.get("maximum")
        if minimum is not None:
            minimum = _finite_number(minimum, f"parameters[{index}].minimum")
        if maximum is not None:
            maximum = _finite_number(maximum, f"parameters[{index}].maximum")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise _contract(f"parameters[{index}] minimum must not exceed maximum")
        if "default" in item and item["default"] is not None and item["type"] == "number":
            _finite_number(item["default"], f"parameters[{index}].default")
        if "choices" in item:
            choices = _list(item["choices"], f"parameters[{index}].choices")
            if not choices:
                raise _contract(f"parameters[{index}].choices must not be empty")
        if "perturbation" in item:
            perturbation = _mapping(item["perturbation"], f"parameters[{index}].perturbation")
            _keys(
                perturbation,
                set(),
                {"minimum", "maximum", "distribution"},
                f"parameters[{index}].perturbation",
            )
            for key in ("minimum", "maximum"):
                if key in perturbation:
                    _finite_number(perturbation[key], f"parameters[{index}].perturbation.{key}")
    return names


def _validate_derived(values: object, parameter_names: set[str]) -> set[str]:
    items = _list(values, "derived_parameters")
    if len(items) > 500:
        raise _contract("derived_parameters exceed the limit of 500")
    names: set[str] = set()
    allowed = {"name", "formula", "unit", "description"}
    for index, raw in enumerate(items):
        item = _mapping(raw, f"derived_parameters[{index}]")
        _keys(item, {"name", "formula", "unit"}, allowed, f"derived_parameters[{index}]")
        name = item["name"]
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise _contract(f"derived_parameters[{index}].name is invalid")
        if name in parameter_names or name in names:
            raise _contract(f"duplicate parameter id: {name}")
        _validate_formula(item["formula"], f"derived_parameters[{index}]")
        if not isinstance(item["unit"], str) or not item["unit"].strip():
            raise _contract(f"derived_parameters[{index}].unit must be a string")
        names.add(name)
    return names


def _validate_constraints(values: object, known_names: set[str]) -> None:
    items = _list(values, "constraints")
    if len(items) > 500:
        raise _contract("constraints exceed the limit of 500")
    seen: set[str] = set()
    allowed = {"id", "severity", "left", "operator", "right", "message"}
    for index, raw in enumerate(items):
        item = _mapping(raw, f"constraints[{index}]")
        _keys(item, {"id", "severity", "left", "operator", "right"}, allowed, f"constraints[{index}]")
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise _contract(f"constraints[{index}].id is invalid or duplicated")
        seen.add(identifier)
        if item["severity"] not in {"hard", "soft"}:
            raise _contract(f"constraints[{index}].severity is unsupported")
        if item["operator"] not in _OPERATORS:
            raise _contract(f"constraints[{index}].operator is unsupported")
        left = item["left"]
        if not isinstance(left, str) or left not in known_names:
            raise _contract(f"constraints[{index}].left is not a declared parameter")
        right = _mapping(item["right"], f"constraints[{index}].right")
        _keys(right, set(), {"value", "parameter"}, f"constraints[{index}].right")
        if set(right) != {"value"} and set(right) != {"parameter"}:
            raise _contract(f"constraints[{index}].right must contain value or parameter")
        if "value" in right:
            _finite_number(right["value"], f"constraints[{index}].right.value")
        else:
            target = right["parameter"]
            if not isinstance(target, str) or target not in known_names:
                raise _contract(f"constraints[{index}].right.parameter is not declared")


def _validate_mappings(value: object, known_names: set[str]) -> None:
    mappings = _mapping(value, "mappings")
    if len(mappings) > 1_000:
        raise _contract("mappings exceed the limit of 1000")
    allowed = {"parameter", "source_unit", "scale", "default", "null_policy"}
    for source, raw in mappings.items():
        if not isinstance(source, str) or not source.strip():
            raise _contract("mapping source names must be non-empty strings")
        item = _mapping(raw, f"mappings[{source!r}]")
        _keys(item, {"parameter"}, allowed, f"mappings[{source!r}]")
        target = item["parameter"]
        if not isinstance(target, str) or not target.strip():
            raise _contract(f"mappings[{source!r}].parameter must be a string")
        if target in _CORE_FIELDS:
            raise _contract(f"domain pack cannot override core field: {target}")
        if target not in known_names:
            raise _contract(f"mappings[{source!r}] targets undeclared parameter: {target}")
        if "scale" in item:
            _finite_number(item["scale"], f"mappings[{source!r}].scale")
        if "null_policy" in item and item["null_policy"] not in {"reject", "ignore", "default"}:
            raise _contract(f"mappings[{source!r}].null_policy is unsupported")


def _validate_requirement_mappings(value: object, known_names: set[str]) -> None:
    if value is None:
        return
    mappings = _mapping(value, "requirement_mappings")
    for source, raw in mappings.items():
        if not isinstance(source, str) or not source.strip():
            raise _contract("requirement mapping source names must be non-empty strings")
        if isinstance(raw, str):
            target = raw
            item: dict[str, Any] = {"parameter": target}
        else:
            item = _mapping(raw, f"requirement_mappings[{source!r}]")
            target = item.get("parameter")
        if not isinstance(target, str) or target not in known_names:
            raise _contract(f"requirement_mappings[{source!r}].parameter is not declared")
        _keys(
            item,
            {"parameter"},
            {"parameter", "unit", "aliases", "operator", "kind"},
            f"requirement_mappings[{source!r}]",
        )
        if "aliases" in item:
            aliases = _list(item["aliases"], f"requirement_mappings[{source!r}].aliases")
            if not all(isinstance(alias, str) and alias.strip() for alias in aliases):
                raise _contract(f"requirement_mappings[{source!r}].aliases must contain strings")
        if "unit" in item and (not isinstance(item["unit"], str) or not item["unit"].strip()):
            raise _contract(f"requirement_mappings[{source!r}].unit must be a string")
        if "operator" in item and item["operator"] not in {"==", "!=", "<", "<=", ">", ">="}:
            raise _contract(f"requirement_mappings[{source!r}].operator is unsupported")


def _validate_requirement_derivations(value: object, known_names: set[str]) -> None:
    if value is None:
        return
    derivations = _mapping(value, "requirement_derivations")
    for name, raw in derivations.items():
        if not isinstance(name, str) or name not in known_names:
            raise _contract(f"requirement_derivations target is not declared: {name}")
        formula = raw.get("formula") if isinstance(raw, dict) else raw
        _validate_formula(formula, f"requirement_derivations[{name!r}]")


def _validate_retrieval(value: object, known_names: set[str]) -> None:
    retrieval = _mapping(value, "retrieval")
    _keys(retrieval, {"features"}, {"features", "limit"}, "retrieval")
    features = _list(retrieval["features"], "retrieval.features")
    for index, raw in enumerate(features):
        item = _mapping(raw, f"retrieval.features[{index}]")
        _keys(item, {"parameter", "weight"}, {"parameter", "weight"}, f"retrieval.features[{index}]")
        if item["parameter"] not in known_names:
            raise _contract(f"retrieval.features[{index}].parameter is not declared")
        weight = _finite_number(item["weight"], f"retrieval.features[{index}].weight")
        if weight < 0:
            raise _contract(f"retrieval.features[{index}].weight must be non-negative")
    if "limit" in retrieval:
        limit = retrieval["limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise _contract("retrieval.limit must be an integer between 1 and 50")


def _validate_generation(value: object) -> None:
    generation = _mapping(value, "generation")
    allowed = {
        "candidate_count_min",
        "candidate_count_max",
        "max_attempts",
        "minimum_distance",
        "seed",
        "generator_version",
        "renderer",
        "timeout_seconds",
    }
    _keys(generation, set(), allowed, "generation")
    minimum = generation.get("candidate_count_min")
    maximum = generation.get("candidate_count_max")
    if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1):
        raise _contract("generation.candidate_count_min must be a positive integer")
    if maximum is not None and (isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1):
        raise _contract("generation.candidate_count_max must be a positive integer")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise _contract("generation.candidate_count_min must not exceed candidate_count_max")
    if "max_attempts" in generation:
        attempts = generation["max_attempts"]
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 10_000:
            raise _contract("generation.max_attempts must be between 1 and 10000")
    if "minimum_distance" in generation and _finite_number(generation["minimum_distance"], "generation.minimum_distance") < 0:
        raise _contract("generation.minimum_distance must be non-negative")
    if "seed" in generation and (isinstance(generation["seed"], bool) or not isinstance(generation["seed"], int)):
        raise _contract("generation.seed must be an integer")
    if "timeout_seconds" in generation:
        timeout = _finite_number(generation["timeout_seconds"], "generation.timeout_seconds")
        if timeout <= 0 or timeout > 3_600:
            raise _contract("generation.timeout_seconds must be between 0 and 3600")


def _validate_objectives(value: object, known_disciplines: set[str]) -> None:
    items = _list(value, "objectives")
    allowed = {"id", "discipline", "metric", "direction"}
    seen: set[str] = set()
    for index, raw in enumerate(items):
        item = _mapping(raw, f"objectives[{index}]")
        _keys(item, {"discipline", "metric", "direction"}, allowed, f"objectives[{index}]")
        identifier = item.get("id", f"{item['discipline']}.{item['metric']}")
        if not isinstance(identifier, str) or identifier in seen:
            raise _contract(f"objectives[{index}].id is invalid or duplicated")
        seen.add(identifier)
        if item["discipline"] not in known_disciplines:
            raise _contract(f"objectives[{index}].discipline is not declared")
        if not isinstance(item["metric"], str) or not item["metric"].strip():
            raise _contract(f"objectives[{index}].metric must be a string")
        if item["direction"] not in {"maximize", "minimize"}:
            raise _contract(f"objectives[{index}].direction is unsupported")


def _validate_disciplines(value: object) -> set[str]:
    items = _list(value, "disciplines")
    if len(items) > 20:
        raise _contract("disciplines exceed the limit of 20")
    allowed = {
        "id",
        "adapter",
        "adapter_version",
        "metrics",
        "input_parameters",
        "validity_domain",
        "validation_error",
        "maximum_error",
        "fallback_adapter",
        "source_kind",
        "surrogate",
    }
    seen: set[str] = set()
    for index, raw in enumerate(items):
        item = _mapping(raw, f"disciplines[{index}]")
        _keys(item, {"id", "adapter", "adapter_version"}, allowed, f"disciplines[{index}]")
        identifier = item["id"]
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise _contract(f"disciplines[{index}].id is invalid or duplicated")
        seen.add(identifier)
        for key in ("adapter", "adapter_version"):
            if not isinstance(item[key], str) or not item[key].strip():
                raise _contract(f"disciplines[{index}].{key} must be a string")
        for key in ("metrics", "input_parameters"):
            if key in item:
                values = _list(item[key], f"disciplines[{index}].{key}")
                if not all(isinstance(value, str) and value.strip() for value in values):
                    raise _contract(f"disciplines[{index}].{key} must contain strings")
        if "validation_error" in item:
            _finite_number(item["validation_error"], f"disciplines[{index}].validation_error")
        if "maximum_error" in item:
            _finite_number(item["maximum_error"], f"disciplines[{index}].maximum_error")
        if "validity_domain" in item:
            validity = _mapping(item["validity_domain"], f"disciplines[{index}].validity_domain")
            for parameter, bound in validity.items():
                if not isinstance(parameter, str):
                    raise _contract("validity_domain parameter names must be strings")
                bound_map = _mapping(bound, f"disciplines[{index}].validity_domain[{parameter!r}]")
                _keys(bound_map, {"minimum", "maximum"}, {"minimum", "maximum"}, "validity_domain bound")
                minimum = _finite_number(bound_map["minimum"], "validity_domain.minimum")
                maximum = _finite_number(bound_map["maximum"], "validity_domain.maximum")
                if minimum > maximum:
                    raise _contract("validity_domain minimum must not exceed maximum")
    return seen


def _ensure_finite_json(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise _contract("pack values must be finite")
    if isinstance(value, dict):
        for child in value.values():
            _ensure_finite_json(child)
    elif isinstance(value, list):
        for child in value:
            _ensure_finite_json(child)


def validate_domain_pack(payload: object) -> dict[str, Any]:
    """Return a canonical, validated copy of a declaration-only pack."""

    if not isinstance(payload, dict):
        raise _contract("pack must be an object")
    _ensure_finite_json(payload)
    _keys(payload, _REQUIRED, _ALLOWED, "domain pack")
    for key in ("id", "object_type", "id_prefix"):
        if not isinstance(payload[key], str) or not payload[key].strip():
            raise _contract(f"{key} must be a non-empty string")
    version = payload["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _contract("version must be a positive integer")
    if "schema_version" in payload:
        schema_version = payload["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
            raise _contract("schema_version must be a positive integer")
    parameter_names = _validate_parameters(payload["parameters"])
    derived_names = _validate_derived(payload["derived_parameters"], parameter_names)
    known_names = parameter_names | derived_names
    _validate_constraints(payload["constraints"], known_names)
    _validate_mappings(payload["mappings"], known_names)
    _validate_requirement_mappings(payload.get("requirement_mappings"), known_names)
    _validate_requirement_derivations(payload.get("requirement_derivations"), known_names)
    _validate_retrieval(payload["retrieval"], known_names)
    _validate_generation(payload["generation"])
    discipline_names = _validate_disciplines(payload["disciplines"])
    _validate_objectives(payload["objectives"], discipline_names)
    try:
        return json.loads(canonical_json(payload))
    except (TypeError, ValueError) as exc:
        raise _contract(f"pack contains unsupported JSON values: {exc}") from exc


def load_domain_pack(path: Path) -> dict[str, Any]:
    """Read and validate a domain pack from a UTF-8 JSON file."""

    candidate = Path(path)
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractViolation(f"domain pack not found: {candidate}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"domain pack is invalid JSON: {candidate}") from exc
    return validate_domain_pack(payload)


def domain_pack_hash(pack: dict[str, Any]) -> str:
    """Return the canonical content identity of a validated domain pack."""

    return canonical_hash(validate_domain_pack(pack))


__all__ = ["domain_pack_hash", "load_domain_pack", "validate_domain_pack"]
