# AI4MBSE Harness Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every P0, P1, and P2 requirement from `AI4MBSE_Harness_项目检查与修改建议_v1.0.docx` while preserving the existing ModelGraph, SQLite, Patch/CAS, single-Phase debug API, and offline RuleRuntime.

**Architecture:** Keep domain and repository as stable boundaries. Add runtime selection, task registries, TaskExecutor, retrieval-aware context, LifecycleOrchestrator, Gate/Repair routing, audit/Closure services, and Web workflow presentation above those boundaries. Each layer communicates through typed dataclasses and narrow ports; adapters never depend on application services.

**Tech Stack:** Python 3.11+, dataclasses, SQLite, FastAPI, Jinja2, JSON Schema, pytest, Hypothesis, Ruff, import-linter, uv build, and the existing OpenAI-compatible model adapter.

## Global Constraints

- Product version remains `rflp-lite 0.1.0`.
- Methodology protocol remains `v2.0`.
- Python requirement remains `>=3.11`.
- `jsonschema>=4.23` becomes a base dependency because project creation and model validation require it.
- Active model configuration must be used by Analysis; missing configuration uses explicit `Offline Rule Mode` with `RuleRuntime`.
- Existing `run(project_id, phase)`, `resume()`, explicit `repair()`, JSON APIs, and local SQLite migration behavior remain available.
- Domain owns graph invariants; application/methodology owns orchestration, policy, retrieval, and task execution.
- Web remains a localhost single-user tool; no non-localhost binding is added in this plan.
- A failed model call must not silently fall back to RuleRuntime.
- Existing unrelated modified and untracked workspace files are not staged or overwritten.
- Every task ends with focused tests and a separate commit.

---

## File Map

The following files are the planned ownership boundaries. New files are deliberately small and focused.

| File | Responsibility |
| --- | --- |
| `src/rflp_lite/runtime/factory.py` | Convert active profile or injected runtime into a runtime selection with provider/model metadata. |
| `src/rflp_lite/methodology/registries.py` | Prompt, output schema, and validator lookup by TaskSpec id. |
| `src/rflp_lite/methodology/schemas.py` | Kind-specific payload and field-patch JSON Schemas. |
| `src/rflp_lite/methodology/policies.py` | Task PatchPolicy authorization. |
| `src/rflp_lite/methodology/executor.py` | One bounded TaskSpec execution, validation, patch application, retry, and step ledger update. |
| `src/rflp_lite/methodology/orchestrator.py` | Full Operational → Functional → Logical/Physical → Assurance → Closure state machine. |
| `src/rflp_lite/application/closure_service.py` | Global Gate precondition, freeze, manifest, snapshots, exports, and closure revision. |
| `src/rflp_lite/methodology/validators/payload.py` | Kind-specific payload validation. |
| `src/rflp_lite/methodology/validators/policy.py` | Task-level writable scope and relation authorization validation. |
| `src/rflp_lite/methodology/contracts.py` | Shared Task, Context, Run, and ledger metadata contracts. |
| `src/rflp_lite/methodology/tasks.py` | Versioned catalog values consumed by the registries and executor. |
| `src/rflp_lite/methodology/context.py` | Bounded graph neighborhood, KnowledgeGap generation, and evidence bundle assembly. |
| `src/rflp_lite/methodology/coverage.py` | Coverage matrices and structured gap construction. |
| `src/rflp_lite/methodology/gates.py` | Phase and global gate evaluation. |
| `src/rflp_lite/methodology/repair.py` | Issue-to-task routing and bounded repair plan. |
| `src/rflp_lite/methodology/workflow.py` | Backward-compatible single-Phase facade over TaskExecutor and orchestration primitives. |
| `src/rflp_lite/repository/port.py` | Persistent contracts for Run, Step, Patch, Revision, Issue, and lease state. |
| `src/rflp_lite/repository/migrations.py` | Additive SQLite schema evolution for audit and closure metadata. |
| `src/rflp_lite/repository/sqlite.py` | Transactional persistence of the expanded ledger and closure artifacts. |
| `src/rflp_lite/domain/model.py` | Correct next-revision metadata and immutable graph application. |
| `src/rflp_lite/bootstrap/v2.py` | Composition root for runtime provider, registries, executor, orchestrator, and closure. |
| `src/rflp_lite/application/analysis_service.py` | Public analysis and pipeline application API. |
| `src/rflp_lite/interface/web/resource_api.py` | Pipeline, run detail, connection test, trace, and debug endpoints. |
| `src/rflp_lite/interface/web/resource_pages.py` | Workflow page view models. |
| `src/rflp_lite/interface/web/templates/analysis.html` | Full lifecycle analysis workbench. |
| `src/rflp_lite/interface/web/templates/model.html` | Clickable RFLP/V&V trace view. |
| `src/rflp_lite/interface/web/templates/settings.html` | Connection test and actual-runtime status. |
| `src/rflp_lite/interface/web/static/app.css` | Shared workflow status, gate, repair, and trace styling. |
| `pyproject.toml`, `README.md`, `PRODUCT.md`, `docs/CURRENT_ARCHITECTURE.md` | Dependency, version, install, and architecture consistency. |
| `tests/support/harness_fixtures.py` | Reusable deterministic runtime, project seeding, valid task output, and wheel metadata helpers. |

## Test Support Contract

Task 1 creates `tests/support/harness_fixtures.py` with these exact helpers so later test snippets are executable and do not depend on production internals:

```python
from pathlib import Path
from zipfile import ZipFile
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.methodology.contracts import StepStatus, TaskExecutionResponse

class RecordingRuntime:
    def __init__(self, payload_factory):
        self.requests = []
        self.payload_factory = payload_factory

    def execute(self, request):
        self.requests.append(request)
        return self.payload_factory(request)

def completed_response(request):
    return TaskExecutionResponse(StepStatus.COMPLETED)

def valid_output(request):
    return TaskExecutionResponse(
        StepStatus.COMPLETED,
        input_hash=canonical_hash(request.context_bundle),
        output_hash=canonical_hash({"task_id": request.task_id, "operations": []}),
        provider_id="fake",
        model_id="fake-model",
    )

def seed_project(repository, project_id="p1"):
    repository.ensure_project(project_id)

def read_wheel_metadata(path: Path) -> tuple[str, ...]:
    with ZipFile(path) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        return tuple(archive.read(metadata_name).decode("utf-8").splitlines())
```

## Task 1: Make the Active Model Runtime Real

**Files:**

- Create: `src/rflp_lite/runtime/factory.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Modify: `src/rflp_lite/application/analysis_service.py`
- Modify: `pyproject.toml`
- Test: `tests/runtime/test_runtime_factory.py`
- Test: `tests/application/test_analysis_model_wiring.py`
- Test: `tests/package/test_minimal_install.py`
- Create: `tests/support/harness_fixtures.py`

**Interfaces:**

- `RuntimeFactory.select(config: Mapping[str, object] | None, injected: TaskRuntime | None = None) -> RuntimeSelection`.
- `RuntimeSelection.runtime: TaskRuntime`, `.profile_id: str`, `.provider_id: str`, `.model_id: str`, `.mode: str`.
- `V2Services.analysis(project_id: str) -> AnalysisService` reads `SettingsService.active_config()` when constructing a runner.
- `build_v2_services(workspace_root: Path, *, runtime: TaskRuntime | None = None, config_dir: Path | None = None) -> V2Services` supports deterministic runtime injection in tests.

- [ ] **Step 1: Write the failing runtime selection tests.** Assert an active config creates an OpenAI-compatible runtime with the config profile/provider/model, an injected fake runtime remains injectable, and no config produces `RuleRuntime` with mode `Offline Rule Mode`.

```python
def test_active_profile_selects_configured_runtime():
    selection = RuntimeFactory().select({"id": "local", "base_url": "http://127.0.0.1:1234/v1", "model": "m", "api_key": "x"})
    assert selection.profile_id == "local"
    assert selection.provider_id == "openai-compatible"
    assert selection.model_id == "m"
    assert selection.mode == "Configured Model"
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/runtime/test_runtime_factory.py tests/application/test_analysis_model_wiring.py -q`

Expected: FAIL because `RuntimeFactory` and the active-config wiring do not exist.

- [ ] **Step 3: Implement the factory and composition wiring.** Add the exact selection dataclass and factory behavior:

```python
@dataclass(frozen=True, slots=True)
class RuntimeSelection:
    runtime: TaskRuntime
    profile_id: str
    provider_id: str
    model_id: str
    mode: str

class RuntimeFactory:
    def select(self, config, injected=None):
        if injected is not None:
            return RuntimeSelection(injected, "injected", "test", "test", "Injected Runtime")
        if config:
            return RuntimeSelection(
                openai_compatible_runtime(dict(config)),
                str(config.get("id", "active")),
                "openai-compatible",
                str(config.get("model", "")),
                "Configured Model",
            )
        return RuntimeSelection(RuleRuntime(), "", "rule", "", "Offline Rule Mode")
```

Move `jsonschema>=4.23` from the `schema` optional extra into `[project].dependencies`; keep `schema = ["jsonschema>=4.23"]` as a duplicate compatibility extra.

- [ ] **Step 4: Run focused tests and the minimum wheel install test.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/runtime/test_runtime_factory.py tests/application/test_analysis_model_wiring.py tests/package/test_minimal_install.py -q`

Expected: PASS; the test creates a project and runs a base analyze after installing the wheel without `[schema]`.

- [ ] **Step 5: Commit the runtime wiring.**

```bash
git add pyproject.toml src/rflp_lite/runtime/factory.py src/rflp_lite/bootstrap/v2.py src/rflp_lite/application/analysis_service.py tests/runtime/test_runtime_factory.py tests/application/test_analysis_model_wiring.py tests/package/test_minimal_install.py
git commit -m "feat: wire active model profiles into analysis runtime"
```

## Task 2: Turn TaskSpec into an Executable Contract

**Files:**

- Create: `src/rflp_lite/methodology/registries.py`
- Create: `src/rflp_lite/methodology/schemas.py`
- Create: `src/rflp_lite/methodology/policies.py`
- Create: `src/rflp_lite/methodology/validators/payload.py`
- Create: `src/rflp_lite/methodology/validators/policy.py`
- Modify: `src/rflp_lite/methodology/contracts.py`
- Modify: `src/rflp_lite/methodology/tasks.py`
- Modify: `src/rflp_lite/methodology/patches.py`
- Test: `tests/methodology/test_task_contracts.py`
- Test: `tests/methodology/test_patch_policy.py`
- Test: `tests/methodology/test_payload_schemas.py`

**Interfaces:**

- `PromptRegistry.get(template_id: str) -> str`.
- `PromptRegistry()` loads the versioned prompt catalog and exposes `get`.
- `SchemaRegistry.get(schema_id: str) -> Mapping[str, object]`.
- `SchemaRegistry()` loads the outer operations schema and kind-specific schemas.
- `validate_payload(kind: EntityKind, payload: Mapping[str, object]) -> tuple[str, ...]`.
- `ValidatorRegistry.validate(task: TaskSpec, request: TaskExecutionRequest, payload: Mapping[str, object], graph: ModelGraph) -> tuple[str, ...]`.
- `ValidatorRegistry()` registers the validator names used by `task.validators`.
- `PatchPolicy(writable_kinds, writable_fields, allowed_predicates, allowed_entity_scope)` with `assert_add_allowed`, `assert_update_allowed`, `assert_relate_allowed`, and `assert_deprecate_allowed` methods, each returning `None` or raising `ContractViolation`.
- `TaskSpec.patch_policy: PatchPolicy` and `TaskSpec.version: str`, with default values preserving construction in existing tests.

- [ ] **Step 1: Add failing contract tests.** Cover a registry lookup, a requirement payload missing its required statement, a stakeholder task attempting to update a physical block, and a RELATE operation using a predicate outside its policy.

```python
def test_requirement_payload_requires_statement():
    errors = validate_payload(EntityKind.REQUIREMENT, {"priority": "high"})
    assert "statement" in " ".join(errors)

def test_stakeholder_task_cannot_update_physical_block():
    task = next(item for item in task_catalog() if item.id == "stakeholder_analysis")
    with pytest.raises(ContractViolation, match="write scope"):
        task.patch_policy.assert_update_allowed(EntityKind.PHYSICAL_BLOCK, {"name"})
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology/test_task_contracts.py tests/methodology/test_patch_policy.py tests/methodology/test_payload_schemas.py -q`

Expected: FAIL because the registries, schemas, and policy checks are absent.

- [ ] **Step 3: Implement registries and formal schemas.** Register every catalog task id; provide method-specific prompt text containing goal, inputs, output semantics, forbidden behavior, and examples. Register payload schemas at minimum for `requirement`, `scenario_hypothesis`, `operational_scenario`, `verification_case`, `validation_case`, and `physical_block`; use a generic schema only for kinds without a formal schema.

- [ ] **Step 4: Implement TaskSpec policy metadata and pre-apply policy checks.** Every catalog task must declare writable kinds and allowed predicates. `patch_from_response()` continues to parse the envelope, but `validate_patch_policy()` must reject UPDATE/DEPRECATE targets not in the selected graph scope and RELATE endpoints/predicates outside the task policy.

- [ ] **Step 5: Run the full methodology contract suite.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology tests/domain -q`

Expected: PASS, including the existing workflow and domain relation tests.

- [ ] **Step 6: Commit the executable TaskSpec contract.**

```bash
git add src/rflp_lite/methodology tests/methodology
git commit -m "feat: enforce task schemas and patch policies"
```

## Task 3: Expand the Run Ledger and Correct Revision Metadata

**Files:**

- Modify: `src/rflp_lite/repository/port.py`
- Modify: `src/rflp_lite/repository/migrations.py`
- Modify: `src/rflp_lite/repository/sqlite.py`
- Modify: `src/rflp_lite/domain/model.py`
- Modify: `src/rflp_lite/methodology/contracts.py`
- Test: `tests/repository/test_run_ledger.py`
- Test: `tests/repository/test_revision_metadata.py`
- Test: `tests/repository/test_sqlite_model_repository.py`

**Interfaces:**

- `Step` gains `output_hash`, `provider_id`, `model_id`, `duration_ms`, `repaired`, `graph_before_hash`, and `graph_after_hash` with defaults.
- `Run` gains `task_spec_version`, `prompt_version`, `provider_id`, `model_id`, `graph_before_hash`, `graph_after_hash`, `lease`, `heartbeat`, `retry_count`, and `force_run` with defaults.
- `RunRepository.claim_run(run_id: str, lease: str, now: float) -> bool`, `heartbeat_run(run_id: str, lease: str, now: float) -> None`, `interrupt_run(run_id: str) -> None`, and `retry_run(run_id: str) -> None`.
- `ModelRepository.append_patch(project_id, patch, expected_revision, *, run_id=None, task_execution_meta=None) -> Revision`.

- [ ] **Step 1: Write failing persistence tests.** Assert all ledger fields survive SQLite round trip, `claim_run` rejects a live lease, heartbeat updates only the owner lease, and an applied patch stores run/task/model/hash metadata.

```python
def test_patch_revision_trace_contains_run_and_model_metadata(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    revision = repository.append_patch("p1", patch, 0, run_id="run-1", task_execution_meta={"provider_id": "fake", "model_id": "m", "input_hash": "in", "output_hash": "out"})
    assert revision.run_id == "run-1"
    assert repository.patch_trace("p1", revision.sequence)["model_id"] == "m"
```

- [ ] **Step 2: Run persistence tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/repository/test_run_ledger.py tests/repository/test_revision_metadata.py -q`

Expected: FAIL because the fields and methods are not present.

- [ ] **Step 3: Add additive schema migrations.** Extend `runs`, `steps`, `patches`, `revisions`, and `issues` with the new metadata using `PRAGMA table_info` checks and `ALTER TABLE ADD COLUMN`; preserve existing incompatible legacy tables exactly as the current migration does.

- [ ] **Step 4: Make `append_patch()` transactional and revision-correct.** Set `next_revision = graph.revision + 1`, apply the immutable graph, persist entities with new/updated metadata at `next_revision`, persist the revision and patch with `run_id` and execution metadata, and roll back every write on CAS or validation failure.

- [ ] **Step 5: Implement lease ownership and recovery.** Use the existing SQLite transaction lock. A lease is claimable when empty, expired, interrupted, or owned by the same lease id. Heartbeat refreshes the timestamp and retry increments the retry count without changing applied patches.

- [ ] **Step 6: Run repository and domain tests.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/repository tests/domain -q`

Expected: PASS with created/updated revisions equal to the actual graph revision.

- [ ] **Step 7: Commit the durable ledger.**

```bash
git add src/rflp_lite/repository src/rflp_lite/domain/model.py src/rflp_lite/methodology/contracts.py tests/repository
git commit -m "feat: complete run patch revision audit ledger"
```

## Task 4: Implement TaskExecutor with Retry, Validation, and Step Ledger

**Files:**

- Create: `src/rflp_lite/methodology/executor.py`
- Modify: `src/rflp_lite/methodology/contracts.py`
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/methodology/workflow.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Test: `tests/methodology/test_task_executor.py`
- Test: `tests/runtime/test_task_execution.py`

**Interfaces:**

- `TaskExecutor.execute(project_id: str, task: TaskSpec, *, run_id: str, runtime: TaskRuntime, graph: ModelGraph | None = None, repaired: bool = False) -> TaskExecutionResult`.
- `TaskExecutor(repository, context_builder, prompt_registry, schema_registry, validator_registry, evidence_service=None)` is the constructor used by the WorkflowRunner and LifecycleOrchestrator.
- `TaskExecutionResult.status`, `.patch_id`, `.attempt`, `.diagnostics`, `.input_hash`, `.output_hash`, `.provider_id`, `.model_id`, `.graph_before_hash`, `.graph_after_hash`.
- `TaskExecutionRequest.prompt` and `TaskExecutionRequest.output_schema` are appended as defaulted fields so older callers remain valid.

- [ ] **Step 1: Write failing executor tests.** Test prompt/schema selection, output validation before patch application, retry up to `max_attempts`, `completion_condition`, no-change completion, and Step metadata persistence.

```python
def test_executor_uses_task_prompt_schema_and_records_step(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    seed_project(repository)
    task = task_catalog()[0]
    runtime = RecordingRuntime(valid_output)
    result = TaskExecutor(repository, ContextBuilder(), PromptRegistry(), SchemaRegistry(), ValidatorRegistry()).execute("p1", task, run_id="run-1", runtime=runtime)
    request = runtime.requests[0]
    assert request.prompt.startswith("You are executing")
    assert request.output_schema["type"] == "object"
    assert result.status is StepStatus.COMPLETED
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology/test_task_executor.py tests/runtime/test_task_execution.py -q`

Expected: FAIL because execution is still embedded in `WorkflowRunner` and uses one generic prompt.

- [ ] **Step 3: Implement one bounded execution.** Build Context, compile the registered prompt with task/context/evidence, call the selected runtime, parse the output envelope, validate schema/semantic/policy, apply Patch through the repository with execution metadata, evaluate completion, and update Step on every attempt.

- [ ] **Step 4: Implement retry semantics.** For a validation or provider format failure, update the current Step with diagnostics, retry until `task.max_attempts`, and return `DEGRADED`/`FAILED` with no patch if all attempts fail. Do not turn provider failure into a RuleRuntime call.

- [ ] **Step 5: Make `WorkflowRunner.run()` delegate each task to TaskExecutor.** Keep the existing `run(project_id, phase)` signature and summary shape while removing its direct generic request construction.

- [ ] **Step 6: Run the existing workflow suite.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology/test_workflow.py tests/runtime tests/application -q`

Expected: PASS; fake runtime calls remain observable and the offline path still completes no-change tasks.

- [ ] **Step 7: Commit the TaskExecutor.**

```bash
git add src/rflp_lite/methodology src/rflp_lite/runtime/structured_model.py src/rflp_lite/bootstrap/v2.py tests/methodology tests/runtime
git commit -m "feat: execute TaskSpec through validated task executor"
```

## Task 5: Connect KnowledgeGap Retrieval to Task Context

**Files:**

- Modify: `src/rflp_lite/methodology/context.py`
- Modify: `src/rflp_lite/retrieval/planner.py`
- Modify: `src/rflp_lite/retrieval/evidence.py`
- Modify: `src/rflp_lite/application/evidence_service.py`
- Modify: `src/rflp_lite/methodology/executor.py`
- Modify: `src/rflp_lite/methodology/contracts.py`
- Test: `tests/methodology/test_context_retrieval.py`
- Test: `tests/retrieval/test_retrieval.py`
- Test: `tests/e2e/test_retrieval_reaches_task.py`

**Interfaces:**

- `ContextBuilder.build(graph: ModelGraph, task: TaskSpec, *, evidence_service: EvidenceService | None = None) -> ContextBundle`.
- `ContextBuilder.knowledge_gaps(graph, task) -> tuple[KnowledgeGap, ...]`.
- `RetrievalEngine.retrieve(gap, context, *, max_candidates=8) -> EvidenceRetrievalResult`.
- `EvidenceService.bundle(project_id: str, candidate_ids: Sequence[str], limit: int = 8) -> tuple[Mapping[str, object], ...]`.

- [ ] **Step 1: Write failing retrieval integration tests.** Seed a unique document/source-region fact and assert the fake runtime receives that fact in `TaskExecutionRequest.evidence_bundle`; assert duplicate evidence is removed and a web retriever failure is non-fatal.

```python
def test_document_fact_reaches_task_prompt(tmp_path):
    runtime = RecordingRuntime(valid_output)
    services = build_v2_services(tmp_path, runtime=runtime)
    services.projects.create("p1")
    repository = services.repository("p1")
    repository.save_source_regions("p1", [{"id": "region-1", "document_id": "doc-1", "page": 1, "locator": "p1", "text": "maximum payload is 12 kg", "bbox": [], "heading_path": []}])
    services.analysis("p1").run("p1", Phase.OPERATIONAL)
    assert any("maximum payload is 12 kg" in str(item) for item in runtime.requests[0].evidence_bundle)
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology/test_context_retrieval.py tests/e2e/test_retrieval_reaches_task.py -q`

Expected: FAIL because `ContextBuilder` currently always returns `evidence=()`.

- [ ] **Step 3: Implement bounded KnowledgeGap generation and retrieval.** Derive queries from missing input kinds and gate-relevant gaps; call sources in User Documents > Historical Projects > Local FTS > optional Web order; stop after two low-yield rounds; cap queries, candidates, and evidence excerpt length.

- [ ] **Step 4: Persist and assemble evidence.** Save candidates through `EvidenceService`, resolve stored evidence by id, deduplicate by stable id/content hash, and place only evidence relevant to the task in both ContextBundle and TaskExecutionRequest.

- [ ] **Step 5: Run retrieval and document tests.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/retrieval tests/adapters/test_document_intelligence.py tests/methodology/test_context_retrieval.py tests/e2e/test_retrieval_reaches_task.py -q`

Expected: PASS, including optional Web failure isolation.

- [ ] **Step 6: Commit retrieval integration.**

```bash
git add src/rflp_lite/methodology/context.py src/rflp_lite/retrieval src/rflp_lite/application/evidence_service.py src/rflp_lite/methodology/executor.py tests/retrieval tests/methodology/test_context_retrieval.py tests/e2e/test_retrieval_reaches_task.py
git commit -m "feat: feed bounded evidence retrieval into tasks"
```

## Task 6: Add the Full Lifecycle Orchestrator

**Files:**

- Create: `src/rflp_lite/methodology/orchestrator.py`
- Modify: `src/rflp_lite/methodology/workflow.py`
- Modify: `src/rflp_lite/application/analysis_service.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Test: `tests/methodology/test_lifecycle_orchestrator.py`
- Test: `tests/e2e/test_full_lifecycle_pipeline.py`

**Interfaces:**

- `LifecycleOrchestrator.run_pipeline(project_id: str, *, run_id: str | None = None, force_run: bool = False) -> PipelineSummary`.
- `LifecycleOrchestrator(model_repository, run_repository, task_executor, gate_service, closure_service, runtime_selection_provider)` is the constructor used by `V2Services`.
- `PipelineSummary.run_id`, `.project_id`, `.status`, `.phase_results`, `.gate_results`, `.closure`, `.diagnostics`.
- `PipelineSummary.repair_results` and `.graph` expose the repair audit and final graph to the UI and acceptance tests.
- `AnalysisService.run_pipeline(project_id, *, force_run=False) -> PipelineSummary`.
- `POST /projects/{project_id}/analysis` accepts `{ "mode": "pipeline", "force_run": true }`; the existing `{ "phase": "operational" }` remains single Phase.

- [ ] **Step 1: Write the failing one-call pipeline test.** Use a deterministic fake runtime that creates the minimum accepted candidates for each phase and assert the orchestrator calls phases in order and reaches Closure.

```python
def test_one_call_runs_full_lifecycle_to_closure(tmp_path):
    services = build_v2_services(tmp_path, runtime=RecordingRuntime(valid_output))
    summary = services.orchestrator.run_pipeline("p1")
    assert [item.phase for item in summary.phase_results] == ["operational", "functional", "logical_physical", "assurance"]
    assert summary.closure.status == "completed"
```

- [ ] **Step 2: Run the integration test and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology/test_lifecycle_orchestrator.py tests/e2e/test_full_lifecycle_pipeline.py -q`

Expected: FAIL because only single-Phase `WorkflowRunner.run()` exists.

- [ ] **Step 3: Implement phase sequencing and RunIdentity.** Compute identity from project, phase, current graph revision, methodology version, task spec version, prompt version, model profile, and context hash. Reuse only an exact matching incomplete/completed Run; `force_run=True` adds a new deterministic suffix and never skips into an unrelated Run.

- [ ] **Step 4: Implement gate checkpoints and resume.** Run the phase through TaskExecutor, evaluate its gate, append gate snapshot to the Run, and stop or route to Repair when it fails. A passed phase advances automatically; `resume()` continues from the first incomplete phase.

- [ ] **Step 5: Run workflow, API, and E2E tests.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology tests/interface/web tests/e2e/test_full_lifecycle_pipeline.py -q`

Expected: PASS; the legacy single-Phase endpoint remains functional.

- [ ] **Step 6: Commit the lifecycle pipeline.**

```bash
git add src/rflp_lite/methodology/orchestrator.py src/rflp_lite/methodology/workflow.py src/rflp_lite/application/analysis_service.py src/rflp_lite/bootstrap/v2.py src/rflp_lite/interface/web/resource_api.py tests/methodology/test_lifecycle_orchestrator.py tests/e2e/test_full_lifecycle_pipeline.py
git commit -m "feat: orchestrate full lifecycle analysis pipeline"
```

## Task 7: Upgrade Gates and Targeted Repair

**Files:**

- Modify: `src/rflp_lite/methodology/coverage.py`
- Modify: `src/rflp_lite/methodology/gates.py`
- Modify: `src/rflp_lite/methodology/repair.py`
- Modify: `src/rflp_lite/methodology/orchestrator.py`
- Modify: `src/rflp_lite/repository/port.py`
- Modify: `src/rflp_lite/repository/sqlite.py`
- Test: `tests/methodology/test_gate_matrices.py`
- Test: `tests/methodology/test_targeted_repair.py`
- Test: `tests/e2e/test_gate_failure_repair_regate.py`

**Interfaces:**

- `GateIssue(code, severity, root_cause, entity_ids, suggested_task, rollback_phase, evidence_gap, status)`.
- `CoverageReport.gaps` contains `GateIssue`-compatible structured gaps and `.covered_dimensions` names matrix dimensions.
- `RepairRouter.route(issue: GateIssue, graph: ModelGraph) -> RepairRoute(task_id: str, phase: Phase, max_rounds: int)`.
- `RepairRouter.repair(project_id, issue, *, run_id, executor) -> RepairResult`.

- [ ] **Step 1: Write failing matrix and repair tests.** Assert an accepted requirement without a Function fails F-Gate, an incomplete R→F→L→P chain fails P-Gate with entity ids, a Hazard without mitigation fails Global Gate, and repair routes to the earliest task instead of adding `missing_xxx`.

```python
def test_repair_routes_to_root_task_and_regates(tmp_path):
    services = build_v2_services(tmp_path, runtime=RecordingRuntime(valid_output))
    result = services.orchestrator.run_pipeline("p1")
    assert result.repair_results[0].task_id == "lifecycle_analysis"
    assert result.gate_results[-1].passed is True
    assert all("missing_" not in item.name for item in result.graph.entities)
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology/test_gate_matrices.py tests/methodology/test_targeted_repair.py tests/e2e/test_gate_failure_repair_regate.py -q`

Expected: FAIL because current gates only test kind existence and repair creates generic candidates.

- [ ] **Step 3: Implement coverage matrices.** Add explicit matrix/link evaluators for Stakeholder × Concern, Stakeholder × Lifecycle, Lifecycle × Scenario Type, UseCase → Scenario → Activity → Requirement, Requirement → Function → Logical → Physical, Requirement × Verification, and Hazard → Mitigation → Verification. Accepted objects use hard requirements; candidates produce soft/degraded diagnostics.

- [ ] **Step 4: Implement structured Issue persistence.** Save code, severity, root cause, entity ids, suggested task, rollback phase, evidence gap, run id, task id, and status. Use stable issue ids per graph revision and mark resolved/superseded after successful repair.

- [ ] **Step 5: Replace placeholder repair with routed task reruns.** Map each root cause to its earliest catalog task, request targeted context/evidence, execute only that task with its policy, and run the corresponding Gate immediately. Stop after the configured maximum repair rounds and preserve the original revision on failure.

- [ ] **Step 6: Run all gate, repair, and E2E tests.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/methodology tests/e2e -q`

Expected: PASS, with repair and re-gate behavior visible in the persisted ledger.

- [ ] **Step 7: Commit Gate and Repair.**

```bash
git add src/rflp_lite/methodology src/rflp_lite/repository tests/methodology tests/e2e/test_gate_failure_repair_regate.py
git commit -m "feat: add matrix gates and targeted repair routing"
```

## Task 8: Implement Closure, Exports, and Run Recovery

**Files:**

- Create: `src/rflp_lite/application/closure_service.py`
- Modify: `src/rflp_lite/application/render_service.py`
- Modify: `src/rflp_lite/methodology/orchestrator.py`
- Modify: `src/rflp_lite/repository/port.py`
- Modify: `src/rflp_lite/repository/sqlite.py`
- Modify: `src/rflp_lite/methodology/contracts.py`
- Test: `tests/application/test_closure_service.py`
- Test: `tests/repository/test_run_recovery.py`
- Test: `tests/e2e/test_closure_manifest.py`

**Interfaces:**

- `ClosureService.close(project_id: str, run_id: str, *, global_gate: GateResult) -> ClosureResult`.
- `ClosureService(repository: ModelRepository, render_service: RenderService)` is the constructor used by the orchestrator.
- `ClosureResult.run_id`, `.status`, `.revision`, `.manifest_path`, `.gate_snapshot_path`, `.exports`, `.diagnostics`.
- `RunRepository.claim_run`, `.heartbeat_run`, `.interrupt_run`, and `.retry_run` are used by the orchestrator around long-running execution.

- [ ] **Step 1: Write failing closure and recovery tests.** Assert Closure rejects a failed Global Gate, a passing Closure writes manifest and gate snapshot with graph/methodology/profile/provider metadata, exports JSON and trace matrix, and an interrupted leased Run resumes without duplicating a patch.

```python
def test_closure_writes_traceable_manifest(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    closure = ClosureService(repository, RenderService(ModelService(repository)))
    result = closure.close("p1", "run-1", global_gate=GateResult("Global-Gate", True))
    manifest = json.loads(Path(result.manifest_path).read_text())
    assert manifest["graph_hash"]
    assert manifest["methodology_version"] == "v2.0"
    assert manifest["run_id"] == result.run_id
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/application/test_closure_service.py tests/repository/test_run_recovery.py tests/e2e/test_closure_manifest.py -q`

Expected: FAIL because Closure currently only marks a Run completed.

- [ ] **Step 3: Implement ClosureService.** Require Global Gate pass, freeze accepted revision metadata, write `manifest.json`, gate snapshot, audit summary, and export listing; call existing RenderService for JSON/SVG/trace outputs. Do not mutate the graph after the closure revision is recorded.

- [ ] **Step 4: Integrate claim/heartbeat/interrupt/retry.** Claim a Run before task execution, heartbeat between tasks and bounded model attempts, mark interrupted on cancellation, and retry only incomplete steps. Patch idempotence comes from exact Run/Task/Revision metadata and CAS.

- [ ] **Step 5: Run application, repository, and E2E suites.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/application tests/repository tests/e2e -q`

Expected: PASS, including legacy project deletion and migration behavior.

- [ ] **Step 6: Commit Closure and recovery.**

```bash
git add src/rflp_lite/application/closure_service.py src/rflp_lite/application/render_service.py src/rflp_lite/methodology src/rflp_lite/repository tests/application/test_closure_service.py tests/repository/test_run_recovery.py tests/e2e/test_closure_manifest.py
git commit -m "feat: close runs with manifests and recoverable leases"
```

## Task 9: Make the Web UI Show the Harness Workflow

**Files:**

- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/settings.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_analysis_workflow.py`
- Test: `tests/interface/web/test_settings_runtime_status.py`
- Test: `tests/interface/web/test_model_trace.py`

**Interfaces:**

- `GET /projects/{project_id}/analysis` returns current revision, active runtime, run status, phase states, gate result, task ledger, repair results, and closure state.
- `POST /projects/{project_id}/analysis` supports `mode=pipeline`, `force_run`, and existing single-Phase requests.
- `POST /model-profiles/test` returns provider/model connectivity status without saving credentials.
- `GET /projects/{project_id}/trace` returns Requirement → Function → Logical → Physical → Verification paths.

- [ ] **Step 1: Write failing page/API tests.** Assert the analysis response and HTML contain all five lifecycle phases, actual provider/model or `Offline Rule Mode`, Gate issues, Evidence count, attempt, Patch, Validation, Repair, and Closure; assert Settings connection test and Model trace endpoints work.

```python
def test_analysis_page_shows_full_harness_workflow(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    client.post("/projects", json={"id": "p1"})
    html = client.get("/ui/projects/p1/analysis").text
    assert "Operational" in html and "Closure" in html
    assert "Offline Rule Mode" in html
```

- [ ] **Step 2: Run focused Web tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/interface/web/test_analysis_workflow.py tests/interface/web/test_settings_runtime_status.py tests/interface/web/test_model_trace.py -q`

Expected: FAIL because the current Analysis page only starts one operational phase and pages do not expose ledger data.

- [ ] **Step 3: Add API view models and endpoints.** Keep JSON as a debug representation, but return structured data suitable for the page. Never expose API keys. Report the runtime metadata captured on the Run, not only the currently active profile id.

- [ ] **Step 4: Build the analysis workbench.** Add the top status row, phase rail, current Task panel, Gate matrix/Issue table, Repair panel, and Closure summary. Use existing HTMX/static assets and preserve project navigation and deletion controls.

- [ ] **Step 5: Add clickable Model trace and Settings connection status.** Render typed paths from the graph, show missing links as issues, and show the result of a real connection test separately from “profile saved/active”.

- [ ] **Step 6: Run all Web tests and a local browser smoke.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/interface/web -q`

Expected: PASS; then start `./.venv/bin/uvicorn rflp_lite.interface.web.app:create_app --factory --host 127.0.0.1 --port 8000` and verify `/ui/projects`, a project analysis page, model trace, and settings page in the browser.

- [ ] **Step 7: Commit the workflow UI.**

```bash
git add src/rflp_lite/interface/web tests/interface/web
git commit -m "feat: expose lifecycle harness workflow in web UI"
```

## Task 10: Align Documentation, Historical Plans, and Packaging

**Files:**

- Modify: `README.md`
- Modify: `PRODUCT.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Create: `docs/superpowers/INDEX.md`
- Modify: `pyproject.toml`
- Create: `scripts/verify_package.py`
- Test: `tests/package/test_package_metadata.py`

**Interfaces:**

- `scripts/verify_package.py <wheel> <source_zip>` exits 0 only when required templates/static assets, entry points, base dependencies, version labels, and no runtime DB/cache files are present.

- [ ] **Step 1: Write failing packaging/documentation tests.** Assert product version `0.1.0`, methodology protocol `v2.0`, base `jsonschema`, wheel-first offline installation, and an index marking current versus superseded plans.

```python
def test_package_metadata_declares_jsonschema_base_dependency():
    metadata = read_wheel_metadata(Path("dist/rflp_lite-0.1.0-py3-none-any.whl"))
    assert any(line == "Requires-Dist: jsonschema>=4.23" for line in metadata)
```

- [ ] **Step 2: Run focused tests and verify failure.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/package/test_package_metadata.py -q`

Expected: FAIL until documentation and packaging checks are updated.

- [ ] **Step 3: Update install and version documentation.** Document editable, wheel-first, and offline paths using Python 3.11+, state that `0.1.0` is the product version and `v2.0` is the methodology protocol, and remove claims that lease/heartbeat or full closure are complete until the implementation from Tasks 3 and 8 exists.

- [ ] **Step 4: Add the historical plan index.** List the current remediation spec/plan and mark older plans as historical/superseded by date and topic. Keep the files in place so existing references do not break; do not delete or move user-authored documents.

- [ ] **Step 5: Build and verify a clean package tree.** Build from a temporary `git archive HEAD` tree into a new output directory, run `scripts/verify_package.py`, and assert the wheel includes `templates/*.html`, `static/app.css`, and `static/vendor/*`.

- [ ] **Step 6: Run packaging tests and commit documentation.**

Run: `PYTHONPATH=src .venv/bin/pytest tests/package -q`

Expected: PASS.

```bash
git add README.md PRODUCT.md docs/CURRENT_ARCHITECTURE.md docs/superpowers/INDEX.md pyproject.toml scripts/verify_package.py tests/package
git commit -m "docs: align versions architecture and package delivery"
```

## Task 11: End-to-End Acceptance and Release

**Files:**

- Modify: `tests/e2e/test_campus_delivery_robot.py`
- Create: `tests/e2e/test_harness_acceptance.py`
- Create: `docs/verification/2026-09-08-harness-review-remediation.md`
- Create: `release/AI4MBSE-0.1.0-current/DELIVERY-NOTES.md`

- [ ] **Step 1: Add the complete acceptance test set.** Implement these named tests from the review document: `test_active_model_profile_is_used_by_analysis`, `test_one_call_runs_full_lifecycle_to_closure`, `test_gate_failure_triggers_targeted_repair_and_regate`, `test_retrieval_evidence_reaches_task_prompt`, `test_task_cannot_update_entity_outside_write_scope`, `test_requirement_payload_schema_rejects_invalid_fields`, `test_run_patch_revision_trace_is_complete`, `test_switching_model_profile_creates_distinct_run`, `test_entity_revision_metadata_advances`, and `test_minimal_wheel_install_can_create_project`.

- [ ] **Step 2: Run the complete verification matrix.**

```bash
PYTHONPATH=src .venv/bin/pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests scripts
.venv/bin/lint-imports
```

Expected: all tests pass, compileall exits 0, Ruff reports no violations, and import-linter reports all configured contracts kept.

- [ ] **Step 3: Run architecture budget checks.**

```bash
PYTHONPATH=src .venv/bin/pytest tests/architecture -q
```

Expected: module cycles, adapter-to-application edges, raw request JSON calls outside the interface boundary, and overlong functions remain within `architecture_budget.json`.

- [ ] **Step 4: Run real local web acceptance.** Start the app with the project Python environment, create a disposable project through the UI/API, verify project creation, document ingestion, pipeline start, phase status, Gate/Repair display, Model trace, Closure manifest, and project deletion. Keep the disposable workspace outside the repository and remove it only after recording the result.

- [ ] **Step 5: Build the final release bundle.** Build wheel and sdist from the final committed tree, create a controlled source zip with `git archive HEAD`, include delivery notes and SHA-256 checksums, and keep all existing release directories untouched.

- [ ] **Step 6: Record verification and commit only controlled acceptance artifacts.**

```bash
git add tests/e2e/test_harness_acceptance.py docs/verification/2026-09-08-harness-review-remediation.md
git commit -m "test: verify complete AI4MBSE harness acceptance flow"
```

## Self-Review Checklist

- [ ] P0-1 is covered by Tasks 1 and 11.
- [ ] P0-2 is covered by Task 6 and the full pipeline acceptance test.
- [ ] P0-3 is covered by Tasks 2 and 4.
- [ ] P0-4 is covered by Task 5.
- [ ] P1 Gate, Repair, PatchPolicy, typed payload, audit, Closure, RunIdentity, revision metadata, lease/heartbeat/retry are covered by Tasks 2, 3, 6, 7, and 8.
- [ ] P2 Web/UI and documentation/package consistency are covered by Tasks 9 and 10.
- [ ] No task instructs a generic placeholder repair, silent model fallback, broad destructive cleanup, or a domain-to-adapter reverse dependency.
- [ ] All newly introduced interfaces are named consistently across later tasks.
- [ ] Every task has focused tests, exact commands, expected results, and a commit boundary.
