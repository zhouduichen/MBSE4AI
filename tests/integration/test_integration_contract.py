from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/integration.yml")


def test_schedule_has_an_unconditional_contract_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in text
    assert "  contract:" in text
    contract = text.split("  contract:", 1)[1].split("  readiness:", 1)[0]
    # A step may use ``if: always()`` for artifact collection; the contract
    # job itself must remain unconditional so scheduled runs cannot skip it.
    assert "\n    if:" not in contract
    assert "tests/mbse_benchmark/run_benchmark.py" in contract
    assert "--track robustness" in contract
    assert "integration-contract-${{ github.run_id }}" in contract


def test_external_jobs_are_explicitly_labelled_and_do_not_use_offline_fallback() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "actions: read" in text
    assert "  readiness:" in text
    assert "no configured external target" in text
    assert "FreeCAD runner: label routing will be enforced by the target job" in text
    assert "GPU runner: label routing will be enforced by the target job" in text
    assert "runs-on: [self-hosted, macOS, X64, remote-bridge, freecad]" in text
    assert "runs-on: [self-hosted, macOS, X64, remote-bridge, gpu]" in text
    assert "runs-on: [self-hosted, macOS, X64, remote-bridge, llm]" in text
    assert "AI4MBSE_REMOTE_SSH_PRIVATE_KEY" in text
    assert "AI4MBSE_REMOTE_SSH_KNOWN_HOSTS" in text
    assert "AI4MBSE_LLM_PROFILE_JSON" in text
    assert "--compare-a-e" in text
    assert "run_llm:" in text
    assert "inputs.run_llm" in text
    assert "--path vertical" in text
    assert "--repeats 3" in text
    assert "AI4MBSE_LLM_CASE_TIMEOUT_SECONDS" in text
    assert "AI4MBSE_LLM_BENCHMARK_TOKEN_BUDGET" in text
    assert "--timeout '$AI4MBSE_LLM_CASE_TIMEOUT_SECONDS'" in text
    assert "--benchmark-token-budget '$AI4MBSE_LLM_BENCHMARK_TOKEN_BUDGET'" in text
    assert "case timeout must be at least the 900s provider timeout" in text
    assert "--comparison-mode natural" in text
    assert "integration-remote-llm-${{ github.run_id }}" in text
    assert "tests/mbse_benchmark/results/integration-remote" in text
    assert "benchmark_rc=$?" in text
    assert "benchmark exit code" in text
    assert "AI4MBSE_CAD_BACKEND: freecad-remote" in text
    assert "refusing to claim a GPU acceptance PASS" in text
    assert "tests/integration/test_gpu_acceptance.py" in text
    assert "AI4MBSE_GPU_ACCEPTANCE" in text
