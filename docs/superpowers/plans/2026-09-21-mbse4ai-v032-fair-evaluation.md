# MBSE4AI v0.3.2 Fair Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the A–E benchmark a fair, reproducible same-model experiment with isolated ground truth, authority-safe normalization, orthogonal Harness controls, complete cost telemetry, repeat statistics, truthful CI, and actionable integration jobs.

**Architecture:** Add a canonical `BenchmarkInputEnvelope` and evaluator-only `EvaluationSpec`. Every scenario consumes the same envelope, one normalizer, and one `ExternalEvaluator`; adapter-boundary telemetry records every real provider call. Semantic evaluation uses a status-neutral projection while governance uses the actual graph.

**Tech Stack:** Python 3.11+, dataclasses, canonical JSON/hash helpers, existing `ModelGraph`/Closure/Gate services, OpenAI-compatible adapter, pytest, Ruff, import-linter, GitHub Actions, and `gh`.

## Global Constraints

- Ground truth is evaluator-only and never enters a model-visible payload.
- Model-produced entities persist as `status=CANDIDATE` and `producer=LLM`; claims are audit data only.
- Technical Closure accepts `VALIDATED | ACCEPTED | LOCKED`; Release Closure accepts `ACCEPTED | LOCKED`; Candidate satisfies neither.
- Empty coverage is `coverage=null`, `status=not_applicable`, and never `1.0`.
- A–E record verifier, gate, repair, and CAS toggles independently.
- Natural and budget-matched modes are explicit; unknown cost is unavailable, not zero.
- Default repeats are three; reports contain mean, sample std, and approximate 95% CI.
- Ordinary CI installs `.[dev,web]`; remote LLM/FreeCAD/GPU work is separate.
- Do not add CAD, MDO, UI, or unrelated Harness features.

## File map

- Create `tests/mbse_benchmark/runners/experiment_contract.py` for envelopes, visibility checks, telemetry, and statistics.
- Modify `tests/mbse_benchmark/cases/loader.py`, `scenarios.py`, `runners/scenario_pipeline.py`, `runners/case_runner.py`, `runners/benchmark_runner.py`, and `runners/report_builder.py` for the single experiment pipeline.
- Modify `tests/mbse_benchmark/validators/case.py` for semantic/governance namespaces; update README and benchmark tests.
- Modify `src/rflp_lite/ports/generative_model.py` and `src/rflp_lite/adapters/openai_compatible_model.py` for transport telemetry.
- Modify `src/rflp_lite/methodology/coverage_status.py`, `coverage_matrix.py`, `vertical_coverage.py`, and `application/projections/traceability.py` only where N/A is not propagated.
- Modify `.github/workflows/ci.yml` and `.github/workflows/integration.yml`; add `tests/integration/test_integration_contract.py`.

## Task 1: Canonical input and evaluator-only ground truth

**Interfaces:** `BenchmarkInputEnvelope.from_case(case)`, `EvaluationSpec.from_expectations(expectations)`, and `assert_model_visible_payload(payload, evaluation_spec)`. `ScenarioRunner.run` consumes the input envelope; `ExternalEvaluator.evaluate` consumes both envelopes explicitly.

- [ ] **Step 1: Write failing tests.** In `tests/mbse_benchmark/test_experiment_contract.py`, assert `BenchmarkInputEnvelope.from_case(CASE).canonical_bytes == canonical_json(CASE).encode()` and its hash equals `canonical_hash(CASE)`. Assert a payload containing `evaluation_spec` raises `ValueError("evaluator-only")`.
- [ ] **Step 2: Run `pytest -q tests/mbse_benchmark/test_experiment_contract.py tests/mbse_benchmark/test_scenario_pipeline.py`; expect failure because the envelope types do not exist.**
- [ ] **Step 3: Implement the envelope with `payload`, `canonical_bytes`, `input_hash`, and `case_id`; use existing canonical helpers, not ordinary JSON serialization. Load expected coverage/conflicts/targets into `EvaluationSpec` only. Recursively reject `evaluation_spec`, `expected`, `ground_truth`, `reference_graph`, and `evaluation_spec_hash` in model payloads.**
- [ ] **Step 4: Put the complete envelope payload, including declared `requirements`, in every A/B request. Make `model_input_for_case` return that same payload for compatibility. Keep expected files out of `case_runner`.**
- [ ] **Step 5: Run focused tests, `git diff --check`, then commit with `git commit -m "feat: isolate benchmark input from evaluation spec"`.**

## Task 2: Authority-safe normalization and closure layers

**Interfaces:** Add `NormalizationAudit(claimed_statuses, claimed_producers, authority_violations)` and `ModelGraphNormalizer.normalize_with_audit(...) -> NormalizedGraph`; keep `normalize(...) -> ModelGraph` as a compatibility wrapper. Evaluator output must contain `semantic_metrics` and `governance_metrics` plus named Technical/Release Closure payloads.

- [ ] **Step 1: Add failing tests in `test_scenario_pipeline.py`: an entity claiming Accepted/User normalizes to Candidate/LLM and records its ID; Candidate fails both gates; Validated-only fails Release Closure.**
- [ ] **Step 2: Run `pytest -q tests/mbse_benchmark/test_scenario_pipeline.py tests/methodology/test_closure_gates.py`; verify the current pass-through normalizer fails.**
- [ ] **Step 3: In `_entity_from_mapping`, preserve requested status/producer as audit data but always call `make_entity(..., status=EntityStatus.CANDIDATE, producer=Producer.LLM)`. Keep semantic payload and relations.**
- [ ] **Step 4: Evaluate semantic metrics on a private status-neutral copy using Validated for trace/coverage calculations. Evaluate actual graph governance with `evaluate_technical_closure` and `evaluate_release_closure`; never persist the semantic copy.**
- [ ] **Step 5: Run benchmark and closure tests, `git diff --check`, and commit with `git commit -m "feat: separate benchmark semantics from governance"`.**

## Task 3: Fair A–E controls and byte-identical Harness input

**Interfaces:** Extend `ScenarioContract` with `generation_shape`, `verifier_enabled`, `gate_enabled`, `repair_enabled`, and `cas_enabled`. A/B controls are off; C has verifier off and gate/repair/CAS on; D has verifier/gate/CAS on and repair off; E has all on. `run_case` consumes `BenchmarkInputEnvelope`.

- [ ] **Step 1: Add failing tests asserting C/D/E controls and that every persisted `input.json` equals `envelope.canonical_bytes + b"\n"`.**
- [ ] **Step 2: Run `pytest -q tests/mbse_benchmark/test_scenario_pipeline.py tests/mbse_benchmark/test_comparison.py`; confirm A/B currently omit requirements and Harness writes a separate raw case.**
- [ ] **Step 3: Add `_write_canonical_input(path, envelope)` using `path.write_bytes(envelope.canonical_bytes + b"\n")`; use it for all five scenarios and persist input hash, byte length, and byte SHA-256.**
- [ ] **Step 4: Make `run_scenario_comparison` reject model/provider/input/task mismatches and invalid ablations. Render all four toggles explicitly.**
- [ ] **Step 5: Run case/comparison tests, `git diff --check`, and commit with `git commit -m "feat: enforce fair A-E benchmark inputs and ablations"`.**

## Task 4: Adapter-boundary model-call telemetry

**Interfaces:** Add `GenerationCallEvent(lens_id, attempt_kind, provider_id, model_id, duration_ms, status, usage, estimated_cost_usd)` and `TelemetrySink`. Add `telemetry_sink: TelemetrySink | None = None` to `OpenAICompatibleModel`. Add `ExperimentTelemetry.from_events(...)` with call counts, repair/failure counts, input/output/total tokens, provider/wall latency, pricing, cost status, comparison mode, budget, and exhaustion.

- [ ] **Step 1: Add a fake-transport test that returns malformed then valid JSON and asserts two events with `attempt_kind` `initial` and `structural_repair`.**
- [ ] **Step 2: Run `pytest -q tests/adapters/test_openai_compatible_model.py`; expect failure because calls are currently hidden behind the final response.**
- [ ] **Step 3: Emit one event around every actual transport attempt, including exceptions and internal structural repair. Count only calls reaching the provider. Pass the same sink through `StructuredModelRuntime` for C/D/E.**
- [ ] **Step 4: Replace response-only usage aggregation and wall-time fallbacks in benchmark metadata with the event ledger. Unknown pricing is `cost_status=unavailable`, not zero.**
- [ ] **Step 5: Run adapter/scenario tests, `git diff --check`, and commit with `git commit -m "feat: record benchmark generation telemetry"`.**

## Task 5: Natural/budget-matched repeats and evidence artifacts

**Interfaces:** Add `ComparisonMode = Literal["natural", "budget_matched"]`; extend `run_scenario_comparison(..., repeats: int = 3, comparison_mode: ComparisonMode = "natural", total_output_token_budget: int | None = None)`. Add `summarize_repeats(records)` and `build_quality_cost_points(...)`. Write `a_to_e_comparison.json`, `a_to_e_comparison.md`, and `reproducibility_manifest.json`.

- [ ] **Step 1: Add failing tests for three-repeat default, sample std, approximate 95% CI, budget exhaustion, and one manifest record per case/scenario/repeat.**
- [ ] **Step 2: Run `pytest -q tests/mbse_benchmark/test_comparison.py`; expect failure because comparison currently defaults to one repeat and has no statistics.**
- [ ] **Step 3: In natural mode retain configured limits. In budget-matched mode apply one total output cap to A–E and decrement remaining budget for staged requests; record `budget_exhausted`.**
- [ ] **Step 4: Use `statistics.stdev` for n>=2 and `1.96 * std / sqrt(n)` for CI. Render semantic/governance namespaces, telemetry, hashes, toggles, repeat statistics, and quality-cost points without fabricating cost.**
- [ ] **Step 5: Run comparison/report tests, `git diff --check`, and commit with `git commit -m "feat: add reproducible comparison statistics"`.**

## Task 6: Unify coverage and report semantics

**Files:** benchmark validator/report builder and `coverage_status.py`, `coverage_matrix.py`, `vertical_coverage.py`, `application/projections/traceability.py`, with coverage/report tests.

- [ ] **Step 1: Add tests asserting empty matrices produce `coverage=None`, `status=not_applicable`, `passed=False`, and reports render `N/A`.**
- [ ] **Step 2: Run `pytest -q tests/methodology/test_coverage_status.py tests/methodology/test_coverage_matrix.py tests/methodology/test_vertical_coverage.py tests/mbse_benchmark/test_reporting.py`; inspect every direct ratio presentation.**
- [ ] **Step 3: Route every aggregate through `coverage_result(covered_count, total_count)` and keep empty vertical stages non-passing. Ensure Candidate-only A/B graphs can have semantic scores from the neutral projection but never pass Release Closure.**
- [ ] **Step 4: Render separate semantic/governance sections, run the same tests, and commit with `git commit -m "fix: unify benchmark coverage semantics"`.**

## Task 7: Truthful CI and schedule-safe Integration workflow

- [ ] **Step 1: Add `tests/integration/test_integration_contract.py` asserting `.github/workflows/integration.yml` has a schedule trigger and an unconditional `contract` job.**
- [ ] **Step 2: Change `.github/workflows/ci.yml` installation to `python -m pip install --upgrade pip && python -m pip install -e ".[dev,web]"`; retain pytest, Ruff, compileall, import-linter, architecture, and robustness commands.**
- [ ] **Step 3: Add a contract job that validates offline setup and clearly fails/blocks when remote profile, FreeCAD service, or GPU runner prerequisites are absent. Keep remote jobs separate; never call offline fallback a remote PASS.**
- [ ] **Step 4: Run `pytest -q tests/integration/test_integration_contract.py`, `python -m compileall -q src tests scripts`, `git diff --check`, then commit with `git commit -m "ci: make quality and integration checks truthful"`.**

## Task 8: Full verification and GitHub delivery

- [ ] **Step 1: Run `pytest -q`, `ruff check src tests scripts`, `python -m compileall -q src tests scripts`, `lint-imports`, `python scripts/architecture_metrics.py`, and `python tests/mbse_benchmark/run_benchmark.py --track robustness`; all must exit 0.**
- [ ] **Step 2: Run a configured selected-case A–E comparison with three repeats and inspect `same_input`, `same_model_provider`, `same_task_spec`, every telemetry `call_count`, both comparison reports, and the reproducibility manifest.**
- [ ] **Step 3: Push `codex/web-audit-2026-08-18`, wait with `gh run watch --exit-status`, and inspect `gh run view --json status,conclusion,url,jobs`; the final commit must have a real successful `CI / quality` check.**
- [ ] **Step 4: Verify `main` protection still requires strict `CI / quality`; query Actions runners, secrets, and variables. Report Remote LLM/FreeCAD/GPU PASS only when real prerequisites are reachable.**
- [ ] **Step 5: Create a PR to `main` containing the commit SHA, local commands, GitHub CI URL, A–E invariants, artifacts, and explicit external integration status. Do not bypass branch protection or claim merge before required checks/reviews are satisfied.**

