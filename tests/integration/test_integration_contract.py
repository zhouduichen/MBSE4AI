from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/integration.yml")


def test_schedule_has_an_unconditional_contract_job() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "schedule:" in text
    assert "  contract:" in text
    contract = text.split("  contract:", 1)[1].split("  remote-llm:", 1)[0]
    assert "if:" not in contract
    assert "tests/mbse_benchmark/run_benchmark.py --track robustness" in contract


def test_external_jobs_are_explicitly_labelled_and_do_not_use_offline_fallback() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "runs-on: [self-hosted, linux, freecad]" in text
    assert "runs-on: [self-hosted, linux, gpu]" in text
    assert "AI4MBSE_LLM_PROFILE_JSON" in text
    assert "AI4MBSE_CAD_BACKEND: freecad-remote" in text
    assert "refusing to claim a GPU acceptance PASS" in text
