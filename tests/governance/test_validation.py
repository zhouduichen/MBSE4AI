import json

import pytest

from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.validation import validate_json


def test_profile_schema_accepts_default_profile():
    value = json.loads(open("examples/profile.json", encoding="utf-8").read())
    validate_json(value, __import__("pathlib").Path("schemas/profile.schema.json"))


def test_profile_schema_rejects_negative_timeout():
    value = {
        "name": "bad",
        "solver": "heuristic",
        "seed": 42,
        "candidate_limit": 3,
        "timeout_seconds": -1,
    }
    with pytest.raises(ContractViolation, match="timeout_seconds"):
        validate_json(value, __import__("pathlib").Path("schemas/profile.schema.json"))

