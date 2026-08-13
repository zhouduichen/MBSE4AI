from copy import deepcopy

from rflp_lite.application.intelligence.normalization import normalize_candidate_sets


def candidate(identifier, content_hash, name, category="medical", status="candidate"):
    return {
        "id": identifier,
        "element_type": "stakeholder",
        "content_hash": content_hash,
        "status": status,
        "payload": {"name": name, "category": category, "goals": ["目标"], "interactions": ["交互"]},
        "provenance": [],
    }


def test_exact_duplicates_merge_but_near_duplicates_only_suggest():
    state = {
        "discovery": {
            "candidate_sets": [
                {"lens_id": "a", "items": [candidate("c1", "same", "急救医生")]},
                {"lens_id": "b", "items": [candidate("c2", "same", "急救医生"), candidate("c3", "different", " 急救医生 ")]},
            ],
            "diagnostics": [],
            "revision": 1,
        }
    }
    source = deepcopy(state)
    result = normalize_candidate_sets(state)
    items = [item for group in result["discovery"]["candidate_sets"] for item in group["items"]]
    assert len([item for item in items if item["content_hash"] == "same"]) == 1
    assert result["discovery"]["merge_suggestions"] == [{"left_id": "c1", "right_id": "c3", "reason": "normalized-name-match"}]
    assert state == source


def test_same_type_and_name_with_different_payload_is_a_conflict():
    state = {
        "discovery": {
            "candidate_sets": [{"lens_id": "a", "items": [candidate("c1", "h1", "监管机构", "regulatory"), candidate("c2", "h2", "监管机构", "operations")]}],
            "diagnostics": [],
            "revision": 1,
        }
    }
    result = normalize_candidate_sets(state)
    assert any(item["code"] == "candidate_conflict" for item in result["discovery"]["diagnostics"])
