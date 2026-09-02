from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.adapters.disciplines import discipline_registry
from rflp_lite.adapters.scheme_sources import read_scheme_rows
from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.concept_design_service import run_concept_design
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.scheme_library import import_scheme_rows


ROOT = Path("src/rflp_lite/resources/examples/concept-design")
PACK = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def test_concept_run_links_envelope_candidates_evaluations_and_optimization(tmp_path):
    pack = load_domain_pack(PACK)
    schemes = import_scheme_rows(
        pack,
        read_scheme_rows("fixed-wing-schemes.json", (ROOT / "fixed-wing-schemes.json").read_bytes()),
        "fixture",
    ).records
    envelope_payload = json.loads((ROOT / "fixed-wing-envelope.json").read_text())
    repository = SQLiteRepository(tmp_path / "model.db")
    try:
        result = run_concept_design(
            pack,
            {"id": "development-v1", "version": 1},
            envelope_payload,
            schemes,
            discipline_registry(),
            repository,
            optimize=True,
        )
        assert len(result.candidates) >= 5
        assert len(result.evaluations) == len(result.candidates) * 3
        assert result.optimization.front_candidate_ids
        assert result.optimization.iteration_records
        assert len(result.optimization.candidate_ids) > 5
        assert any(
            candidate.reference_ids
            and candidate.reference_ids[0] in {
                item.id for item in result.candidates[:5]
            }
            for candidate in result.candidates[5:]
        )
        assert all(item.envelope_id == result.envelope.id for item in result.candidates)
        assert result.trace_links
        assert result.formal_status == "development"
        assert repository.concept_runs()
    finally:
        repository.close()
