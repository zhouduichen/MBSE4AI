from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.domain.errors import ContractViolation


def validate_json(instance: object, schema_path: Path) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ContractViolation("jsonschema extra is required for validation") from exc
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "$"
        raise ContractViolation(
            f"{schema_path.name} validation failed at {location}: {exc.message}"
        ) from exc

