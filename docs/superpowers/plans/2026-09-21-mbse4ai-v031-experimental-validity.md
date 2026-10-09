# MBSE4AI v0.3.1 Experimental Validity & Engineering Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the A–E benchmark to a same-model, same-input, same-evaluator experiment; expose TechnicalClosure and ReleaseClosure; make empty coverage N/A; and add reproducible CI gates.

**Architecture:** Keep benchmark orchestration in `tests/mbse_benchmark`, but split scenario execution, graph normalization, evaluation, and metadata into focused modules. Keep closure and canonical coverage in `src/rflp_lite/methodology`, then make projections, deliverables, benchmark reports, and Web API serialize the same status contract. Use an offline deterministic model stub only for tests; real configured providers remain explicit integration inputs.

**Tech Stack:** Python 3.11+, dataclasses/StrEnum, existing `ModelGraph`, `OpenAICompatibleModel`, pytest, Ruff, import-linter, GitHub Actions, and the repository's existing `uv.lock`.

## Global Constraints

- A/B must call the same injected model/provider contract as E and must not read expected graphs or call `bare_model_graph()`.
- All scenarios must pass through one `ModelGraphNormalizer` and one external evaluator.
- `TechnicalClosure` accepts `VALIDATED | ACCEPTED | LOCKED`; `ReleaseClosure` accepts `ACCEPTED | LOCKED` only.
- Empty coverage must be `{status: "not_applicable", coverage: null, covered_count: 0, requirement_count: 0}` and must not become a passing ratio.
- Ordinary CI must not require remote LLM, FreeCAD, GPU, or credentials.
- Every changed behavior gets a focused test before implementation and a focused test run after implementation.

---

### Task 1: Establish the canonical coverage status contract

**Files:**
- Create: `src/rflp_lite/methodology/coverage_status.py`
- Modify: `src/rflp_lite/methodology/coverage_matrix.py`
- Modify: `src/rflp_lite/methodology/vertical_coverage.py`
- Test: `tests/methodology/test_coverage_status.py`
- Modify: `tests/methodology/test_coverage_matrix.py`
- Modify: `tests/methodology/test_vertical_coverage.py`

**Interfaces:**
- Produce `CoverageStatus` with values `PASS`, `FAIL`, and `N/A` (serialized as `pass`, `fail`, and `not_applicable`).
- Produce `coverage_result(covered_count: int, total_count: int, *, passed: bool | None = None) -> Mapping[str, object]` with `coverage: None` and N/A status when `total_count == 0`.
- `CoverageMatrix.metrics` will include `coverage_status` and `coverage` for aggregate coverage while retaining named ratios for compatibility.
- `VerticalCoverage.as_check()` will include `status` and nullable `coverage`.

- [ ] **Step 1: Write the failing status tests.**

```python
def test_empty_coverage_is_not_applicable():
    result = coverage_result(0, 0)
    assert result == {
        "covered_count": 0,
        "requirement_count": 0,
        "coverage": None,
        "status": "not_applicable",
    }


def test_non_empty_coverage_has_pass_or_fail_and_ratio():
    assert coverage_result(2, 2)["status"] == "pass"
    assert coverage_result(1, 2)["status"] == "fail"
    assert coverage_result(1, 2)["coverage"] == 0.5
```

- [ ] **Step 2: Run the focused tests and verify they fail.**

Run: `pytest -q tests/methodology/test_coverage_status.py`

Expected: collection or assertion failure because `coverage_status.py` and `coverage_result` do not yet exist.

- [ ] **Step 3: Implement the shared helper and wire both coverage producers.**

Implement the enum and helper with stable serialized values. In `build_requirement_coverage`, calculate `requirement_scope = len(rows)`, preserve the existing named ratios as `None` for empty scope, and add the canonical result under `coverage`. In `VerticalCoverage.as_check`, derive the status from `covered_count` and `len(rows)` and keep `passed` as `status == "pass"` for compatibility.

- [ ] **Step 4: Run focused tests and update old empty-scope assertions.**

Run: `pytest -q tests/methodology/test_coverage_status.py tests/methodology/test_coverage_matrix.py tests/methodology/test_vertical_coverage.py`

Expected: PASS, with empty matrix and empty vertical-stage checks asserting N/A/null instead of `1.0` or a vacuous pass. Existing non-empty ratio tests must remain green.

- [ ] **Step 5: Commit the coverage contract.**

```bash
git add src/rflp_lite/methodology/coverage_status.py src/rflp_lite/methodology/coverage_matrix.py src/rflp_lite/methodology/vertical_coverage.py tests/methodology/test_coverage_status.py tests/methodology/test_coverage_matrix.py tests/methodology/test_vertical_coverage.py
git commit -m "feat: define canonical coverage status semantics"
```

### Task 2: Split TechnicalClosure from ReleaseClosure

**Files:**
- Modify: `src/rflp_lite/methodology/closure.py`
- Modify: `src/rflp_lite/methodology/gates.py` if the strict gate imports closure status assumptions
- Test: `tests/methodology/test_closure_gates.py`
- Modify: `tests/methodology/test_strict_closure.py`

**Interfaces:**
- Add `ClosureGate` with `TECHNICAL` and `RELEASE` values.
- Add `evaluate_technical_closure(graph, *, issue_records=()) -> ClosureAssessment`.
- Add `evaluate_release_closure(graph, *, issue_records=()) -> ClosureAssessment`.
- Keep `evaluate_strict_closure` as an explicit compatibility alias to `evaluate_release_closure`.
- Extend `ClosureAssessment` with `gate` and `ready_statuses` while keeping `passed`, `issues`, `requirement_ids`, and `accepted_count` available to current callers.

- [ ] **Step 1: Add failing tests for the lifecycle distinction.**

```python
def test_validated_only_graph_passes_technical_but_fails_release():
    graph = _graph(requirement_status=EntityStatus.VALIDATED, downstream_status=EntityStatus.VALIDATED)
    assert evaluate_technical_closure(graph).passed is True
    release = evaluate_release_closure(graph)
    assert release.passed is False
    assert "fact_not_accepted" in _codes(release)


def test_release_closure_rejects_zero_accepted_requirements():
    graph = ModelGraph("p1", ())
    result = evaluate_release_closure(graph)
    assert result.passed is False
    assert result.gate.value == "release"
    assert "empty_requirement_scope" in _codes(result)
```

- [ ] **Step 2: Run the focused tests and verify failure.**

Run: `pytest -q tests/methodology/test_closure_gates.py tests/methodology/test_strict_closure.py`

Expected: FAIL because the new gate functions and assessment fields are not present.

- [ ] **Step 3: Refactor the shared closure evaluator.**

Parameterize the current strict evaluator by `ready_statuses` and `gate`. Keep the existing missing trace, placeholder, human-review, V&V-plan, and issue checks. For TechnicalClosure, `VALIDATED` is ready. For ReleaseClosure, any traced entity with status `VALIDATED` produces `fact_not_accepted`; Candidate continues to produce `unresolved_candidate`. Keep the empty Requirement scope hard-failing in both gates.

- [ ] **Step 4: Run all closure and gate tests.**

Run: `pytest -q tests/methodology/test_closure_gates.py tests/methodology/test_strict_closure.py tests/methodology/test_gates.py tests/methodology/test_completion_conditions.py`

Expected: PASS. The old strict tests must still pass through the release alias, and no existing global gate may become a vacuous pass.

- [ ] **Step 5: Commit the two-gate closure semantics.**

```bash
git add src/rflp_lite/methodology/closure.py src/rflp_lite/methodology/gates.py tests/methodology/test_closure_gates.py tests/methodology/test_strict_closure.py
git commit -m "feat: separate technical and release closure gates"
```

### Task 3: Build the unified benchmark pipeline and metadata

**Files:**
- Create: `tests/mbse_benchmark/runners/scenario_pipeline.py`
- Create: `tests/mbse_benchmark/runners/benchmark_metadata.py`
- Modify: `tests/mbse_benchmark/scenarios.py`
- Modify: `tests/mbse_benchmark/validators/case.py`
- Create: `tests/mbse_benchmark/test_scenario_pipeline.py`

**Interfaces:**
- `ModelGraphNormalizer.normalize(value: object, *, project_id: str) -> ModelGraph` owns the existing mapping-to-graph conversion.
- `ExternalEvaluator.evaluate(case: Mapping[str, object], graph: ModelGraph) -> Mapping[str, object]` delegates to the existing case validators without scenario-specific metric defaults.
- `ScenarioRunner.run(case, contract, model, *, project_id, token_budget) -> ScenarioOutput` invokes A/B model generation or C–E Harness execution and always returns normalized graph, evaluator metrics, and metadata.
- `RunMetadata` serializes the exact fields `scenario`, `model`, `provider`, `prompt_hash`, `task_spec_hash`, `temperature`, `input_hash`, `token_usage`, `latency_ms`, `graph_hash`, `verifier_enabled`, `repair_enabled`, and `cas_enabled`.

- [ ] **Step 1: Write tests with a recording fake model.**

```python
class RecordingModel:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        return type("Response", (), {"payload": self.payload, "usage": {"total_tokens": 42}})()


def test_one_shot_and_staged_scenarios_call_the_same_model_without_expected_graph():
    case = {
        "case_id": "CASE-01",
        "system": "测试系统",
        "brief": "测试输入",
        "stakeholders": [],
        "lifecycle_stages": [],
        "scenarios": [],
        "requirements": [],
    }
    model = RecordingModel({"project_id": "p1", "entities": [], "relations": []})
    runner = ScenarioRunner(normalizer=ModelGraphNormalizer(), evaluator=ExternalEvaluator())
    for scenario in (BenchmarkScenario.A_BARE_ONE_SHOT, BenchmarkScenario.B_BARE_STAGED):
        runner.run(case, scenario_contract(scenario), model, project_id="p1", token_budget=1200)
    assert len(model.requests) >= 2
    assert all("expected" not in request.input_payload for request in model.requests)


def test_metadata_contains_hashes_and_control_switches():
    case = {"case_id": "CASE-01", "system": "测试系统", "brief": "测试输入", "requirements": []}
    model = RecordingModel({"project_id": "p1", "entities": [], "relations": []})
    runner = ScenarioRunner(normalizer=ModelGraphNormalizer(), evaluator=ExternalEvaluator())
    result = runner.run(case, scenario_contract(BenchmarkScenario.A_BARE_ONE_SHOT), model, project_id="p1", token_budget=1200)
    payload = result.metadata.as_dict()
    assert {"scenario", "model", "provider", "prompt_hash", "task_spec_hash", "temperature", "input_hash", "token_usage", "latency_ms", "graph_hash", "verifier_enabled", "repair_enabled", "cas_enabled"} <= payload.keys()
```

- [ ] **Step 2: Run the new tests and verify failure.**

Run: `pytest -q tests/mbse_benchmark/test_scenario_pipeline.py`

Expected: FAIL because the pipeline classes and metadata object do not exist.

- [ ] **Step 3: Move graph normalization out of the scenario helper.**

Move the current `normalize_to_model_graph`, `_graph_from_mapping`, and `_entity_from_mapping` behavior into `ModelGraphNormalizer`; retain `normalize_to_model_graph` as a thin compatibility function. Add canonical JSON SHA-256 helpers for input, prompts, task spec, and graph. Capture provider/model/temperature from the model adapter configuration without including API keys.

- [ ] **Step 4: Implement A/B model generation contracts.**

Define a complete structured schema with entities and relations. A sends one `GenerationRequest` containing only the case input and task specification. B sends one request per stage (`requirements`, `functional`, `logical`, `physical`, `verification_validation`) with the case input and prior generated graph state, never expected data. Normalize each final response through the same normalizer. Record usage when present, otherwise `None`.

- [ ] **Step 5: Implement one external evaluator boundary.**

Make the evaluator accept only the normalized graph and case; remove any scenario-specific metric injection. Compute trace and RFLP coverage from graph relations and return N/A for metrics whose denominator is zero. Keep expected fixture data available only to the evaluator, never to the model request.

- [ ] **Step 6: Run focused pipeline tests.**

Run: `pytest -q tests/mbse_benchmark/test_scenario_pipeline.py tests/mbse_benchmark/test_tracks.py`

Expected: PASS, including the assertion that A/B requests contain no expected graph and that trace/RFLP metrics are computed rather than hard-coded.

- [ ] **Step 7: Commit the unified pipeline core.**

```bash
git add tests/mbse_benchmark/runners/scenario_pipeline.py tests/mbse_benchmark/runners/benchmark_metadata.py tests/mbse_benchmark/scenarios.py tests/mbse_benchmark/validators/case.py tests/mbse_benchmark/test_scenario_pipeline.py tests/mbse_benchmark/test_tracks.py
git commit -m "feat: add unified same-model benchmark pipeline"
```

### Task 4: Route the benchmark runner through A–E and remove the old baseline

**Files:**
- Modify: `tests/mbse_benchmark/runners/case_runner.py`
- Modify: `tests/mbse_benchmark/runners/benchmark_runner.py`
- Modify: `tests/mbse_benchmark/tracks/llm.py`
- Modify: `tests/mbse_benchmark/runners/report_builder.py`
- Modify: `tests/mbse_benchmark/test_tracks.py`
- Modify: `tests/mbse_benchmark/test_reporting.py`

**Interfaces:**
- The existing `run_benchmark` entry point, when called with its current `cases_dir`, `output_root`, `repeats`, `timeout_seconds`, `report_dir`, `selected_case`, `track`, `profile`, `runtime_config`, `analysis_path`, and `scenario` parameters, emits one scenario result with normalized graph, evaluator metrics, and complete metadata.
- `run_bare_baseline` is removed from the report path; `--baseline` is either removed or mapped to explicit A/B scenarios without a second evaluator.
- `render_benchmark_report` shows one A–E result table and serialized metadata, not a separate legacy baseline section.
- Add `run_one_scenario(case: Mapping[str, object], scenario: BenchmarkScenario, model: object, *, output_dir: Path) -> ScenarioOutput` as the injectable test seam used by the CLI runner.

- [ ] **Step 1: Add failing regression tests against the old behavior.**

```python
def test_bare_scenario_does_not_construct_graph_from_case(monkeypatch, tmp_path):
    monkeypatch.setattr("tests.mbse_benchmark.scenarios.bare_model_graph", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ground truth constructor used")))
    case = {"case_id": "CASE-01", "system": "测试系统", "brief": "测试输入", "requirements": []}
    model = RecordingModel({"project_id": "case-01", "entities": [], "relations": []})
    result = run_one_scenario(case, BenchmarkScenario.A_BARE_ONE_SHOT, model, output_dir=tmp_path)
    assert result.metadata.scenario == BenchmarkScenario.A_BARE_ONE_SHOT.value


def test_report_has_computed_rflp_metrics_and_run_metadata(tmp_path):
    summary = {
        "track": "llm",
        "scenario_results": [{
            "metadata": {"trace_accuracy": 0.75, "RFLP_coverage": 0.5, "verifier_enabled": False},
        }],
        "metrics": {"trace_accuracy": 0.75, "RFLP_coverage": 0.5},
    }
    write_reports(summary, tmp_path)
    report = (tmp_path / "metrics.json").read_text()
    assert '"trace_accuracy": 0.0' not in report
    assert '"RFLP_coverage": 0.0' not in report
    assert '"verifier_enabled"' in report
```

- [ ] **Step 2: Run the tests and verify they fail against the current bare path.**

Run: `pytest -q tests/mbse_benchmark/test_tracks.py tests/mbse_benchmark/test_reporting.py`

Expected: FAIL because `case_runner.py` still calls `bare_model_graph()` and `llm.py` writes structural zero metrics.

- [ ] **Step 3: Wire `case_runner.py` to scenario controls.**

Use the contract to set `verifier_enabled`, repair rounds, and CAS probing. For A/B, instantiate the same configured model used by E and call `ScenarioRunner`; for C–E, keep the real application services but pass the contract switches. Never synthesize an answer from `case` data. Persist `metadata.json` beside `model.json` and include its values in `execution.json`.

- [ ] **Step 4: Replace the old LLM baseline with A–E scenario execution.**

Retain profile resolution and the provider adapter, but remove `_BARE_SCHEMA`, `evaluate_bare_payload`, and `run_bare_baseline` from the benchmark result path. Add a scenario selection/compare mode that runs A, B, C, D, and E with the same resolved config and input hash. Any LLM metric must come from the normalized graph/evaluator; empty denominators are N/A/null rather than `0.0`.

- [ ] **Step 5: Update reports and tests.**

Report the five scenario contracts, computed metrics, graph hash, and run metadata in JSON and Markdown. Keep the existing P0 score logic, but make it consume the evaluator result and fail if a scenario has no graph. Remove the legacy separate bare section.

- [ ] **Step 6: Run benchmark-focused verification.**

Run: `pytest -q tests/mbse_benchmark`

Expected: PASS; A/B model calls are observable in fake-model tests, all scenarios have the same normalized graph schema, and no benchmark code contains `trace_accuracy: 0.0` or `RFLP_coverage: 0.0` assignments.

- [ ] **Step 7: Commit the runner migration.**

```bash
git add tests/mbse_benchmark/runners/case_runner.py tests/mbse_benchmark/runners/benchmark_runner.py tests/mbse_benchmark/tracks/llm.py tests/mbse_benchmark/runners/report_builder.py tests/mbse_benchmark/test_tracks.py tests/mbse_benchmark/test_reporting.py
git commit -m "refactor: route benchmark comparisons through one evaluator"
```

### Task 5: Propagate coverage status through projections, deliverables, and Web API

**Files:**
- Modify: `src/rflp_lite/application/projections/traceability.py`
- Modify: `src/rflp_lite/application/projections/requirements.py`
- Modify: `src/rflp_lite/application/projections/assurance.py`
- Modify: `src/rflp_lite/application/deliverables.py`
- Modify: `tests/mbse_benchmark/runners/report_builder.py`
- Test: `tests/application/projections/test_coverage_semantics.py`
- Modify: `tests/application/projections/test_traceability_projection.py`
- Modify: `tests/interface/web/test_traceability_matrix.py`

**Interfaces:**
- Traceability rows expose `coverage_status` and nullable `coverage_percent` for empty scopes.
- Aggregate views expose `coverage_status`, `covered_count`, `requirement_count`, and `coverage` from the shared helper.
- Existing non-empty `coverage_percent == 100.0` behavior remains unchanged.

- [ ] **Step 1: Write empty-scope projection tests.**

```python
def test_empty_traceability_view_is_not_applicable():
    view = build_traceability_view(ModelGraph("p1", (), ()))
    assert view["metrics"]["status"] == "not_applicable"
    assert view["metrics"]["coverage"] is None
    assert view["average_coverage_percent"] is None
```

- [ ] **Step 2: Run and verify failure.**

Run: `pytest -q tests/application/projections/test_coverage_semantics.py tests/application/projections/test_traceability_projection.py tests/interface/web/test_traceability_matrix.py`

Expected: FAIL because current empty projections use `100.0` and do not expose a canonical status.

- [ ] **Step 3: Replace empty defaults with the shared helper.**

Use `coverage_result` in traceability, requirements, assurance, deliverable, and benchmark report serialization. For row-level percentage, use `None` when the row has no applicable stage scope; use status `not_applicable` instead of treating zero requirements as complete.

- [ ] **Step 4: Run projection and API tests.**

Run: `pytest -q tests/application/projections tests/interface/web/test_traceability_matrix.py tests/interface/web/test_model_trace.py tests/interface/web/test_deliverables_api.py`

Expected: PASS with complete fixtures unchanged and empty fixtures explicitly N/A.

- [ ] **Step 5: Commit semantic propagation.**

```bash
git add src/rflp_lite/application/projections/traceability.py src/rflp_lite/application/projections/requirements.py src/rflp_lite/application/projections/assurance.py src/rflp_lite/application/deliverables.py tests/mbse_benchmark/runners/report_builder.py tests/application/projections/test_coverage_semantics.py tests/application/projections/test_traceability_projection.py tests/interface/web/test_traceability_matrix.py
git commit -m "fix: propagate not-applicable coverage semantics"
```

### Task 6: Add ordinary and integration GitHub workflows

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/integration.yml`
- Create: `.importlinter`
- Modify: `docs/DEVELOPMENT_STATUS.md` or create `docs/CI.md`

**Interfaces:**
- CI workflow name/check: `CI / quality`.
- Ordinary workflow runs on `push` and `pull_request` with Python 3.12 and executes exactly the required checks.
- Integration workflow is `workflow_dispatch` plus nightly schedule and is allowed to skip when provider/FreeCAD/GPU credentials are absent.

- [ ] **Step 1: Add a local command contract test/documentation.**

Document these commands as the required check sequence:

```bash
pytest -q
ruff check src tests scripts
python -m compileall -q src tests scripts
lint-imports
python scripts/architecture_metrics.py
python tests/mbse_benchmark/run_benchmark.py --track robustness
```

- [ ] **Step 2: Add import-linter configuration.**

Create a minimal `.importlinter` contract for the existing package boundary, using `rflp_lite` as the root package and a no-cycle contract that fails on new import cycles without inventing layer restrictions not present in the repository.

- [ ] **Step 3: Add `ci.yml`.**

Install the locked project with dev dependencies, run the six commands in separate named steps, upload benchmark output on failure, and use `uv` only if available through the repository setup; otherwise use standard pip installation from `pyproject.toml`.

- [ ] **Step 4: Add manual/nightly integration workflow.**

Expose inputs for `profile`, `scenario`, and `path`; run remote LLM/FreeCAD/GPU tests only when corresponding secrets or self-hosted labels exist. Do not run it from `ci.yml`.

- [ ] **Step 5: Verify workflow syntax and local commands.**

Run: `python -m compileall -q src tests scripts`, `ruff check src tests scripts`, `lint-imports`, `python scripts/architecture_metrics.py`, and `python tests/mbse_benchmark/run_benchmark.py --track robustness`.

Expected: all commands exit 0 in the available environment; if `lint-imports` is unavailable, install the declared dev dependency and rerun before considering the task complete.

- [ ] **Step 6: Commit CI configuration.**

```bash
git add .github/workflows/ci.yml .github/workflows/integration.yml .importlinter docs/CI.md
git commit -m "ci: enforce offline quality and robustness benchmark"
```

### Task 7: Full regression, audit, and release evidence

**Files:**
- Modify: `tests/mbse_benchmark/README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `tests/mbse_benchmark/reports/benchmark_report.md` only if regenerated output is intentionally tracked

- [ ] **Step 1: Run the complete local quality gate.**

```bash
pytest -q
ruff check src tests scripts
python -m compileall -q src tests scripts
lint-imports
python scripts/architecture_metrics.py
python tests/mbse_benchmark/run_benchmark.py --track robustness
```

Expected: all commands pass and architecture metrics stay within `architecture_budget.json`.

- [ ] **Step 2: Run targeted same-model benchmark tests.**

Run: `pytest -q tests/mbse_benchmark tests/methodology/test_closure_gates.py tests/methodology/test_coverage_status.py tests/application/projections/test_coverage_semantics.py`

Expected: A/B/E share model/provider metadata and normalizer/evaluator identity; no expected graph is present in model input; TechnicalClosure and ReleaseClosure differ only as designed; empty coverage is N/A/null.

- [ ] **Step 3: Audit prohibited legacy behavior.**

Run:

```bash
rg -n "bare_model_graph|bare_llm_requirement_extraction|trace_accuracy\"\s*:\s*0\.0|RFLP_coverage\"\s*:\s*0\.0|else 100\.0|if rows else 100" tests src
```

Expected: no benchmark execution path uses the ground-truth constructor or legacy prompt, no structural zero metric assignments remain, and no empty coverage path defaults to 100%.

- [ ] **Step 4: Update benchmark documentation with reproducibility fields and CI boundary.**

Document how to run A–E with a configured profile, how to interpret N/A, and which checks are deliberately excluded from ordinary CI.

- [ ] **Step 5: Commit final documentation/evidence and inspect status.**

```bash
git add tests/mbse_benchmark/README.md docs/DEVELOPMENT_STATUS.md
git commit -m "docs: document reproducible v0.3.1 benchmark evidence"
git status --short
```

Expected: clean worktree except for explicitly user-owned files that were present before this task.
