"""Load declaration-only MBSE domain packs from packaged resources.

The optional ``jsonschema`` dependency is deliberately imported only while a
pack is being validated.  Consumers can therefore import this module in a
minimal installation and opt out of validation with ``validate=False``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rflp_lite.application.resources import resource_path
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


PACK_SCHEMA = resource_path("schemas/mbse-domain-pack.schema.json")
PACK_DIRECTORY = resource_path("domain-packs")


def list_domain_packs() -> list[str]:
    """Return packaged JSON domain-pack IDs in deterministic order."""

    if not PACK_DIRECTORY.is_dir():
        return []
    return sorted(
        path.stem
        for path in PACK_DIRECTORY.iterdir()
        if path.is_file() and path.suffix == ".json"
    )


def _clean_pack_id(pack_id: str) -> str:
    if not isinstance(pack_id, str):
        raise ContractViolation("MBSE domain pack ID must be a string")
    clean_id = pack_id.strip()
    if clean_id.endswith(".json"):
        clean_id = clean_id[:-5]
    if (
        not clean_id
        or clean_id in {".", ".."}
        or clean_id != Path(clean_id).name
        or "/" in clean_id
        or "\\" in clean_id
        or "\x00" in clean_id
    ):
        raise ContractViolation("invalid MBSE domain pack ID")
    return clean_id


def _pack_path(pack_id: str) -> Path:
    """Resolve a resource pack without allowing a path escape."""

    clean_id = _clean_pack_id(pack_id)
    root = PACK_DIRECTORY.resolve()
    path = (root / f"{clean_id}.json").resolve()
    if path.parent != root or not path.is_file():
        raise ContractViolation(f"MBSE domain pack not found: {clean_id}")
    return path


def _read_pack(path: Path) -> dict[str, object]:
    candidate = Path(path)
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractViolation(
            f"invalid MBSE domain pack: {candidate.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise ContractViolation("MBSE domain pack must be a JSON object")
    return payload


def _validate_pack(payload: dict[str, object], *, path: Path) -> None:
    """Validate an MBSE pack, or the legacy layout pack in the same directory."""

    if "object_type" in payload and "parameters" in payload:
        # The resource directory also contains the older concept-design pack.
        # Keep this loader backwards-compatible without importing optional
        # validation dependencies at module import time.
        from rflp_lite.application.domain_packs import validate_domain_pack

        validate_domain_pack(payload)
        return

    try:
        from rflp_lite.governance.validation import validate_json

        validate_json(payload, PACK_SCHEMA)
    except FileNotFoundError as exc:
        raise ContractViolation(
            f"MBSE domain-pack schema not found: {PACK_SCHEMA}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ContractViolation(
            f"invalid MBSE domain-pack schema: {PACK_SCHEMA.name}"
        ) from exc
    except ContractViolation:
        raise
    except OSError as exc:
        raise ContractViolation(
            f"unable to read MBSE domain-pack schema: {PACK_SCHEMA.name}"
        ) from exc


def _load_domain_pack(path: Path, *, validate: bool = True) -> dict[str, object]:
    """Read one pack from disk and return a canonical object representation."""

    candidate = Path(path)
    payload = _read_pack(candidate)
    if payload.get("core_overrides"):
        raise ContractViolation("MBSE domain pack cannot define core_overrides")
    if validate:
        _validate_pack(payload, path=candidate)
    return json.loads(canonical_json(payload))


def load_domain_pack(pack_id: str, validate: bool = True) -> dict[str, object]:
    """Load ``<pack_id>.json`` from the packaged domain-pack directory."""

    return _load_domain_pack(_pack_path(pack_id), validate=validate)


def load_mbse_domain_pack(path: Path, validate: bool = True) -> dict[str, object]:
    """Load and validate an MBSE pack from an explicit path."""

    return _load_domain_pack(Path(path), validate=validate)


def mbse_domain_pack_hash(pack: object) -> str:
    """Return the deterministic content hash of a domain pack."""

    return canonical_hash(pack)


def validate_candidate_payload(
    pack: dict[str, object], element_type: str, payload: object
) -> dict[str, object]:
    """Validate and canonically normalize one domain element payload."""

    schemas = pack.get("element_schemas", {})
    if not isinstance(schemas, dict) or element_type not in schemas:
        raise ContractViolation(f"unsupported element type: {element_type}")
    if not isinstance(payload, dict):
        raise ContractViolation(f"{element_type} payload must be an object")
    schema = schemas[element_type]
    if not isinstance(schema, dict):
        raise ContractViolation(f"{element_type} schema must be an object")
    try:
        import jsonschema
    except ImportError as exc:
        raise ContractViolation(
            "jsonschema extra is required for MBSE discovery"
        ) from exc
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "$"
        raise ContractViolation(
            f"{element_type} payload validation failed at {location}: {exc.message}"
        ) from exc
    except jsonschema.SchemaError as exc:
        raise ContractViolation(f"{element_type} schema is invalid") from exc
    return json.loads(canonical_json(payload))
