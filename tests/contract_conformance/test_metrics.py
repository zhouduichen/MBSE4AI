import json

from tests.contract_conformance.runner import METRIC_NAMES, SampleResult, run_conformance, summarize


def test_metrics_are_computed_from_stage_results():
    samples = [
        SampleResult(json_parsed=True, schema_passed=True, compiled=True, domain_valid=True, structural_retries=0),
        SampleResult(json_parsed=True, schema_passed=False, compiled=False, domain_valid=False, structural_retries=1),
    ]

    assert summarize(samples) == {
        "provider_success_rate": 0.0,
        "json_parse_rate": 1.0,
        "schema_pass_rate": 0.5,
        "proposal_compile_rate": 0.5,
        "domain_validation_rate": 0.5,
        "first_pass_success_rate": 0.0,
        "structural_retry_rate": 0.5,
        "retry_recovery_rate": 0.0,
        "semantic_rejection_rate": 0.0,
        "blocked_count": 0.0,
        "mean_output_tokens": 0.0,
        "mean_latency_ms": 0.0,
    }


def test_blocked_samples_are_reported_separately_from_executed_funnel():
    samples = [
        SampleResult(
            provider_success=True,
            status="completed",
            json_parsed=True,
            schema_passed=True,
            compiled=True,
            domain_valid=True,
        ),
        SampleResult(status="blocked", blocked=True, failure_stage="structural"),
    ]

    metrics = summarize(samples)

    assert metrics["blocked_count"] == 1.0
    assert metrics["proposal_compile_rate"] == 0.5
    assert metrics["semantic_rejection_rate"] == 0.0


def test_non_live_conformance_smoke_writes_all_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("PR09_ARTIFACT_ROOT", str(tmp_path))

    result = run_conformance(repetitions=1, live=False)

    assert result["sample_count"] == 3
    assert set(result["metrics"]) == set(METRIC_NAMES)
    report = json.loads((tmp_path / result["result_path"].split("/")[-1]).read_text())
    assert report["sample_count"] == 3
    assert report["tasks"] == ["system_definition", "stakeholder_requirements", "function_identification"]
    assert all(sample["schema_hash"] for sample in report["samples"])
    assert all(sample["prompt_hash"] for sample in report["samples"])
    assert report["status_counts"] == {"completed": 3}
    assert report["metrics"]["blocked_count"] == 0.0
