from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from rflp_lite.adapters.scheme_sources import read_scheme_rows
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.layout_generation import candidate_distance, generate_layout_candidates
from rflp_lite.application.parameter_rules import create_indicator_envelope
from rflp_lite.application.scheme_library import import_scheme_rows
from rflp_lite.application.scheme_retrieval import find_similar_schemes


ROOT = Path("src/rflp_lite/resources/examples/concept-design")
PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def _inputs():
    pack = load_domain_pack(PACK)
    rows = read_scheme_rows("fixed-wing-schemes.json", (ROOT / "fixed-wing-schemes.json").read_bytes())
    schemes = import_scheme_rows(pack, rows, "fixture").records
    payload = json.loads((ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))
    envelope = create_indicator_envelope(pack, payload, ())
    matches = find_similar_schemes(pack, envelope, schemes)
    return pack, envelope, schemes, matches


def test_generator_returns_three_to_five_feasible_diverse_candidates():
    pack, envelope, schemes, matches = _inputs()
    candidates = generate_layout_candidates(pack, envelope, schemes, matches)
    assert 3 <= len(candidates) <= 5
    assert all(item.feasible and item.status == "feasible" for item in candidates)
    assert all(
        all(result.passed for result in item.constraints if result.severity == "hard")
        for item in candidates
    )
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            assert candidate_distance(pack, left, right) >= 0.08


def test_same_inputs_and_seed_have_same_result_hashes_and_svg():
    args = _inputs()
    first = generate_layout_candidates(*args, seed=42)
    second = generate_layout_candidates(*args, seed=42)
    assert [item.result_hash for item in first] == [item.result_hash for item in second]
    assert [item.svg for item in first] == [item.svg for item in second]


def test_generator_does_not_fill_shortfall_with_infeasible_items():
    pack, envelope, schemes, _matches = _inputs()
    impossible_payload = {
        "parameters": {
            **dict(envelope.parameters),
            "wing_area_m2": 90,
            "span_m": 5,
            "cg_x_m": 1.0,
        }
    }
    impossible = create_indicator_envelope(pack, impossible_payload, ())
    assert generate_layout_candidates(pack, impossible, schemes, (), seed=42) == ()


def test_generator_requires_reference_matches():
    pack, envelope, schemes, _matches = _inputs()
    assert generate_layout_candidates(pack, envelope, schemes, (), seed=42) == ()


def test_candidate_id_and_hash_change_with_seed():
    pack, envelope, schemes, matches = _inputs()
    first = generate_layout_candidates(pack, envelope, schemes, matches, seed=1)
    second = generate_layout_candidates(pack, envelope, schemes, matches, seed=2)
    assert first and second
    assert first[0].id != second[0].id
    assert first[0].result_hash != second[0].result_hash


def test_envelope_bounds_are_hard_and_traceable():
    pack, envelope, schemes, matches = _inputs()
    bounded = replace(envelope, bounds=(("span_m", 13.0, 13.0),))
    assert generate_layout_candidates(pack, bounded, schemes, matches, seed=42) == ()

