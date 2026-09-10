import json

from tests.contract_conformance.runner import SampleResult, run_conformance, summarize


def test_metrics_are_computed_from_stage_results():
    samples = [
        SampleResult(json_parsed=True, schema_passed=True, compiled=True, domain_valid=True, structural_retries=0),
        SampleResult(json_parsed=True, schema_passed=False, compiled=False, domain_valid=False, structural_retries=1),
    ]

    assert summarize(samples) == {
        "json_parse_rate": 1.0,
        "schema_pass_rate": 0.5,
        "proposal_compile_rate": 0.5,
        "domain_validation_rate": 0.5,
        "first_pass_success_rate": 0.5,
        "structural_retry_rate": 0.5,
    }


def test_non_live_conformance_smoke_writes_all_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("PR09_ARTIFACT_ROOT", str(tmp_path))

    result = run_conformance(repetitions=1, live=False)

    assert result["sample_count"] == 3
    assert set(result["metrics"]) == {
        "json_parse_rate", "schema_pass_rate", "proposal_compile_rate",
        "domain_validation_rate", "first_pass_success_rate", "structural_retry_rate",
    }
    report = json.loads((tmp_path / result["result_path"].split("/")[-1]).read_text())
    assert report["sample_count"] == 3
    assert report["tasks"] == ["system_definition", "stakeholder_requirements", "function_identification"]
