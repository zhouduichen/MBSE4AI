import json

from rflp_lite.interface.cli import main


def test_cli_demo_is_reproducible(tmp_path, capsys):
    first = main(["demo", "--workspace", str(tmp_path / "one"), "--seed", "42"])
    first_output = json.loads(capsys.readouterr().out)
    second = main(["demo", "--workspace", str(tmp_path / "two"), "--seed", "42"])
    second_output = json.loads(capsys.readouterr().out)
    assert first == second == 0
    assert first_output["result_hash"] == second_output["result_hash"]
    assert first_output["baseline_hash"] == second_output["baseline_hash"]
    assert first_output["candidate_count"] >= 2
    assert first_output["task_count"] >= 1
    assert first_output["evidence_count"] >= 1


def test_cli_init_writes_valid_profile(tmp_path, capsys):
    assert main(["init", str(tmp_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "initialized"
    assert (tmp_path / "profile.json").is_file()

