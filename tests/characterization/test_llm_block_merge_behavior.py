import pytest

from rflp_lite.application.intelligence.block_schemas import BLOCK_SCHEMA_VERSION, schema_for
from rflp_lite.application.intelligence.validated_result import parse_block_dto


@pytest.mark.parametrize(
    "block_id",
    ("system_scope", "stakeholders", "concerns_needs", "requirements", "scenarios", "architecture"),
)
def test_all_llm_blocks_have_versioned_strict_schemas(block_id: str) -> None:
    schema = schema_for(block_id)
    assert schema["additionalProperties"] is False
    payload = {"schema_version": BLOCK_SCHEMA_VERSION, "items": [], "diagnostics": []}
    parsed = parse_block_dto(block_id, payload)
    assert parsed.block_id == block_id
