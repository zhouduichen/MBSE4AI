# MBSE4AI v0.3.2 — Fair Evaluation & Reproducible Evidence

## Status

Proposed design for implementation after review.

## Goal

Make the A–E benchmark a fair, reproducible experiment and close the remaining engineering gaps without expanding peripheral CAD/MDO functionality.

The benchmark must compare the same model on the same declared task input, normalize every output into the same `ModelGraph` schema, evaluate every graph with the same external evaluator, and report semantic quality separately from governance and lifecycle quality.

## Non-goals

- Adding new CAD, MDO, or other peripheral product capabilities.
- Treating a local/offline fallback as evidence of a real remote-model, FreeCAD, or GPU integration pass.
- Sending evaluator-only expected graphs or criteria to the model.
- Allowing a model response to grant itself user authority or an Accepted/Locked lifecycle state.

## Experiment boundary

Each case is split into two explicit objects:

```text
BenchmarkInputEnvelope  -> model-visible, canonical task input
EvaluationSpec           -> evaluator-only expectations and criteria
```

`BenchmarkInputEnvelope` contains the case brief, declared requirements and constraints, stakeholders, lifecycle stages, scenarios, and any other information that a participant is legitimately allowed to use. It is serialized once using canonical JSON and the exact bytes are reused by A–E. Its byte hash is the authoritative `input_hash` for the run.

`EvaluationSpec` contains expected coverage, expected trace links, conflict rules, metric targets, and other ground truth. It is loaded only by `ExternalEvaluator`; no model request, prompt, staged state, Harness ingest payload, or report input may contain it.

The runner must fail before execution if any scenario has a different canonical input byte sequence or if evaluator-only data appears in a model-visible payload. The manifest records both `input_hash` and `evaluation_spec_hash`, but only the former is shared with the model execution boundary.

## Unified execution pipeline

All scenarios use one pipeline:

```text
ScenarioContract
  -> BenchmarkInputEnvelope
  -> ScenarioRunner
  -> ModelGraphNormalizer
  -> ExternalEvaluator
  -> ReportBuilder
```

The `ScenarioContract` is the single source of truth for scenario identity, control toggles, prompt template, model configuration, budget mode, repeat count, and metadata. Legacy benchmark tracks must delegate to this pipeline or be removed from the runnable surface.

## ModelGraph normalization and authority

The normalizer is a trust boundary, not a pass-through deserializer. For every model-produced entity it must:

1. Preserve the model's requested lifecycle and producer as `claimed_status` and `claimed_producer` for audit.
2. Force the persisted benchmark entity to `status=CANDIDATE` and `producer=LLM`.
3. Emit an `authority_violation` when the response claims `ACCEPTED`, `LOCKED`, `USER`, or another authority that the model does not possess.
4. Keep semantic content available for evaluation even when governance claims are invalid.

The same normalizer is used for A–E. Harness services may advance entities through verifier, acceptance policy, and user-controlled lifecycle transitions, but the benchmark must report those transitions separately from the model's raw claims.

## Closure semantics

The implementation exposes two explicit gates:

```text
TechnicalClosure -> all required R/F/L/P/V&V facts are VALIDATED or stronger
ReleaseClosure   -> all required R/F/L/P/V&V facts are ACCEPTED or LOCKED
```

`CANDIDATE` never satisfies either gate. `VALIDATED` can satisfy Technical Closure but never Release Closure. Missing required entities, zero Accepted Requirements, or an incomplete required layer causes Release Closure to fail. Reports must identify which gate was evaluated and must not collapse the two gates into one boolean.

## Orthogonal A–E controls

The five scenarios use the same model, provider, task input, normalizer, evaluator, and comparable output-token budget.

| Scenario | Generation shape | Verifier | Gate | Repair | CAS |
|---|---|---:|---:|---:|---:|
| A Bare one-shot | One request for complete R→F→L→P→V&V | off | off | off | off |
| B Bare staged | Simple staged requests for R/F/L/P/V&V | off | off | off | off |
| C Harness – Verifier | Harness execution | on | on | on | on |
| D Harness – Repair | Harness execution | on | on | off | on |
| E Full Harness | Harness execution | on | on | on | on |

C/D/E are required to be orthogonal ablations. C, D, and E must differ only in the declared control under test; the contract records any necessary implementation-level distinction between verifier-driven repair and generation-time structural repair. If a control cannot be disabled independently, the runner fails rather than silently reporting an invalid ablation.

The comparison manifest must include `verifier_enabled`, `gate_enabled`, `repair_enabled`, `cas_enabled`, and the effective prompt/task/model settings for every run.

## Metrics

Reports have two non-interchangeable namespaces.

### Semantic metrics

These measure what the graph says:

- requirement/function/logical/physical/V&V counts;
- trace accuracy and trace completeness;
- RFLP coverage;
- evaluator conflicts and correctness scores;
- Technical Closure result.

### Governance metrics

These measure whether the graph is safely governable:

- authority violations;
- lifecycle claim violations;
- actual status distribution;
- verifier and gate outcomes;
- repair events;
- CAS events and graph identity;
- Release Closure result.

Model self-declarations must never be used as evidence of governance success. A/B may have strong semantic scores while failing governance because their outputs remain model-authored candidates.

Coverage has one three-state representation everywhere: `PASS`, `FAIL`, or `N/A`. For an empty denominator, the JSON form is:

```json
{
  "requirement_count": 0,
  "covered_count": 0,
  "coverage": null,
  "status": "not_applicable"
}
```

No report, API, or Web UI may render empty coverage as `1.0` or as a passing closure. The same representation is used by `coverage_matrix.py`, `vertical_coverage.py`, Traceability Report, Benchmark Report, and the Web UI.

## Telemetry and reproducibility

Every scenario repeat emits a complete `ExperimentTelemetry` record:

```text
call_count
initial_call_count
repair_call_count
failed_call_count
input_tokens
output_tokens
total_tokens
provider_latency_ms
wall_latency_ms
input_cost_per_1m_tokens
output_cost_per_1m_tokens
estimated_cost_usd
cost_status
comparison_mode
total_output_token_budget
budget_exhausted
budget_within_cap
```

Telemetry is collected at the adapter transport boundary so every real provider call is counted, including calls made during structural repair. Aggregated response metadata is insufficient when a runtime batches requests or hides repair calls.

Two supported modes are explicit:

- `natural`: each scenario uses its normal configured generation limits;
- `budget_matched`: all scenarios receive the same positive total output-token cap, and staged runs receive the remaining cap after each call. A provider must report output-token usage; otherwise the adapter fails closed. The comparison rejects any repeat whose measured output exceeds the cap and the manifest records both `budget_exhausted` and `budget_within_cap`.

Token usage, call count, latency, and estimated cost are real measured values when the provider supplies usage and pricing metadata. Unknown pricing is reported as `cost_status=unavailable`, never as zero cost.

## Repeats and statistics

The comparison runner defaults to three repeats and accepts five or more for publication runs. Each repeat gets a stable repeat index and its own telemetry, graph hash, metric results, and seed/configuration record.

The report includes per-scenario mean, sample standard deviation, and an approximate 95% confidence interval for numeric semantic, governance, latency, token, call, and cost metrics. It also includes Quality-Cost points using the declared quality metric and measured cost; missing cost cannot be converted into a fabricated zero.

The output artifacts are:

```text
a_to_e_comparison.json
a_to_e_comparison.md
reproducibility_manifest.json
```

The manifest records, for every repeat:

```text
scenario
model
provider
prompt_hash
task_spec_hash
temperature
input_hash
evaluation_spec_hash
token usage
call_count
latency
estimated cost
graph_hash
verifier_enabled
gate_enabled
repair_enabled
cas_enabled
comparison_mode
repeat_index
```

## CI and integration contract

The ordinary CI workflow installs both test dependency groups:

```bash
python -m pip install -e ".[dev,web]"
```

Every push and pull request runs:

```bash
pytest -q
ruff check src tests scripts
python -m compileall -q src tests scripts
lint-imports
python scripts/architecture_metrics.py
python tests/mbse_benchmark/run_benchmark.py --track robustness
```

The Integration workflow must contain a schedule-safe contract job that runs on every scheduled invocation and fails clearly when required external configuration is missing. Remote LLM, FreeCAD, and GPU jobs are separate jobs with explicit secrets, runner labels, and reachability checks. They must not be represented as PASS when credentials, runners, or software are absent.

The current repository audit found no configured self-hosted GPU runner, no Actions variables, and no Actions secrets. Those are external prerequisites for real remote integration evidence; code changes may make the jobs truthful and actionable but cannot manufacture that infrastructure.

`main` retains branch protection requiring the real `CI / quality` check. Completion requires a GitHub CI PASS for the final implementation commit, not only a local test result.

## Verification plan

The implementation must add or update tests for:

1. byte-identical A–E input and stable `input_hash`;
2. evaluator-only ground truth isolation;
3. forced candidate/LLM normalization and authority-violation reporting;
4. Technical Closure versus Release Closure;
5. independent C/D/E controls;
6. real call, repair, token, latency, and cost telemetry;
7. natural and budget-matched modes;
8. repeat statistics and Quality-Cost output;
9. empty coverage as `N/A` across all report surfaces;
10. CI dependency installation and schedule-safe integration behavior.

Local verification must pass pytest, Ruff, compileall, import lint, architecture budgets, and the robustness benchmark. The final handoff must include the local evidence, the GitHub run URL/status, the commit SHA, and any external integration checks that remain blocked by missing runners or credentials.
