# Trusted Closure & Experimental Validity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task with a test checkpoint after each task.

**Goal:** Make Closure, lifecycle authority, verifier retry, leases, task permissions, and benchmark conclusions enforceable system invariants.

**Architecture:** Add a pure closure/lifecycle policy layer above `ModelGraph`, then make repository CAS and `WorkflowRunner` enforce run ownership and lifecycle authority. Reuse the existing typed validators and benchmark result format, but require every path to pass through the same strict evaluator and real fault-injection operations.

**Tech Stack:** Python 3.11+, dataclasses, SQLite transactions, pytest, existing `ModelGraph`/`TaskSpec`/benchmark harness.

## Global Constraints

- Closure must reject an empty or non-accepted requirement scope.
- Generic methodology patches cannot write `status` or `producer`.
- Only fully validated patches may reach CAS.
- A failed run claim and an expired lease terminate/reject work.
- `allowed_predicates=None` must never expand to all predicates.
- Every acceptance criterion in the v0.3 design spec requires an executable test.

---

### Task 1: Strict closure semantics

**Files:**
- Create: `src/rflp_lite/methodology/closure.py`
- Modify: `src/rflp_lite/methodology/coverage_matrix.py`
- Modify: `src/rflp_lite/methodology/vertical_coverage.py`
- Modify: `src/rflp_lite/methodology/gates.py`
- Modify: `src/rflp_lite/application/closure_service.py`
- Test: `tests/methodology/test_strict_closure.py`

**Interfaces:**
- `evaluate_strict_closure(graph: ModelGraph, *, issue_records=(), requirement_ids=None) -> ClosureAssessment`.
- `ClosureAssessment.passed: bool`, `.issues: tuple[ClosureIssue, ...]`, `.requirement_ids: tuple[str, ...]`, and `.as_dict()`.
- `global_gate(graph)` and `ClosureService.close()` both consume this evaluator.

- [ ] **Step 1: Write failing negative tests**

Add tests that build small graphs using `make_entity`, `Relation`, and
`ModelGraph` and assert that empty requirements, candidate requirements,
missing R→F, missing logical/physical links, missing V&V, placeholders,
human-review flags, and open issues all fail. Add a complete accepted graph
fixture and assert that it passes.

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `pytest tests/methodology/test_strict_closure.py -q`

Expected: collection or assertion failures because no strict evaluator exists
and the current gates permit an empty accepted set.

- [ ] **Step 3: Implement the pure strict evaluator**

Use the accepted/locked requirement set as the closure scope. Return explicit
codes such as `empty_requirement_scope`, `requirement_not_accepted`,
`missing_function`, `missing_logical`, `missing_physical`,
`missing_verification`, `missing_validation`, `candidate_in_scope`,
`fallback_placeholder`, `requires_human_review`, and `open_issue`. Treat
empty coverage ratios as `0.0` in `coverage_matrix.py`; ratios remain
diagnostic and never decide Closure.

- [ ] **Step 4: Route gates and ClosureService through the evaluator**

Make `rflp_gate` fail when the accepted requirement scope is empty, make
`global_gate` include strict V&V/lifecycle checks, and make `ClosureService`
pass repository issue records into `evaluate_strict_closure` before saving or
freezing a manifest.

- [ ] **Step 5: Run focused and regression tests**

Run: `pytest tests/methodology/test_strict_closure.py tests/e2e/test_vertical_model_generation.py -q`

Expected: all strict closure tests pass; any legacy test that expected vacuum
coverage is updated to the new explicit `0.0`/FAIL semantics.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/methodology/closure.py src/rflp_lite/methodology/coverage_matrix.py src/rflp_lite/methodology/vertical_coverage.py src/rflp_lite/methodology/gates.py src/rflp_lite/application/closure_service.py tests/methodology/test_strict_closure.py
git commit -m "feat: enforce strict closure semantics"
```

### Task 2: Lifecycle state machine and review authority

**Files:**
- Create: `src/rflp_lite/domain/lifecycle_policy.py`
- Modify: `src/rflp_lite/domain/model.py`
- Modify: `src/rflp_lite/methodology/validators/patch_policy.py`
- Modify: `src/rflp_lite/application/review_service.py`
- Modify: `src/rflp_lite/methodology/executor.py`
- Modify: `src/rflp_lite/methodology/workflow.py`
- Test: `tests/domain/test_entity_lifecycle_policy.py`
- Test: `tests/application/test_review_authority.py`

**Interfaces:**
- `LifecycleActor = Literal["llm", "verifier", "user", "acceptance_policy", "rule"]`.
- `transition_status(current, target, actor, *, authority=None) -> LifecycleTransitionDecision`.
- `validate_patch_lifecycle(graph, patch, *, authority=None) -> None`.

- [ ] **Step 1: Write failing transition and bypass tests**

Cover allowed transitions, illegal skips, generic `UpdateEntity` status/producer
writes, verifier-only validation, user-only acceptance/unlock, locked AI
mutation, and review edit invalidation. Assert audit records contain actor,
previous/next status, reason, and affected entity IDs.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `pytest tests/domain/test_entity_lifecycle_policy.py tests/application/test_review_authority.py -q`

Expected: failures because `apply_patch` currently accepts status and producer
fields based on task IDs rather than an explicit authority.

- [ ] **Step 3: Implement the explicit lifecycle policy**

Define only `candidate→validated`, `validated→accepted`, `candidate→accepted`
when an acceptance policy token is present, `accepted→locked`, and
`locked→accepted` for a user unlock. Make LLM output creation candidate-only;
the executor's verifier promotion uses a verifier authority object.

- [ ] **Step 4: Guard generic patch and route ReviewService**

Reject `status` and `producer` from normal task `Patch` operations, require a
typed authority for verifier promotion, and make ReviewService the only manual
edit path. After a user edit, set status to candidate, add provenance/audit,
and persist impact invalidation for downstream trace entities.

- [ ] **Step 5: Run focused review tests and existing review API tests**

Run: `pytest tests/domain/test_entity_lifecycle_policy.py tests/application/test_review_authority.py tests/interface/web/test_review_actions.py -q`

Expected: all authority and stale-trace assertions pass.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/domain/lifecycle_policy.py src/rflp_lite/domain/model.py src/rflp_lite/methodology/validators/patch_policy.py src/rflp_lite/application/review_service.py src/rflp_lite/methodology/executor.py src/rflp_lite/methodology/workflow.py tests/domain/test_entity_lifecycle_policy.py tests/application/test_review_authority.py
git commit -m "feat: enforce entity lifecycle authority"
```

### Task 3: Verifier-grounded retry loop

**Files:**
- Modify: `src/rflp_lite/methodology/contracts.py`
- Modify: `src/rflp_lite/methodology/executor.py`
- Modify: `src/rflp_lite/methodology/workflow.py`
- Modify: `src/rflp_lite/methodology/validators/__init__.py`
- Create: `src/rflp_lite/methodology/validation_feedback.py`
- Test: `tests/methodology/test_verifier_grounded_retry.py`

**Interfaces:**
- `ValidationFeedback(code, affected_entities, expected, actual, failing_relation, evidence_gap, retry_count)`.
- `TaskExecutionResponse.validation_feedback: tuple[ValidationFeedback, ...]`.
- `TaskExecutor.execute(..., feedback=()) -> TaskExecutionResponse`.

- [ ] **Step 1: Write failing retry tests**

Use a scripted runtime that returns one invalid patch and then one valid patch.
Assert the first attempt is not appended, the second request receives exact
feedback, the step ledger records both attempts, and only the valid patch is
committed. Add a max-attempt test that routes to repair/review without CAS.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `pytest tests/methodology/test_verifier_grounded_retry.py -q`

Expected: the existing executor returns diagnostics but no typed feedback and
the workflow can commit after a weaker completion check.

- [ ] **Step 3: Add typed feedback and validator aggregation**

Convert `MethodologyValidationError` and completion failures into bounded
`ValidationFeedback` records. Include affected IDs from the active patch,
expected/actual values, relation names where applicable, and an evidence gap
when evidence validation fails.

- [ ] **Step 4: Feed feedback into revision and commit only after validation**

Make each retry construct a new request with the feedback payload, run all
registered validators again, and return a committable response only when every
validator passes. Move any promotion/append operation after this validation
boundary.

- [ ] **Step 5: Run retry, repair, and workflow tests**

Run: `pytest tests/methodology/test_verifier_grounded_retry.py tests/e2e/test_targeted_repair_loop.py tests/e2e/test_repair_stalled.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/methodology/contracts.py src/rflp_lite/methodology/executor.py src/rflp_lite/methodology/workflow.py src/rflp_lite/methodology/validators/__init__.py src/rflp_lite/methodology/validation_feedback.py tests/methodology/test_verifier_grounded_retry.py
git commit -m "feat: add verifier-grounded retry feedback"
```

### Task 4: Run lease ownership and CAS safety

**Files:**
- Modify: `src/rflp_lite/repository/port.py`
- Modify: `src/rflp_lite/repository/sqlite.py`
- Modify: `src/rflp_lite/methodology/workflow.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Modify: `src/rflp_lite/repository/migrations.py`
- Test: `tests/repository/test_run_lease_safety.py`
- Test: `tests/methodology/test_workflow_lease_safety.py`

**Interfaces:**
- `RunRepository.assert_lease(project_id, run_id, lease, now) -> None`.
- `RunRepository.release_run(project_id, run_id, lease, now) -> None`.
- `ModelRepository.append_patch(..., run_id=None, lease=None) -> Revision`.

- [ ] **Step 1: Write failing race and expiry tests**

Use two repository instances against one SQLite file to assert exactly one
claim succeeds. Assert failed claim never calls the model, heartbeat rejects a
wrong owner, expired ownership cannot CAS, and a `finally` release clears the
lease after success or failure.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `pytest tests/repository/test_run_lease_safety.py tests/methodology/test_workflow_lease_safety.py -q`

- [ ] **Step 3: Add atomic owner-checked repository operations**

Implement `assert_lease`, `release_run`, and lease-aware `append_patch` inside
the same SQLite transaction. Use an explicit configurable lease timeout and
check both owner and heartbeat freshness; never treat an old owner as valid.

- [ ] **Step 4: Guard WorkflowRunner/model generation boundaries**

Acquire once, return a terminal blocked result when `claim_run` is false, and
check the lease before and after model calls, batch calls, repair, promotion,
and CAS. Release in `finally`; a lost lease records a concurrency failure and
does not continue downstream work.

- [ ] **Step 5: Run lease and full workflow regression tests**

Run: `pytest tests/repository/test_run_lease_safety.py tests/methodology/test_workflow_lease_safety.py tests/methodology/test_workflow.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/repository/port.py src/rflp_lite/repository/sqlite.py src/rflp_lite/methodology/workflow.py src/rflp_lite/application/model_generation.py src/rflp_lite/repository/migrations.py tests/repository/test_run_lease_safety.py tests/methodology/test_workflow_lease_safety.py
git commit -m "feat: enforce run lease ownership"
```

### Task 5: Explicit least-privilege contracts for all legacy tasks

**Files:**
- Modify: `src/rflp_lite/methodology/policy.py`
- Modify: `src/rflp_lite/methodology/contracts.py`
- Modify: `src/rflp_lite/methodology/tasks.py`
- Modify: `src/rflp_lite/methodology/executor.py`
- Modify: `src/rflp_lite/methodology/validators/patch_policy.py`
- Test: `tests/methodology/test_task_contracts.py`

**Interfaces:**
- `TaskSpec.precondition: str` and `TaskSpec.postcondition: str`.
- `PatchPolicy.require_explicit_predicates: bool = True`.
- `task_contract_snapshot() -> tuple[Mapping[str, object], ...]`.

- [ ] **Step 1: Write catalog contract tests**

Assert every catalog task has non-empty input/output declarations, explicit
predicates, writable fields, an entity scope, an operation bound, and named
pre/postconditions. Assert the four core trace tasks allow only their stated
predicates and reject cross-scope writes.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `pytest tests/methodology/test_task_contracts.py -q`

- [ ] **Step 3: Make omitted predicates fail closed**

Change `PatchPolicy.for_task(..., allowed_predicates=None)` to raise a contract
error during catalog construction. Supply explicit predicate sets for all
legacy tasks; use an empty set where a task cannot create relations.

- [ ] **Step 4: Add pre/postcondition metadata and enforcement**

Add explicit strings/identifiers to each `TaskSpec`, include them in the task
hash and output contract, and invoke the deterministic precondition before
execution and postcondition after validator success.

- [ ] **Step 5: Run contract, schema, and executor tests**

Run: `pytest tests/methodology/test_task_contracts.py tests/methodology/test_executor.py tests/methodology/test_task_catalog.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/methodology/policy.py src/rflp_lite/methodology/contracts.py src/rflp_lite/methodology/tasks.py src/rflp_lite/methodology/executor.py src/rflp_lite/methodology/validators/patch_policy.py tests/methodology/test_task_contracts.py
git commit -m "feat: make task contracts least privilege"
```

### Task 6: Real benchmark tracks and shared evaluator

**Files:**
- Modify: `tests/mbse_benchmark/tracks/harness.py`
- Modify: `tests/mbse_benchmark/tracks/llm.py`
- Modify: `tests/mbse_benchmark/tracks/robustness.py`
- Modify: `tests/mbse_benchmark/runners/benchmark_runner.py`
- Modify: `tests/mbse_benchmark/runners/case_runner.py`
- Create: `tests/mbse_benchmark/validators/trusted_closure.py`
- Modify: `tests/mbse_benchmark/validators/case.py`
- Test: `tests/mbse_benchmark/test_trusted_closure_benchmark.py`

**Interfaces:**
- `evaluate_trusted_graph(case, graph, issues, audit) -> Mapping[str, object]`.
- `inject_fault(graph, fault) -> FaultInjectionResult`.
- `run_track(case, track_id) -> normalized result with graph and evaluator output`.

- [ ] **Step 1: Write failing benchmark validity tests**

Run each A/B/C/D/E track on a fixture and assert that all outputs are
normalized to the same graph shape. Inject a missing R→F link and require the
evaluator to return the exact requirement ID, apply repair, pass afterward,
and preserve the hash of unrelated entities/relations. Assert Harness metrics
come from observed operations rather than a boolean shortcut.

- [ ] **Step 2: Run focused tests to verify failure**

Run: `pytest tests/mbse_benchmark/test_trusted_closure_benchmark.py -q`

- [ ] **Step 3: Implement the shared trusted evaluator and fault injection**

Use the production strict closure/gate functions against the normalized graph.
Represent each fault as a real patch/deletion on a copy, record detection and
root-cause IDs, call the existing repair path, rerun the verifier, and compare
unrelated canonical projections.

- [ ] **Step 4: Make A/B/C/D/E use the same evaluator**

Keep model generation differences in the track runners only. Remove direct
metric constants and derive `closure`, `gate_detection`, `repair_recovery`,
`cas_lock_protection`, and determinism from run ledger, graph revisions, audit,
and evaluator output.

- [ ] **Step 5: Run benchmark tests and deterministic repeats**

Run: `pytest tests/mbse_benchmark -q` and then
`python -m tests.mbse_benchmark.run_benchmark --repeats 2 --offline`.

Expected: every track has a normalized graph and explicit evidence for its
claims; fault injection recovery and unrelated-delta checks pass.

- [ ] **Step 6: Commit**

```bash
git add tests/mbse_benchmark
git commit -m "test: make benchmark validity evidence real"
```

### Task 7: Full completion audit

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Create: `docs/verification/2026-09-21-v03-trusted-closure-acceptance.md`

- [ ] **Step 1: Run all automated checks**

Run: `pytest -q`, `python -m compileall -q src tests`, and the repository's
architecture/ruff checks.

- [ ] **Step 2: Inspect every hard acceptance criterion**

Record the exact test name and output for empty/partial Closure, lifecycle
bypass, locked mutation, two-worker claim, expired-lease CAS, retry feedback,
precise repair, stale revision, and deterministic hash.

- [ ] **Step 3: Update development evidence without overstating remote quality**

Document offline versus remote-provider results separately, including any
provider limitations and whether the result is semantic LLM quality or a
deterministic bridge.

- [ ] **Step 4: Commit the acceptance evidence**

```bash
git add docs/DEVELOPMENT_STATUS.md docs/verification/2026-09-21-v03-trusted-closure-acceptance.md
git commit -m "docs: record v0.3 trusted closure acceptance"
```
