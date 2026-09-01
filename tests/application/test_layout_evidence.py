import json
from pathlib import Path

from rflp_lite.application.concept_acceptance import _MemoryStore
from rflp_lite.application.concept_design_service import run_concept_design
from rflp_lite.application.dependencies import configured_dependencies
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.layout_evidence import build_layout_manifest
from rflp_lite.application.scheme_library import import_scheme_rows
from rflp_lite.domain.canonical import canonical_hash


ROOT = Path("src/rflp_lite/resources/examples/concept-design")


def _run():
    deps = configured_dependencies()
    pack = load_domain_pack(Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json"))
    rows = deps.scheme_reader("fixed-wing-schemes.json", (ROOT / "fixed-wing-schemes.json").read_bytes())
    imported = import_scheme_rows(pack, rows, str(ROOT / "fixed-wing-schemes.json"))
    profile = json.loads((ROOT / "development-evaluator-profile.json").read_text(encoding="utf-8"))
    envelope = json.loads((ROOT / "fixed-wing-envelope.json").read_text(encoding="utf-8"))
    return pack, run_concept_design(pack, profile, envelope, imported.records, deps.discipline_registry(), _MemoryStore(), optimize=False)


def test_layout_manifest_declares_conceptual_svg_and_hashes():
    pack, result = _run()
    manifest = build_layout_manifest(pack, result.candidates[0], result.candidates)
    assert manifest["representation_kind"] == "conceptual_2d_svg"
    assert manifest["views"] == ["top", "side"]
    assert manifest["candidate_id"] == result.candidates[0].id
    assert manifest["svg_hash"]
    assert manifest["manifest_hash"] == canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})


def test_layout_manifest_reports_pairwise_distance_and_constraint_margins():
    pack, result = _run()
    manifest = build_layout_manifest(pack, result.candidates[0], result.candidates)
    assert manifest["minimum_pairwise_distance"] >= 0.08
    assert manifest["hard_constraint_margins"]
    assert manifest["reference_scheme_ids"]
