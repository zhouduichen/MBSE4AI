# AI4MBSE MBSE Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and execute a deterministic, evidence-backed MBSE benchmark against the current AI4MBSE application and produce the required CASE-01～CASE-05, T1～T20, fault-injection, regression, metrics, failure, and traceability artifacts.

**Architecture:** Keep production code unchanged. Store benchmark inputs and semantic expectations as JSON, invoke the real `V2Services` application stack with the supported offline `RuleRuntime`, persist raw outputs per isolated case run, then run pure validators over those outputs. A report assembler converts validator results into the task-book score, P0 decision, and Markdown/JSON reports.

**Tech Stack:** Python 3.11+, pytest, standard library `json`/`pathlib`/`tempfile`/`subprocess`, existing `rflp_lite.bootstrap.v2`, `ProjectService`, `AnalysisService`, `ModelService`, `RuleRuntime`, and `ModelGraph` repository APIs.

## Global Constraints

- Do not alter production behavior to make benchmark results pass.
- Use real application services and persist real ModelGraph/SQLite results; never substitute expected output for observed output.
- `expected/` contains only coverage references, constraints, and known fault expectations.
- Missing implementation must be reported as `NOT_IMPLEMENTED`, execution failures as `FAIL`, and timeout/stall as `BLOCKED`.
- CASE-05 must detect both weight and runtime conflicts before the overall result can be accepted.
- Preserve all existing user changes in the dirty worktree.

---

### Task 1: Add benchmark cases and semantic expectations

**Files:**
- Create: `tests/mbse_benchmark/cases/case_01_smart_lock.json`
- Create: `tests/mbse_benchmark/cases/case_02_vending_machine.json`
- Create: `tests/mbse_benchmark/cases/case_03_delivery_robot.json`
- Create: `tests/mbse_benchmark/cases/case_04_drone.json`
- Create: `tests/mbse_benchmark/cases/case_05_fault_injection.json`
- Create: `tests/mbse_benchmark/expected/coverage_expectations.json`
- Create: `tests/mbse_benchmark/expected/metric_targets.json`
- Create: `tests/mbse_benchmark/expected/known_conflicts.json`

**Interfaces:**
- Produces case dictionaries with `case_id`, `system`, `brief`, `stakeholders`, `lifecycle_stages`, `scenarios`, `requirements`, and optional `physical_design`.
- Produces semantic expectation dictionaries consumed by validators and report assembly.

- [ ] **Step 1: Write the five JSON input cases**

Each case must contain the exact task-book input meaning, with stable IDs for explicit requirements and no generated model objects. CASE-03 must list rain, night, communication interruption, low battery, localization anomaly, road closure, and sudden pedestrian as expected scenario semantics. CASE-05 must contain the two requirements and five physical components with mass, power, and energy values.

- [ ] **Step 2: Write expectation and target JSON**

Store stakeholder synonym groups, lifecycle synonym groups, required scenario phrases, all task-book target thresholds, and the two CASE-05 arithmetic conflicts. Do not store a complete entity graph or a presumed correct system response.

- [ ] **Step 3: Validate the fixtures**

Run:

```bash
./.venv/bin/python -m json.tool tests/mbse_benchmark/cases/case_05_fault_injection.json >/dev/null
./.venv/bin/python -m pytest tests/mbse_benchmark -q
```

Expected: fixture parsing tests pass once Task 2 adds the loader; before that, only JSON parsing is expected to be manually checked.

### Task 2: Implement case loading, isolated execution, and raw result persistence

**Files:**
- Create: `tests/mbse_benchmark/__init__.py`
- Create: `tests/mbse_benchmark/cases/__init__.py`
- Create: `tests/mbse_benchmark/fixtures/__init__.py`
- Create: `tests/mbse_benchmark/runners/__init__.py`
- Create: `tests/mbse_benchmark/runners/case_runner.py`
- Create: `tests/mbse_benchmark/runners/benchmark_runner.py`
- Create: `tests/mbse_benchmark/test_fixture_loading.py`

**Interfaces:**
- `load_case(path: Path) -> dict[str, object]`
- `load_expectations(path: Path) -> dict[str, object]`
- `run_case(case: Mapping[str, object], output_dir: Path, *, repeat_index: int = 1, timeout_seconds: int = 60) -> dict[str, object]`
- `run_benchmark(cases_dir: Path, output_root: Path, *, repeats: int = 3) -> dict[str, object]`

- [ ] **Step 1: Write loader tests**

Test that all five cases load, IDs are unique, CASE-05 contains exactly the required numeric design values, and expected target keys are present.

- [ ] **Step 2: Implement fixture loaders**

Use `Path.read_text(encoding="utf-8")` and `json.loads`. Reject a non-object case, missing `case_id`, missing `system`, or malformed `requirements` with a descriptive `ValueError`.

- [ ] **Step 3: Write runner tests with a temporary output directory**

Test that a case run creates `input.json`, `run_summary.json`, `model.json`, `issues.json`, `audit.json`, and `execution.json`, and that the output records the runtime mode, revision, elapsed time, status, and exception/timeout details when present.

- [ ] **Step 4: Implement real application execution**

Create a temporary workspace per repeat, call `build_v2_services(workspace, runtime=RuleRuntime(), config_dir=workspace / ".rflp-config")`, then call `services.projects.create`, `services.projects.ingest`, and `services.analysis(case_id).run(case_id)`. Read the resulting graph through `services.model(case_id).graph(case_id)` and write canonical JSON serializations of the graph and repository records. For CASE-05, call a dedicated fixture injector before analysis to add the physical design from the case input through a normal `Patch` / repository append operation.

- [ ] **Step 5: Add bounded execution**

Run each case repeat in a child process or an equivalent bounded worker so an active adapter, deadlock, or repair loop becomes a recorded `BLOCKED` result after 60 seconds. The parent runner must continue to the next case and repeat rather than abort the benchmark.

- [ ] **Step 6: Run the runner smoke test**

Run:

```bash
./.venv/bin/python -m pytest tests/mbse_benchmark/test_fixture_loading.py -q
```

Expected: all five fixtures load and one offline case produces raw result files.

### Task 3: Implement deterministic structural and semantic validators

**Files:**
- Create: `tests/mbse_benchmark/validators/__init__.py`
- Create: `tests/mbse_benchmark/validators/common.py`
- Create: `tests/mbse_benchmark/validators/coverage.py`
- Create: `tests/mbse_benchmark/validators/requirements.py`
- Create: `tests/mbse_benchmark/validators/traceability.py`
- Create: `tests/mbse_benchmark/validators/architecture.py`
- Create: `tests/mbse_benchmark/validators/verification.py`
- Create: `tests/mbse_benchmark/validators/consistency.py`
- Create: `tests/mbse_benchmark/validators/regression.py`
- Create: `tests/mbse_benchmark/test_validators.py`

**Interfaces:**
- `validate_case(case, raw_result, expectations) -> list[dict[str, object]]`
- `validate_structural_graph(graph_dict) -> list[dict[str, object]]`
- `validate_coverage(case, graph_dict, expectations) -> dict[str, object]`
- `validate_requirements(graph_dict, expectations) -> dict[str, object]`
- `validate_traceability(graph_dict) -> dict[str, object]`
- `validate_architecture(graph_dict, case) -> dict[str, object]`
- `validate_verification(graph_dict) -> dict[str, object]`
- `validate_consistency(graph_dict, case, expectations) -> dict[str, object]`
- `validate_regression(repeat_results) -> dict[str, object]`

- [ ] **Step 1: Write structural validator tests**

Cover duplicate IDs, missing relation endpoints, invalid relation references, missing requirement source metadata, orphan entities, and invalid verification-case payload fields. Use hand-built validator input dictionaries only for validator unit tests; these are not benchmark outputs.

- [ ] **Step 2: Implement graph normalization and structural checks**

Normalize `entities` and `relations` from the real export, preserve IDs and kinds, and emit a finding with `test_id`, `case_id`, `severity`, `expected`, `actual`, `related_elements`, `root_cause`, and `recommended_fix` for each failure.

- [ ] **Step 3: Write coverage and requirement tests**

Cover synonym matching for maintenance/repair/operator roles, lifecycle aliases, normal/alternative/exception categories, atomicity heuristics, measurable numeric requirements, source validity, and unsupported hard assumptions.

- [ ] **Step 4: Implement semantic coverage and requirement quality**

Match normalized Chinese/English phrases against expectation synonym groups. Score coverage by matched expected items divided by expected items. Treat an output as unsupported when it introduces a hard component or numeric constraint without source IDs, scenario IDs, evidence, or derivation rationale.

- [ ] **Step 5: Write traceability, architecture, verification, and consistency tests**

Cover complete and broken Requirement → Function → Logical → Physical → Verification paths, missing links, required verification payload fields, orphan test cases, and CASE-05 arithmetic.

- [ ] **Step 6: Implement path and arithmetic validators**

Build adjacency maps from actual graph relations. Follow typed paths rather than trusting payload lists. For CASE-05, sum the injected mass values, compute runtime as `available_energy / average_power`, compare against requirement thresholds, and fail if the model claims the violated physical architecture is satisfied.

- [ ] **Step 7: Implement repeat stability checks**

Compare normalized entity-kind/name semantic sets, relation triples, coverage metrics, and P0 conflict detection across three actual runs. Do not compare timestamps, generated revision IDs, or natural-language wording byte-for-byte.

- [ ] **Step 8: Run validator unit tests**

Run:

```bash
./.venv/bin/python -m pytest tests/mbse_benchmark/test_validators.py -q
```

Expected: deterministic validator tests pass.

### Task 4: Implement metrics, scoring, failures, and reports

**Files:**
- Create: `tests/mbse_benchmark/runners/report_builder.py`
- Create: `tests/mbse_benchmark/reports/.gitkeep`
- Create: `tests/mbse_benchmark/test_reporting.py`

**Interfaces:**
- `compute_metrics(case_results) -> dict[str, object]`
- `compute_score(metrics) -> dict[str, object]`
- `build_failures(case_results) -> list[dict[str, object]]`
- `render_benchmark_report(summary) -> str`
- `render_traceability_report(summary) -> str`
- `write_reports(summary, report_dir) -> None`

- [ ] **Step 1: Write report tests**

Use synthetic validator findings to assert that `failures.json` contains the required fields, a P0 failure forces `REJECTED`, `metrics.json` contains all task-book metrics, and Markdown includes the exact sections 1–13 required by the task book.

- [ ] **Step 2: Implement metric aggregation**

Aggregate per-case metrics, preserve `PASS`/`FAIL`/`NOT_IMPLEMENTED`/`BLOCKED`, compute weighted coverage using matched/expected counts, and calculate current capability and full target capability separately when an entire layer is absent.

- [ ] **Step 3: Implement score and hard-gate decisions**

Use the task-book category weights. Mark `ACCEPTED` only when score is at least 80 and all six P0 conditions pass; otherwise mark `REJECTED`.

- [ ] **Step 4: Implement Markdown and JSON report writers**

Generate `benchmark_report.md`, `metrics.json`, `failures.json`, and `traceability_report.md` under `tests/mbse_benchmark/reports/`. Include commit, branch, Python/runtime, test date, configuration, actual entrypoint, case table, all metrics, P0 failures, top problems, current gaps, and recommended fix order.

- [ ] **Step 5: Run report tests**

Run:

```bash
./.venv/bin/python -m pytest tests/mbse_benchmark/test_reporting.py -q
```

Expected: report structure and hard-gate decisions pass.

### Task 5: Add benchmark CLI and README

**Files:**
- Create: `tests/mbse_benchmark/run_benchmark.py`
- Create: `tests/mbse_benchmark/README.md`
- Modify: `tests/mbse_benchmark/runners/benchmark_runner.py`

- [ ] **Step 1: Implement command-line options**

Support:

```text
python tests/mbse_benchmark/run_benchmark.py
python tests/mbse_benchmark/run_benchmark.py --case CASE-03 --repeats 3 --timeout 60
python tests/mbse_benchmark/run_benchmark.py --output-root tests/mbse_benchmark/results
```

The default must run all five cases, three repeats, and write reports to `tests/mbse_benchmark/reports`.

- [ ] **Step 2: Document execution and interpretation**

Document offline runtime selection, raw-result locations, status semantics, P0 gates, known baseline test failures, and how to rerun with a configured model without confusing that run with the deterministic acceptance baseline.

- [ ] **Step 3: Run the benchmark end-to-end**

Run:

```bash
./.venv/bin/python tests/mbse_benchmark/run_benchmark.py --repeats 3 --timeout 60
```

Expected: all cases either complete with raw artifacts or produce bounded `BLOCKED`/`FAIL` records; the process exits nonzero only after reports are written if the final status is `REJECTED`.

### Task 6: Execute full verification and inspect root causes

**Files:**
- Modify: `tests/mbse_benchmark/reports/benchmark_report.md`
- Modify: `tests/mbse_benchmark/reports/metrics.json`
- Modify: `tests/mbse_benchmark/reports/failures.json`
- Modify: `tests/mbse_benchmark/reports/traceability_report.md`

- [ ] **Step 1: Run the new benchmark tests**

Run:

```bash
./.venv/bin/python -m pytest tests/mbse_benchmark -q
```

- [ ] **Step 2: Run the repository regression suite**

Run:

```bash
./.venv/bin/python -m pytest -q
```

Record the two known baseline failures and any new failures separately.

- [ ] **Step 3: Inspect five result directories**

Confirm each case has actual input, run, graph, issue, audit, and execution records; inspect CASE-05 arithmetic findings and trace break locations.

- [ ] **Step 4: Finalize report root causes and priority order**

Each failure must state expected, actual, related element IDs, root cause, recommended fix, and priority. Do not change production code during this inspection.

- [ ] **Step 5: Run compile and lint checks for benchmark code**

Run:

```bash
./.venv/bin/python -m compileall -q tests/mbse_benchmark
./.venv/bin/ruff check tests/mbse_benchmark
```

Expected: benchmark code compiles and has no new lint errors, or the report records the exact tooling failure.
