from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from rflp_lite.application.layout_generation import generate_layout_candidates
from rflp_lite.application.layout_render import render_layout_svg
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.parameter_rules import create_indicator_envelope
from rflp_lite.application.scheme_library import import_scheme_rows
from rflp_lite.application.scheme_retrieval import find_similar_schemes
from rflp_lite.adapters.scheme_sources import read_scheme_rows
from rflp_lite.domain.errors import ContractViolation


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


def test_fixed_wing_svg_is_deterministic_and_contains_geometry():
    pack, envelope, schemes, matches = _inputs()
    candidate = generate_layout_candidates(pack, envelope, schemes, matches, seed=42)[0]
    first = render_layout_svg(pack, candidate)
    second = render_layout_svg(pack, candidate)
    assert first == second == candidate.svg
    assert first.startswith("<svg ")
    assert 'viewBox="0 0 1000 520"' in first
    assert "Top view" in first and "Side view" in first
    assert "chord=" in first


def test_fixed_wing_svg_escapes_candidate_label():
    pack, envelope, schemes, matches = _inputs()
    candidate = generate_layout_candidates(pack, envelope, schemes, matches, seed=42)[0]
    escaped = render_layout_svg(pack, replace(candidate, id='candidate<&"'))
    assert "candidate&lt;&amp;&quot;" in escaped


def test_unknown_renderer_is_rejected():
    pack, envelope, schemes, matches = _inputs()
    candidate = generate_layout_candidates(pack, envelope, schemes, matches, seed=42)[0]
    invalid_pack = {**pack, "generation": {**pack["generation"], "renderer": "other"}}
    with pytest.raises(ContractViolation, match="renderer"):
        render_layout_svg(invalid_pack, candidate)
