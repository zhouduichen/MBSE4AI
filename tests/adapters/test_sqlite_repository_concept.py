from pathlib import Path

import pytest

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.domain.errors import ContractViolation


PACK_PATH = Path("src/rflp_lite/resources/domain-packs/fixed-wing-v1.json")


def test_domain_pack_revision_is_immutable_and_payload_records_round_trip(tmp_path):
    repository = SQLiteRepository(tmp_path / "model.db")
    pack = load_domain_pack(PACK_PATH)
    repository.save_domain_pack(pack)
    assert repository.domain_packs()[0]["content_hash"]

    changed = {**pack, "id_prefix": "ALT"}
    with pytest.raises(ContractViolation, match="version"):
        repository.save_domain_pack(changed)

    record = {"id": "FW-S-1", "parameters": {"mass_kg": 120.0}}
    repository.save_scheme_records((record,))
    assert repository.scheme_records() == (record,)
    assert repository.load_scheme_record("FW-S-1") == record


def test_concept_payload_tables_are_available(tmp_path):
    repository = SQLiteRepository(tmp_path / "model.db")
    candidate = {"id": "FW-C-1", "feasible": True}
    evaluation = {"id": "eval-1", "cache_key": "cache-1", "status": "succeeded"}
    run = {"id": "run-1", "candidate_ids": [candidate["id"]]}
    repository.save_layout_candidates((candidate,))
    repository.save_discipline_evaluations((evaluation,))
    repository.save_optimization_runs((run,))
    assert repository.layout_candidates() == (candidate,)
    assert repository.discipline_evaluations() == (evaluation,)
    assert repository.load_discipline_evaluation("cache-1") == evaluation
    assert repository.optimization_runs() == (run,)
