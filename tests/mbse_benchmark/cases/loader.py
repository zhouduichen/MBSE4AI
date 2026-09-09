"""Load benchmark inputs and reference expectations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def validate_case(value: Mapping[str, object], *, path: Path | None = None) -> dict[str, Any]:
    prefix = f" in {path}" if path else ""
    case = dict(value)
    case_id = str(case.get("case_id", "")).strip()
    system = str(case.get("system", "")).strip()
    if not case_id:
        raise ValueError(f"case_id is required{prefix}")
    if not system:
        raise ValueError(f"system is required{prefix}")
    for field in ("stakeholders", "lifecycle_stages", "scenarios", "requirements"):
        if not isinstance(case.get(field), list):
            raise ValueError(f"{field} must be an array{prefix}")
    for index, requirement in enumerate(case["requirements"]):
        if not isinstance(requirement, dict):
            raise ValueError(f"requirements[{index}] must be an object{prefix}")
        if not str(requirement.get("id", "")).strip():
            raise ValueError(f"requirements[{index}].id is required{prefix}")
        if not str(requirement.get("statement", "")).strip():
            raise ValueError(f"requirements[{index}].statement is required{prefix}")
    if "physical_design" in case and not isinstance(case["physical_design"], list):
        raise ValueError(f"physical_design must be an array{prefix}")
    return case


def load_case(path: Path) -> dict[str, Any]:
    return validate_case(load_json_object(path), path=path)


def load_cases(cases_dir: Path) -> tuple[dict[str, Any], ...]:
    cases = tuple(load_case(path) for path in sorted(cases_dir.glob("case_*.json")))
    if len(cases) != 5:
        raise ValueError(f"expected five benchmark cases, found {len(cases)}")
    ids = [str(case["case_id"]) for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("benchmark case IDs must be unique")
    return cases


def load_expectations(expected_dir: Path) -> dict[str, Any]:
    return {
        "coverage": load_json_object(expected_dir / "coverage_expectations.json"),
        "metric_targets": load_json_object(expected_dir / "metric_targets.json"),
        "known_conflicts": load_json_object(expected_dir / "known_conflicts.json"),
    }
