import pytest

from rflp_lite.application.intelligence.pack_composition import (
    compose_pack_selection,
    normalize_pack_selection,
    pack_selection_hash,
)
from rflp_lite.domain.errors import ContractViolation


def test_missing_selection_defaults_to_common_pack():
    assert normalize_pack_selection(None)["base_pack_id"] == "common-v1"
    assert normalize_pack_selection(None)["industry_pack_ids"] == []
    assert normalize_pack_selection(None)["discipline_pack_ids"] == []
    assert normalize_pack_selection(None)["overlay_pack_ids"] == []


def test_composition_keeps_selection_order_and_hash():
    result = compose_pack_selection(
        {
            "base_pack_id": "common-v1",
            "overlay_pack_ids": ["urban-medical-aam-v1"],
        }
    )

    assert result["pack_ids"] == ["common-v1", "urban-medical-aam-v1"]
    assert result["pack_hashes"]
    assert result["pack_selection_hash"] == pack_selection_hash(result["selection"])


def test_selection_rejects_duplicate_ids_across_categories():
    with pytest.raises(ContractViolation, match="重复"):
        normalize_pack_selection(
            {
                "industry_pack_ids": ["urban-medical-aam-v1"],
                "overlay_pack_ids": ["urban-medical-aam-v1"],
            }
        )


def test_selection_rejects_path_traversal():
    with pytest.raises(ContractViolation, match="非法"):
        normalize_pack_selection({"overlay_pack_ids": ["../common-v1"]})
