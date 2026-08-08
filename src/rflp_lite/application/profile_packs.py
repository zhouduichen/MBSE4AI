from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from rflp_lite.application.run_catalog import RunRecord
from rflp_lite.application.resources import resource_path
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.profile import Profile
from rflp_lite.governance.validation import validate_json


PROFILE_SCHEMA = resource_path("schemas/profile.schema.json")


def validate_profile_payload(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ContractViolation("profile must be a JSON object")
    validate_json(payload, PROFILE_SCHEMA)
    try:
        profile = Profile(**payload)
    except (TypeError, ValueError) as exc:
        raise ContractViolation(f"invalid profile: {exc}") from exc
    return profile.as_dict()


def load_profile(workspace: Path) -> dict[str, object]:
    path = workspace / "profile.json"
    if not path.is_file():
        raise ContractViolation("profile.json not found")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractViolation(f"profile.json is invalid JSON: {exc.msg}") from exc
    return validate_profile_payload(payload)


def save_profile(workspace: Path, payload: object) -> dict[str, object]:
    normalized = validate_profile_payload(payload)
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / "profile.json"
    handle, temporary = tempfile.mkstemp(prefix="profile-", suffix=".json", dir=workspace)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(canonical_json(normalized))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return normalized


def export_run_record(record: RunRecord) -> dict[str, object]:
    return {
        "schema_version": 1,
        "format": "rflp-lite-run",
        "result_hash": record.result_hash,
        "manifest": record.manifest,
        "outputs": record.outputs,
    }
