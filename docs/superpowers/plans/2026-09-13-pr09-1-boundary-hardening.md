# PR09.1 Boundary Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct incremental payload validation and make Workflow execution fail closed for concurrency, invariant, contract, and unknown execution errors.

**Architecture:** Keep `TaskProposal` and `ProposalCompiler` interfaces unchanged. Validate an update's final merged payload while emitting only the original delta. Add explicit non-semantic failure stages for concurrency and internal execution errors so `WorkflowRunner` and `LifecycleOrchestrator` can persist `FAILED`, block pending tasks, and stop later phases; preserve `MethodologyValidationError` as the known semantic-degradation route.

**Tech Stack:** Python 3, dataclasses, SQLite repository, pytest, ruff, compileall, import-linter.

## Global Constraints

- Do not modify the `TaskProposal` wire contract, prompts, model profile, benchmark fixture, or benchmark working-tree files.
- Preserve PR09 baseline behavior for structural/compiler/transport responses: task `FAILED`, pending tasks `BLOCKED`, semantic repair skipped.
- Preserve the existing public run summary behavior of returning `RunStatus.DEGRADED` for a stopped run while persisting the failed task and failure stage.
- Do not commit unrelated existing worktree changes under `tests/mbse_benchmark/`.
- Validate before any repository append and keep update patches delta-shaped.

---

### Task 1: Fix merged payload validation

**Files:**
- Modify: `src/rflp_lite/methodology/proposal_compiler.py:379-380`
- Test: `tests/methodology/test_proposal_compiler.py`

**Interfaces:**
- Consumes: `TaskExecutionRequest.output_contract["x-payload-schemas"]`, `Entity.payload`, and `ProposalUpdate.field_patch`.
- Produces: the existing `UpdateEntity(entity_id, field_patch)` operation with unchanged delta shape.

- [ ] **Step 1: Write the failing regression tests**

Add `UpdateEntity` and `dataclasses.replace` imports, then append:

```python
def _update_request() -> tuple[TaskExecutionRequest, str]:
    request = _request()
    entity = make_entity(
        EntityKind.REQUIREMENT,
        "原始需求",
        {"obligation": "系统应完成投递", "source": "doc-1"},
    )
    contract = dict(request.output_contract)
    schemas = dict(contract["x-payload-schemas"])
    requirement_schema = dict(schemas[EntityKind.REQUIREMENT.value])
    requirement_schema["required"] = ["obligation", "source"]
    schemas[EntityKind.REQUIREMENT.value] = requirement_schema
    contract["x-payload-schemas"] = schemas
    return replace(
        request,
        context_bundle=replace(request.context_bundle, entities=(entity,)),
        output_contract=contract,
    ), entity.id


def test_partial_payload_update_validates_merged_payload():
    request, entity_id = _update_request()
    payload = _proposal(
        entities=[],
        updates=[{
            "entity_id": entity_id,
            "field_patch": {"payload": {"obligation": "系统应支持人工接管"}},
        }],
    )

    patch = compile_task_proposal(request, payload)

    assert patch is not None
    assert isinstance(patch.operations[0], UpdateEntity)
    assert patch.operations[0].field_patch == {
        "payload": {"obligation": "系统应支持人工接管"}
    }


def test_partial_payload_update_rejects_invalid_final_payload():
    request, entity_id = _update_request()
    payload = _proposal(
        entities=[],
        updates=[{
            "entity_id": entity_id,
            "field_patch": {"payload": {"source": 42}},
        }],
    )

    with pytest.raises(ContractViolation, match="invalid requirement payload"):
        compile_task_proposal(request, payload)
```

The helper must use `context_bundle`, not a new unrelated context field; construct the replacement with `replace(request.context_bundle, ...)`.

- [ ] **Step 2: Run the focused tests and verify the bug is reproduced**

Run:

```bash
./.venv/bin/pytest tests/methodology/test_proposal_compiler.py -q
```

Expected before implementation: `test_partial_payload_update_validates_merged_payload` fails because the partial payload is validated without the existing `source` field.

- [ ] **Step 3: Implement final-state validation with delta preservation**

Replace the current update validation block:

```python
        if "payload" in item.field_patch:
            payload_patch = _mapping(item.field_patch["payload"], "updates.field_patch.payload")
            merged_payload = {**dict(entity.payload), **payload_patch}
            _validate_entity_payload(entity.kind, merged_payload, request)
```

Keep the following operation unchanged:

```python
        operations.append(UpdateEntity(item.entity_id, item.field_patch))
```

- [ ] **Step 4: Run the focused tests**

Run:

```bash
./.venv/bin/pytest tests/methodology/test_proposal_compiler.py -q
```

Expected: all ProposalCompiler tests pass, including both new tests.

- [ ] **Step 5: Commit the isolated compiler fix**

```bash
git add src/rflp_lite/methodology/proposal_compiler.py tests/methodology/test_proposal_compiler.py
git commit -m "fix(pr09.1): validate merged payload updates"
```

### Task 2: Make Workflow exception handling fail closed

**Files:**
- Modify: `src/rflp_lite/methodology/contracts.py:39-47`
- Modify: `src/rflp_lite/methodology/workflow.py:8-16,260-275`
- Modify: `src/rflp_lite/interface/web/resource_api.py:35-50`
- Modify: `src/rflp_lite/interface/web/resource_pages.py:284-300,624-637`
- Test: `tests/methodology/test_workflow.py`

**Interfaces:**
- Consumes: `ConcurrentModificationError`, `WorkflowInvariantError`, `ContractViolation`, `MethodologyValidationError`, and `TaskExecutionResponse`.
- Produces: `FailureStage.CONCURRENCY` and `FailureStage.INTERNAL`, persisted failed steps, blocked pending steps, and a stopped `RunSummary`.

- [ ] **Step 1: Add failing workflow regression tests**

Extend imports in `tests/methodology/test_workflow.py`:

```python
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
```

Add the repository failure double and tests below. The repository exceptions are raised by `append_patch()`, which is inside `WorkflowRunner._run_phase()`'s exception boundary; exceptions raised directly by a runtime are intentionally not used here because `TaskExecutor` owns and normalizes that adapter boundary.

```python
class CommittableRuntime:
    def execute(self, request):
        entity = make_entity(EntityKind.SYSTEM, "候选系统")
        return TaskExecutionResponse(
            StepStatus.COMPLETED,
            Patch.create(
                request.context_bundle.project_id,
                request.task_id,
                (AddEntity(entity),),
                "测试 patch",
                request.context_bundle.revision,
            ),
        )


class RaisingAppendRepository(SQLiteModelRepository):
    def __init__(self, path, error):
        super().__init__(path)
        self.error = error

    def append_patch(self, project_id, patch, expected_revision, *, run_id=None):
        raise self.error


@pytest.mark.parametrize(
    ("error", "stage", "diagnostic"),
    [
        (ContractViolation("contract broken"), FailureStage.INTERNAL, "contract_violation"),
        (RuntimeError("unexpected bug"), FailureStage.INTERNAL, "internal_error"),
    ],
)
def test_fail_closed_append_error_marks_failed_and_blocks_pending(tmp_path, error, stage, diagnostic):
    repository = RaisingAppendRepository(tmp_path / "model.db", error)
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, CommittableRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.failure_stage is stage
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
    assert repository.load_graph("p1").revision == 0
    assert diagnostic in " ".join(summary.diagnostics)


def test_workflow_invariant_fails_closed_before_repository_append(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, InvalidPatchResponseRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.failure_stage is FailureStage.INTERNAL
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
    assert repository.load_graph("p1").revision == 0
    assert "workflow_invariant" in " ".join(summary.diagnostics)


def test_concurrent_modification_fails_closed_before_repository_mutation(tmp_path):
    repository = RaisingAppendRepository(
        tmp_path / "model.db",
        ConcurrentModificationError("stale ModelGraph revision"),
    )
    repository.ensure_project("p1")
    runner = WorkflowRunner(repository, repository, CommittableRuntime())

    summary = runner.run("p1", Phase.OPERATIONAL, force_run=True)
    stored = repository.load_run("p1", summary.run_id)

    assert summary.failure_stage is FailureStage.CONCURRENCY
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
    assert repository.load_graph("p1").revision == 0
    assert "concurrency_conflict" in " ".join(summary.diagnostics)
```

Replace the assertions in `test_non_completed_patch_is_rejected_before_repository_append` with the following state checks while retaining the revision assertion and the existing `non-completed response` diagnostic assertion:

```python
    assert summary.failure_stage is FailureStage.INTERNAL
    stored = repository.load_run("p1", summary.run_id)
    assert stored is not None
    statuses = {step.task_id: step.status for step in stored.steps}
    assert statuses["system_definition"] == "failed"
    assert statuses["stakeholder_analysis"] == "blocked"
```

- [ ] **Step 2: Run the focused workflow tests and verify the old catch-all behavior fails the new expectations**

Run:

```bash
./.venv/bin/pytest tests/methodology/test_workflow.py -q
```

Expected before implementation: the new exception tests fail because the current catch-all persists `DEGRADED` and continues, and the current summary has no internal/concurrency failure stage.

- [ ] **Step 3: Add explicit internal and concurrency failure stages**

Extend `FailureStage` in `src/rflp_lite/methodology/contracts.py`:

```python
class FailureStage(StrEnum):
    STRUCTURAL = "structural"
    COMPILER = "compiler"
    SEMANTIC = "semantic"
    TRANSPORT = "transport"
    CONCURRENCY = "concurrency"
    INTERNAL = "internal"
```

Add `FailureStage.CONCURRENCY` and `FailureStage.INTERNAL` to `_NON_SEMANTIC_FAILURE_STAGES` in `workflow.py`. Add both values to the web API non-semantic set and add Chinese labels `并发冲突` and `内部执行错误` to both failure-stage label maps in `resource_pages.py`.

- [ ] **Step 4: Route semantic validation separately and fail closed for all other exceptions**

Update the workflow imports:

```python
from rflp_lite.domain.errors import (
    ConcurrentModificationError,
    ContractViolation,
    MethodologyValidationError,
    WorkflowInvariantError,
)
```

Replace the current catch-all body with this ordered routing:

```python
            except MethodologyValidationError as exc:
                message = f"{task.id}: semantic validation: {exc}"
                diagnostics.append(message)
                self.run_repository.update_step(Step(
                    identity.run_id, task.id, StepStatus.DEGRADED.value,
                    prior_attempt + 1, context_hash, None, (message,), "",
                    self._provider_id(), self._model_id(), task.prompt_template_id,
                    context_hash, started, time.time(), request.prompt_version,
                    request.prompt_hash, task_spec_hash(task), "none", 0,
                ))
            except ConcurrentModificationError as exc:
                return self._fail_closed_task(
                    project_id, phase, identity, task, request, context_hash,
                    prior_attempt, started, completed, diagnostics, FailureStage.CONCURRENCY,
                    "concurrency_conflict", exc,
                )
            except WorkflowInvariantError as exc:
                return self._fail_closed_task(
                    project_id, phase, identity, task, request, context_hash,
                    prior_attempt, started, completed, diagnostics, FailureStage.INTERNAL,
                    "workflow_invariant", exc,
                )
            except ContractViolation as exc:
                return self._fail_closed_task(
                    project_id, phase, identity, task, request, context_hash,
                    prior_attempt, started, completed, diagnostics, FailureStage.INTERNAL,
                    "contract_violation", exc,
                )
            except Exception as exc:
                return self._fail_closed_task(
                    project_id, phase, identity, task, request, context_hash,
                    prior_attempt, started, completed, diagnostics, FailureStage.INTERNAL,
                    "internal_error", exc,
                )
```

Add this `WorkflowRunner` helper before `_ensure_run()`:

```python
    def _fail_closed_task(
        self, project_id, phase, identity, task, request, context_hash,
        prior_attempt, started, completed, diagnostics, failure_stage, code, exc,
    ) -> RunSummary:
        message = f"{task.id}: {code}: {type(exc).__name__}: {exc}"
        diagnostic = f"{failure_stage.value}:{code}: {message}"
        diagnostics.append(diagnostic)
        self.run_repository.update_step(Step(
            identity.run_id, task.id, StepStatus.FAILED.value,
            prior_attempt + 1, context_hash, None, (diagnostic,),
            canonical_hash(diagnostic), self._provider_id(), self._model_id(),
            task.prompt_template_id, context_hash, started, time.time(),
            request.prompt_version, request.prompt_hash, task_spec_hash(task),
            "none", 0,
        ))
        self._block_pending_steps(
            project_id,
            identity.run_id,
            f"blocked by {task.id} {failure_stage.value} failure",
            after_task_id=task.id,
        )
        self._update_run_status(identity.run_id, RunStatus.DEGRADED, tuple(diagnostics))
        return RunSummary(
            identity.run_id,
            project_id,
            phase,
            RunStatus.DEGRADED,
            tuple(sorted(completed)),
            tuple(diagnostics),
            failure_stage=failure_stage,
        )
```

The `MethodologyValidationError` route must continue the loop so known semantic defects remain eligible for existing gate/repair handling. Every other exception returns immediately and therefore cannot reach the next task.

- [ ] **Step 5: Run the focused workflow tests**

Run:

```bash
./.venv/bin/pytest tests/methodology/test_workflow.py -q
```

Expected: all workflow tests pass; failed tasks are persisted as `failed`, pending tasks as `blocked`, and the model revision remains unchanged for the exception tests.

- [ ] **Step 6: Commit the fail-closed workflow fix**

```bash
git add src/rflp_lite/methodology/contracts.py src/rflp_lite/methodology/workflow.py src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/resource_pages.py tests/methodology/test_workflow.py
git commit -m "fix(pr09.1): fail closed on workflow execution errors"
```

### Task 3: Run the complete verification suite

**Files:**
- Inspect only: `pyproject.toml`, `.importlinter`, `tests/architecture/`
- No source edits unless a failure is directly caused by Tasks 1–2.

**Interfaces:**
- Consumes: the two committed P1 fixes and all existing PR09 tests.
- Produces: verified test, lint, compilation, import-boundary, and architecture-metric results.

- [ ] **Step 1: Run focused regression tests together**

```bash
./.venv/bin/pytest tests/methodology/test_proposal_compiler.py tests/methodology/test_workflow.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the full Python test suite**

```bash
./.venv/bin/pytest -q
```

Expected: PASS with no benchmark files staged or changed by the test run.

- [ ] **Step 3: Run static and bytecode checks**

```bash
./.venv/bin/ruff check src tests
./.venv/bin/python -m compileall -q src tests
```

Expected: both commands exit 0.

- [ ] **Step 4: Run architecture checks**

```bash
./.venv/bin/lint-imports
./.venv/bin/pytest tests/architecture/test_dependency_boundaries.py tests/architecture/test_architecture_budget.py -q
```

Expected: all defined import contracts and architecture metrics pass.

- [ ] **Step 5: Review the final worktree and commits**

```bash
git status --short
git log -3 --oneline
```

Expected: the two P1 implementation commits and the design/plan documentation are present; unrelated pre-existing `tests/mbse_benchmark/` changes remain unstaged and uncommitted.
