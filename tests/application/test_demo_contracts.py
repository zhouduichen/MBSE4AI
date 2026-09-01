import json
from pathlib import Path

from rflp_lite.application.domain_packs import load_domain_pack


RESOURCE_ROOT = Path("src/rflp_lite/resources")


def test_fixed_wing_pack_declares_candidate_generation_and_three_disciplines():
    pack = load_domain_pack(RESOURCE_ROOT / "domain-packs/fixed-wing-v1.json")
    assert pack["generation"]["candidate_count_min"] == 3
    assert pack["generation"]["candidate_count_max"] == 5
    assert {item["id"] for item in pack["disciplines"]} == {
        "aerodynamics", "structures", "weight_balance"
    }


def test_demo_envelope_has_explicit_source_requirement_ids():
    payload = json.loads(
        (RESOURCE_ROOT / "examples/concept-design/fixed-wing-envelope.json")
        .read_text(encoding="utf-8")
    )
    assert payload["source_requirement_ids"]
    assert payload["bounds"]["span_m"] == {"minimum": 11, "maximum": 16}
