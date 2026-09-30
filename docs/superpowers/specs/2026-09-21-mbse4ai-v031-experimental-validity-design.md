# MBSE4AI v0.3.1 — Experimental Validity & Engineering Closure

## Goal

Make the benchmark a reproducible same-model comparison and make engineering closure and coverage semantics explicit without expanding CAD/MDO or other peripheral capabilities.

## Context and constraints

- A–E must use the same model, provider, input, comparable token budget, `ModelGraph` schema, and external evaluator.
- A is one-shot generation; B is staged bare generation; C disables deterministic verification; D disables repair; E is the full Harness.
- A/B must not read expected graphs or use `bare_model_graph()` as an answer generator.
- `TechnicalClosure` accepts ready `VALIDATED`, `ACCEPTED`, or `LOCKED` facts; `ReleaseClosure` requires `ACCEPTED` or `LOCKED` facts across Requirement, Function, Logical, Physical, Verification, and Validation entities.
- Empty coverage is `N/A`: `coverage: null`, `status: "not_applicable"`; it must not be represented as a passing `1.0` or an ordinary failing `0.0`.
- Ordinary CI remains offline and deterministic. Remote LLM, FreeCAD, and GPU integration runs are manual/nightly only.

## Design

### 1. One benchmark pipeline

The benchmark will have one contract-driven execution path:

```text
ScenarioContract
  -> ScenarioRunner
  -> ModelGraphNormalizer
  -> ExternalEvaluator
  -> ReportBuilder
```

`ScenarioContract` owns only the scenario identity and capability switches. `ScenarioRunner` receives an injected model/runtime and the same case input for every scenario. Bare scenarios call that model directly: A makes one structured generation request for the complete RFLP+V&V graph, while B makes a sequence of requests using the same model and task input. Harness scenarios invoke the existing workflow with verifier, repair, and CAS switches from the contract.

The normalizer is the only boundary that converts model or Harness output into the canonical `ModelGraph` representation. The external evaluator consumes only that graph plus the case specification; it never evaluates a scenario-specific payload. Existing case validators remain the benchmark's external evaluator implementation, with schema-level LLM metrics added to the same report rather than calculated by a separate bare-baseline path.

Every run emits a JSON-serializable metadata record containing:

```text
scenario, model, provider, prompt_hash, task_spec_hash, temperature,
input_hash, token_usage, latency_ms, graph_hash,
verifier_enabled, repair_enabled, cas_enabled
```

The legacy `bare_llm_requirement_extraction` request and `bare_model_graph()` helper will be removed from the experiment path. A compatibility failure should be explicit rather than silently constructing ground-truth output.

### 2. Two closure gates

The closure module will expose a shared assessment primitive with a required minimum status set. `evaluate_technical_closure()` uses `{VALIDATED, ACCEPTED, LOCKED}` as ready statuses. `evaluate_release_closure()` uses `{ACCEPTED, LOCKED}` and is the strict release gate. Both reject an empty Requirement scope, Candidate facts, placeholders, unresolved human review, missing trace stages, incomplete V&V plans, and open issues.

The existing strict-closure API remains as a compatibility alias to ReleaseClosure during migration, while result payloads identify the gate (`technical` or `release`) and its accepted status set. Tests will explicitly prove that a Validated-only downstream graph passes TechnicalClosure but fails ReleaseClosure, and that zero accepted requirements fails ReleaseClosure.

### 3. Canonical three-state coverage

Coverage results will use a shared `CoverageStatus` and helper. A non-empty scope produces `PASS` or `FAIL` with a numeric ratio. An empty scope produces `N/A` with `coverage: null` and zero counts. Matrix metrics, vertical stage checks, benchmark reports, traceability projections, deliverable reports, and Web API serialization will use this helper. Existing boolean `passed` fields remain only as derived compatibility fields where callers still require them; they must not change the canonical status.

### 4. CI boundaries

`.github/workflows/ci.yml` will run on pushes and pull requests and execute pytest, Ruff, compileall, import-linter, architecture metrics, and the offline robustness benchmark. A separate manual/nightly integration workflow will be limited to configured remote LLM, FreeCAD, and GPU checks; no credentials or external service dependency enters ordinary CI.

The workflow will use the repository's existing `uv.lock`/Python packaging conventions and fail if any required check fails. Branch protection itself is a GitHub repository setting and cannot be changed from this local worktree; the workflow will document the required `main` status check name for administrators to mark as required.

## Error handling and reproducibility

- Missing model configuration fails an explicit LLM benchmark invocation before any report is written.
- A model timeout or malformed structured response becomes a failed scenario result with error metadata; it cannot be replaced by expected-graph data.
- Hashes are computed from canonical JSON with stable ordering and exclude secrets.
- Token usage and latency are recorded when the provider exposes them; otherwise the report records `null`, not a fabricated zero.
- Reports include the scenario contract and all run metadata so two results can be compared without inspecting process logs.

## Verification

Unit and integration tests will cover:

1. A/B call the injected model and never call expected-graph constructors.
2. All five scenarios normalize to the same graph schema and use the same evaluator.
3. Metadata is complete and hashes are deterministic.
4. Technical vs Release Closure status rules, including Candidate and empty-scope failures.
5. Empty matrix and vertical coverage serialize as `N/A`/`null`.
6. Reports and Web API use the same coverage status.
7. The CI commands and robustness benchmark are executable in the repository's offline environment.

## Acceptance criteria

- No benchmark baseline writes `trace_accuracy=0` or `RFLP_coverage=0` as a structural claim; those values are computed from the normalized graph and evaluator and may be `N/A` only when the metric has no applicable scope.
- A/B use the same configured model/provider as E and do not consume expected graphs.
- `ReleaseClosure` rejects Candidate and Validated-only facts; `TechnicalClosure` can accept Validated-only facts.
- `0 Requirement` and `0 Accepted Requirement` are both non-passing release outcomes, with coverage represented as `N/A` where applicable.
- The required CI commands are represented in GitHub workflow configuration and pass locally wherever the environment provides the command.
