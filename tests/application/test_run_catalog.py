from pathlib import Path

import pytest

from rflp_lite.application.demo import run_demo
from rflp_lite.application.run_catalog import list_runs, load_run, registered_output
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.profile import Profile


def test_catalog_loads_latest_run_and_confines_downloads(tmp_path: Path) -> None:
    result = run_demo(tmp_path, Profile())
    records = list_runs(tmp_path)
    assert records[0].result_hash == result.result_hash
    assert load_run(tmp_path, result.result_hash) == records[0]
    assert registered_output(records[0], "evidence.json").is_file()
    with pytest.raises(ContractViolation):
        registered_output(records[0], "../../profile.json")


def test_catalog_rejects_invalid_hash(tmp_path: Path) -> None:
    with pytest.raises(ContractViolation, match="invalid result hash"):
        load_run(tmp_path, "not-a-hash")
