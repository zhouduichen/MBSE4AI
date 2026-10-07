# MBSE4AI v0.3.2 Evidence Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every A–E comparison self-consistent and fail closed when raw artifacts, evaluator-boundary metadata, or report provenance is missing.

**Architecture:** Keep the existing `ScenarioContract -> BenchmarkInputEnvelope -> ScenarioRunner -> ModelGraphNormalizer -> ExternalEvaluator -> ReportBuilder` pipeline. Add the missing evidence controls at the benchmark boundary: reject a reused comparison output root before model calls, persist evaluator-only boundary metadata even for failed calls, and derive report-level hashes from repeat metadata when a runtime ledger is empty. Do not change CAD, MDO, Harness generation, or evaluator scoring behavior.

**Tech Stack:** Python 3.12, pytest, canonical JSON/hash helpers, `pathlib`, GitHub Actions, Ruff, import-linter.

## Global Constraints

- A–E must use byte-identical canonical `BenchmarkInputEnvelope` artifacts and one `ExternalEvaluator`.
- `EvaluationSpec` and expected graphs remain evaluator-only; failed calls must not be treated as successful evaluations.
- A/B model output remains `CANDIDATE`/`LLM` after normalization; self-declared `ACCEPTED`, `LOCKED`, or `USER` authority is audit data only.
- Technical Closure accepts `VALIDATED` or stronger; Release Closure accepts only `ACCEPTED` or `LOCKED`; empty scopes are not passing coverage.
- Natural mode and budget-matched mode remain explicit; unknown cost remains `cost_status=unavailable`, never fabricated zero cost.
- Do not merge to `main` without a real `CI / quality` check and the existing branch-protection review requirement.

---

### Task 1: Reject stale or reused A–E evidence roots before execution

**Files:**
- Modify: `tests/mbse_benchmark/runners/benchmark_runner.py` in `run_scenario_comparison`
- Modify: `tests/mbse_benchmark/run_benchmark.py` CLI argument handling
- Test: `tests/mbse_benchmark/test_comparison.py`

**Interfaces:**
- Add `_assert_fresh_comparison_root(output_root: Path) -> None`.
- It raises `ValueError("A–E comparison output root must be empty")` when the root contains any file or any non-empty scenario/repeat directory.
- An empty, newly-created root remains valid; no provider call may occur before this check.

- [ ] **Step 1: Write the failing test**

```python
def test_comparison_rejects_reused_output_root_before_model_calls(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    output_root.mkdir()
    (output_root / "old-report.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="output root must be empty"):
        benchmark_runner_module.run_scenario_comparison(
            Path("tests/mbse_benchmark/cases"),
            output_root,
            repeats=3,
            report_dir=tmp_path / "report",
            profile="test-profile",
            runtime_config={"model": "test-model", "provider": "test"},
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -q tests/mbse_benchmark/test_comparison.py::test_comparison_rejects_reused_output_root_before_model_calls`

Expected: FAIL because the current runner accepts a non-empty comparison root.

- [ ] **Step 3: Write the minimal implementation**

```python
def _assert_fresh_comparison_root(output_root: Path) -> None:
    if not output_root.exists():
        return
    if any(output_root.iterdir()):
        raise ValueError("A–E comparison output root must be empty")


def run_scenario_comparison(...):
    _assert_fresh_comparison_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    ...
```

Call the helper before constructing the shared evaluator or invoking `run_benchmark`. Keep single-scenario runs backward-compatible; the guard applies only to `--compare-a-e`.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -q tests/mbse_benchmark/test_comparison.py::test_comparison_rejects_reused_output_root_before_model_calls`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/mbse_benchmark/runners/benchmark_runner.py tests/mbse_benchmark/test_comparison.py
git commit -m "test: reject stale A-E comparison roots"
```

### Task 2: Preserve evaluator-boundary metadata on failed repeats

**Files:**
- Modify: `tests/mbse_benchmark/runners/case_runner.py` in `_failure_metadata`, `_child_entry`, and `run_case`
- Modify: `tests/mbse_benchmark/runners/benchmark_runner.py` at the `run_case` call site
- Test: `tests/mbse_benchmark/test_case_runner.py`

**Interfaces:**
- Extend the child execution arguments with `evaluation_spec_hash: str`, `evaluator_id: str`, and `request_guard_hash: str`.
- `_failure_metadata(...)` writes `evaluation_owner`, `evaluator_id`, `evaluation_spec_hash`, `ground_truth_model_visible=False`, and an `evaluation_boundary` object with `model_visible=False`, `ground_truth_payload_transmitted=False`, and `guard_enforced=True`.
- The existing failure status, exception type, and telemetry remain unchanged.

- [ ] **Step 1: Write the failing test**

Add a failure-path assertion using a fake provider that raises after emitting telemetry:

```python
def test_failed_repeat_retains_external_evaluator_boundary(tmp_path: Path) -> None:
    metadata = case_runner_module._failure_metadata(
        BenchmarkInputEnvelope.from_case(CASE),
        scenario_contract(BenchmarkScenario.D_HARNESS_NO_REPAIR),
        {"model": "m", "provider": "p", "benchmark_token_budget": 8192},
        telemetry_events=[],
        comparison_mode="natural",
        total_output_token_budget=None,
        execution_elapsed=1.0,
        evaluation_spec_hash="eval-hash",
        evaluator_id=EXTERNAL_EVALUATOR_ID,
        request_guard_hash="guard-hash",
    )

    assert metadata["evaluation_owner"] == EXTERNAL_EVALUATOR_ID
    assert metadata["evaluation_spec_hash"] == "eval-hash"
    assert metadata["ground_truth_model_visible"] is False
    assert metadata["evaluation_boundary"]["guard_enforced"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -q tests/mbse_benchmark/test_case_runner.py::test_failed_repeat_retains_external_evaluator_boundary`

Expected: FAIL because `_failure_metadata` does not currently accept evaluator metadata.

- [ ] **Step 3: Write the minimal implementation**

Thread the three values through `run_benchmark -> run_case -> _child_entry -> _run_case_inner -> _failure_metadata`. Use the existing `ExternalEvaluator.evaluator_id`, `ExternalEvaluator.evaluation_spec_hash`, and `ExternalEvaluator.request_guard_hash`; do not load expected payloads in the child.

The metadata written by the failure path must be structurally equivalent to the successful path’s boundary block, while leaving `execution_status="failed"`, `graph_hash=None` when no graph exists, and `token_usage_status` truthful.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -q tests/mbse_benchmark/test_case_runner.py::test_failed_repeat_retains_external_evaluator_boundary tests/mbse_benchmark/test_comparison.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/mbse_benchmark/runners/case_runner.py tests/mbse_benchmark/runners/benchmark_runner.py tests/mbse_benchmark/test_case_runner.py
git commit -m "fix: retain evaluator boundary on failed repeats"
```

### Task 3: Make per-scenario reports use repeat metadata and include artifact provenance

**Files:**
- Modify: `tests/mbse_benchmark/runners/benchmark_runner.py` in `_case_metadata`
- Modify: `tests/mbse_benchmark/runners/report_builder.py` in `render_scenario_comparison` and `write_scenario_comparison`
- Test: `tests/mbse_benchmark/test_reporting.py`

**Interfaces:**
- `_case_metadata` must use non-empty `prompt_hash` and `task_spec_hash` from repeat metadata when `run_ledger.json` is empty.
- The reproducibility manifest must include `output_dir`/artifact path and `execution_status` for every repeat, in addition to the existing hashes and telemetry.
- The rendered report must expose the comparison `status` and the artifact audit (`checked_count`, `all_present`, `all_exact`) near the headline.

- [ ] **Step 1: Write the failing tests**

```python
def test_case_metadata_falls_back_to_repeat_metadata() -> None:
    result = benchmark_runner_module._case_metadata(
        "CASE-01",
        [{
            "metadata": {"prompt_hash": "p", "task_spec_hash": "t"},
            "run_ledger": {},
            "repeat_index": 1,
        }],
        track="llm",
        profile="test",
    )
    assert result["prompt_hash"] == ["p"]
    assert result["task_spec_hash"] == ["t"]


def test_comparison_report_shows_artifact_audit_and_status() -> None:
    rendered = render_scenario_comparison({
        "status": "FAIL",
        "input_artifact_audit": {"checked_count": 75, "all_present": False, "all_exact": False},
        "scenarios": {},
    })
    assert "Status: **FAIL**" in rendered
    assert "artifact audit" in rendered
    assert "all_present=False" in rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./.venv/bin/pytest -q tests/mbse_benchmark/test_reporting.py::test_case_metadata_falls_back_to_repeat_metadata tests/mbse_benchmark/test_reporting.py::test_comparison_report_shows_artifact_audit_and_status`

Expected: FAIL because the current case-level metadata only reads the empty ledger and the comparison report does not render the audit summary.

- [ ] **Step 3: Write the minimal implementation**

Union non-empty hashes from both `run_ledger` and repeat `metadata`, preserve sorted unique values, and add `output_dir` plus `execution_status` to each manifest record. Render a compact line such as:

```text
Artifact audit: checked=75; all_present=False; all_exact=False
```

Do not convert missing artifact data into an empty string that looks valid.

- [ ] **Step 4: Run test to verify it passes**

Run: `./.venv/bin/pytest -q tests/mbse_benchmark/test_reporting.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/mbse_benchmark/runners/benchmark_runner.py tests/mbse_benchmark/runners/report_builder.py tests/mbse_benchmark/test_reporting.py
git commit -m "fix: make benchmark reports self-auditing"
```

### Task 4: Re-run the full local verification and publish only truthful GitHub evidence

**Files:**
- Modify: `docs/engineering/mbse4ai-v032-evidence.md` only after the run produces current evidence
- Modify: `.github/workflows/integration.yml` only if the final audit finds a concrete contract defect

**Interfaces:**
- Use a fresh, timestamped output root for each remote campaign; never reuse the failed `/tmp/ai4mbse-5080-qwen-20260930/stable-results` root.
- The final campaign command is:

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile windows-5080-ollama --compare-a-e --path vertical \
  --repeats 3 --timeout 5400 --benchmark-token-budget 8192 \
  --comparison-mode natural \
  --output-root /tmp/ai4mbse-5080-qwen-<fresh-run>/results \
  --report-dir /tmp/ai4mbse-5080-qwen-<fresh-run>/reports
```

- [ ] **Step 1: Run the complete local quality gate**

Run:

```bash
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests scripts
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --track robustness
```

Expected: all commands pass; any remote campaign failure is reported separately from this offline gate.

- [ ] **Step 2: Verify GitHub branch protection and CI on the final commit**

Run:

```bash
gh pr view 2 --repo zhouduichen/MBSE4AI --json mergeStateStatus,reviewDecision,statusCheckRollup
gh api repos/zhouduichen/MBSE4AI/branches/main/protection
```

Expected: `CI / quality` is SUCCESS, `main` requires that check with strict status, and the PR is not claimed merged while review or external prerequisites remain missing.

- [ ] **Step 3: Verify scheduled and external integration evidence**

Run:

```bash
gh run list --repo zhouduichen/MBSE4AI --workflow integration.yml --limit 20
gh workflow view integration.yml --repo zhouduichen/MBSE4AI
```

Expected: a schedule-triggered run exists after the workflow is present on `main`; remote LLM, FreeCAD, and GPU jobs are marked PASS only when their labelled runner and reachability checks actually execute. Missing Actions variables/secrets/runners remain an explicit blocker.

- [ ] **Step 4: Commit the evidence documentation only after verification**

```bash
git add docs/engineering/mbse4ai-v032-evidence.md
git commit -m "docs: record v0.3.2 evidence integrity and external checks"
```

Do not mark the goal complete until the final comparison JSON has all 17 invariants true, 75/75 exact input artifacts, 15 repeats per scenario, and the GitHub evidence is tied to the final commit.
