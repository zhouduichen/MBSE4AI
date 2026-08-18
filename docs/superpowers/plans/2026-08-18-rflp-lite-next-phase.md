# AI4MBSE RFLP-Lite 下一阶段完整落实 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依次完成复审文档中的 Phase 2A、2B、3A、3B、5、4、6、7，使 RFLP-Lite 具备显式窄依赖、严格 LLM 契约、证据约束 MBSE、可恢复 Job、完整 UI 闭环和自动质量门禁。

**Architecture:** 保留现有模块化单体和兼容表面，以 `application/use_cases` 为业务入口、`ports` 为边界、`bootstrap/container.py` 为唯一组合根。LLM 结果必须经过 block-specific schema、Typed DTO、语义/来源校验后才形成 `ValidatedBlockResult` 并事务性合并；MBSE 只接受有证据的关系。

**Tech Stack:** Python 3.11+, dataclasses/typing Protocol, SQLite repository, JSON-backed local jobs, FastAPI/Jinja/HTMX, pytest, Import Linter, jsonschema/check-jsonschema。

## Global Constraints

- 保留现有 CLI 命令、Web 路由、模板入口、工作区目录和 `.rflp` 存储布局。
- 不引入 Celery、Redis、消息队列或远程数据库。
- `bootstrap/container.py` 是唯一允许组合 Application + Adapter 的位置。
- Application / Interface 不得 import `rflp_lite.adapters`。
- 新代码不得调用 `require_dependencies()`；旧调用仅在迁移清单中保留。
- LLM 结构或语义失败不得写入 Workbench；repair 最多一次。
- Block 级失败不回滚已成功 Block；重试只执行非 succeeded Block。
- 现有未跟踪文件不纳入本次变更。

---

### Task 1: 建立基线门禁和 Use Case 依赖协议

**Files:**
- Create: `src/rflp_lite/application/use_cases/dependencies.py`
- Modify: `src/rflp_lite/application/use_cases/__init__.py`
- Modify: `tests/architecture/test_dependency_boundaries.py`
- Create: `tests/application/use_cases/test_dependencies.py`
- Modify: `docs/CURRENT_ARCHITECTURE.md`

**Interfaces:**
- Produces frozen dataclasses `ReviewRequirementDeps`, `GenerateRflpDeps`, `GenerateMbseDeps`, `AnalyzeProjectDeps`, `RunProjectTestsDeps`, `RecordEvidenceDeps`.
- Each dataclass stores only Protocol/Callable ports used by its Use Case; it never imports `rflp_lite.adapters`.

- [ ] **Step 1: Add failing architecture tests**

```python
def test_new_use_case_modules_do_not_call_global_dependency_locator():
    source = Path("src/rflp_lite/application/use_cases")
    assert "require_dependencies(" not in "\n".join(p.read_text() for p in source.glob("*.py"))
```

- [ ] **Step 2: Run the focused test and verify the current failure**

Run: `.venv/bin/python -m pytest tests/architecture/test_dependency_boundaries.py -q`

Expected: the new guard fails until the directory-level scan and dependency dataclasses are present.

- [ ] **Step 3: Implement the dependency dataclasses**

Use `@dataclass(frozen=True, slots=True)` and Protocol types from `ports.repositories`, `ports.jobs`, `ports.generative_model`, `ports.test_execution`, and `ports.project_analysis`. Do not add a catch-all `ApplicationDependencies` field to the new dataclasses.

- [ ] **Step 4: Run architecture and compile checks**

Run: `.venv/bin/python -m pytest tests/architecture/test_dependency_boundaries.py -q && .venv/bin/python -m compileall -q src`

Expected: PASS.

- [ ] **Step 5: Document the migration boundary**

Update `docs/CURRENT_ARCHITECTURE.md` with the six Use Case dependency bundles and list every remaining compatibility caller of `require_dependencies()`.

### Task 2: Extract requirement review as an explicit Use Case

**Files:**
- Create: `src/rflp_lite/application/use_cases/review_requirement.py`
- Modify: `src/rflp_lite/application/requirements_workbench.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Create: `tests/application/use_cases/test_review_requirement.py`
- Modify: `tests/application/test_web_facade.py`

**Interfaces:**
- `ReviewRequirementCommand(requirement_id: str, decision: str, revision: int | None = None, statement: str | None = None)`.
- `ReviewRequirementResult(state: dict[str, object], changed_ids: tuple[str, ...], stale_groups: tuple[str, ...])`.
- `ReviewRequirementUseCase.execute(command: ReviewRequirementCommand) -> ReviewRequirementResult`.

- [ ] **Step 1: Write tests for accept, edit, reject, and stale propagation**

Tests use a fake `WorkbenchRepositoryPort`, invoke the Use Case directly, and assert that only the selected requirement and its derived groups change. Assert that an unknown ID raises `ContractViolation`.

- [ ] **Step 2: Run the focused tests to verify failure**

Run: `.venv/bin/python -m pytest tests/application/use_cases/test_review_requirement.py -q`

Expected: FAIL because the command/result/use case do not exist.

- [ ] **Step 3: Move the smallest state-transition slice**

Delegate the existing accepted/edited/rejected behavior from `requirements_workbench.py` into `ReviewRequirementUseCase`. Keep persistence inside one repository transaction and preserve existing audit event names and revision hashes.

- [ ] **Step 4: Make WebFacade and existing routes forward only**

Construct the Use Case in the composition root and pass it to `WebFacade`. Keep existing public facade method names and return shapes; those methods translate HTTP/legacy arguments into `ReviewRequirementCommand` and return the existing payload.

- [ ] **Step 5: Run review, facade, and full domain tests**

Run: `.venv/bin/python -m pytest tests/application/use_cases/test_review_requirement.py tests/application/test_web_facade.py tests/domain/test_requirements.py -q`

Expected: PASS with existing behavior preserved.

### Task 3: Extract RFLP/MBSE/project/evidence Use Cases

**Files:**
- Create: `src/rflp_lite/application/use_cases/generate_rflp.py`
- Create: `src/rflp_lite/application/use_cases/generate_mbse.py`
- Create: `src/rflp_lite/application/use_cases/analyze_project.py`
- Create: `src/rflp_lite/application/use_cases/run_project_tests.py`
- Create: `src/rflp_lite/application/use_cases/record_evidence.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Create: `tests/application/use_cases/test_generation_use_cases.py`
- Modify: `tests/architecture/test_dependency_boundaries.py`

**Interfaces:**
- `GenerateRflpUseCase.execute(workspace: Path) -> dict[str, object]`.
- `GenerateMbseUseCase.execute(workspace: Path, revision: int | None = None) -> dict[str, object]`.
- `AnalyzeProjectUseCase.execute(workspace: Path, source: Path) -> dict[str, object]`.
- `RunProjectTestsUseCase.execute(workspace: Path, source: Path, config: dict[str, object]) -> dict[str, object]`.
- `RecordEvidenceUseCase.execute(workspace: Path, evidence: tuple[dict[str, object], ...]) -> dict[str, object]`.

- [ ] **Step 1: Add delegation tests**

Stub each Use Case and assert WebFacade/CLI adapters call exactly one Use Case with normalized arguments. Assert the project-test result is saved as Evidence only.

- [ ] **Step 2: Run the tests and verify the old orchestration is still used**

Run: `.venv/bin/python -m pytest tests/application/use_cases/test_generation_use_cases.py -q`

Expected: FAIL until the facade delegates.

- [ ] **Step 3: Implement thin Use Cases by moving orchestration, not domain rules**

Reuse existing `requirements_flow`, `mbse_modeling`, `project_bridge`, and `evidence` logic. Inject repositories, scanners, test executors, and renderers through the task-specific dependency dataclasses.

- [ ] **Step 4: Keep compatibility methods and routes**

Replace business bodies in WebFacade and CLI command handlers with argument normalization plus Use Case invocation. Do not change URL paths or JSON keys.

- [ ] **Step 5: Run interface and application tests**

Run: `.venv/bin/python -m pytest tests/application tests/interface tests/architecture/test_dependency_boundaries.py -q`

Expected: PASS.

### Task 4: Remove Application raw `chat_completion` bypass

**Files:**
- Modify: `src/rflp_lite/application/requirements_workbench.py`
- Modify: `src/rflp_lite/application/requirement_inference.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/application/dependencies.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Create: `tests/application/test_no_raw_chat_completion.py`
- Modify: `tests/ports/test_generative_model.py`

**Interfaces:**
- All business-layer generation uses `GenerativeModel.complete_json(GenerationRequest) -> GenerationResponse`.
- `chat_completion` remains adapter-internal and is not a field of new Use Case dependency bundles.

- [ ] **Step 1: Add the bypass guard**

Scan `src/rflp_lite/application` and fail when an import or call to `chat_completion` exists outside an adapter/port test fixture.

- [ ] **Step 2: Run the guard and capture current failures**

Run: `.venv/bin/python -m pytest tests/application/test_no_raw_chat_completion.py -q`

Expected: FAIL on `requirements_workbench.py` and `requirement_inference.py`.

- [ ] **Step 3: Route legacy inference through a GenerationRequest**

Build a `GenerationRequest` with a named lens, bounded schema, input hash, and existing prompt payload. Use the injected model; if no model is configured, return the existing degraded diagnostic.

- [ ] **Step 4: Remove the Application dependency field**

Delete `ApplicationDependencies.chat_completion` after all callers are migrated; update `bootstrap/container.py` to keep `chat_completion` only inside `OpenAICompatibleModel` construction.

- [ ] **Step 5: Run LLM port and full application tests**

Run: `.venv/bin/python -m pytest tests/ports/test_generative_model.py tests/adapters/test_llm_client.py tests/application -q`

Expected: PASS and the raw-call scan is clean.

### Task 5: Implement six strict block schemas and typed DTOs

**Files:**
- Create: `src/rflp_lite/application/intelligence/block_schemas.py`
- Create: `src/rflp_lite/application/intelligence/validated_result.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/ports/generative_model.py`
- Create: `tests/application/intelligence/test_block_schemas.py`
- Create: `tests/application/intelligence/test_validated_result.py`

**Interfaces:**
- `BLOCK_SCHEMA_VERSION: str = "v2"`.
- `schema_for(block_id: str) -> dict[str, object]`.
- `parse_block_dto(block_id: str, payload: dict[str, object]) -> BlockDTO`.
- `ValidatedBlockResult(block_id, input_hash, workspace, dto, diagnostics, provenance, output_hash, repaired)`.
- `validate_and_build_result(response: GenerationResponse, *, state: dict[str, object], block: AnalysisBlock) -> ValidatedBlockResult`.

- [ ] **Step 1: Add table-driven schema rejection tests**

Cover extra fields, missing fields, wrong types, NaN confidence, list limits, enum limits, and the six block-specific required shapes. Assert `additionalProperties` is false at every object level.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_block_schemas.py tests/application/intelligence/test_validated_result.py -q`

Expected: FAIL because the schema/DTO modules do not exist.

- [ ] **Step 3: Define explicit schema maps**

Create separate schemas for `system_scope`, `stakeholders`, `concerns_needs`, `requirements`, `scenarios`, and `architecture`. Include required IDs/fields, bounded strings/lists, confidence `0 <= x <= 1`, controlled enums, and `additionalProperties: false` recursively.

- [ ] **Step 4: Define immutable DTOs and normalization**

Use frozen dataclasses with tuples for collections. Preserve model IDs in provenance but derive deterministic stored IDs only after validation. Reject `NaN`, duplicate IDs, missing `input_hash`, missing workspace, and unsupported schema version.

- [ ] **Step 5: Make `build_analysis_blocks()` use the schemas**

Replace `_schema()`'s generic item object with `schema_for(block_id)`. Keep existing max-item/max-token values and request lens names.

- [ ] **Step 6: Run the contract tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_block_schemas.py tests/application/intelligence/test_validated_result.py tests/application/intelligence/test_analysis_blocks.py -q`

Expected: PASS.

### Task 6: Add semantic/provenance validation and bounded merge

**Files:**
- Create: `src/rflp_lite/application/intelligence/semantic_validator.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Create: `tests/application/intelligence/test_semantic_validator.py`
- Modify: `tests/application/intelligence/test_analysis_blocks.py`

**Interfaces:**
- `AnalysisSemanticValidator.validate(result: ValidatedBlockResult, state: dict[str, object]) -> tuple[Diagnostic, ...]`.
- `merge_block_result(state: dict[str, object], result: ValidatedBlockResult) -> dict[str, object]`.

- [ ] **Step 1: Add semantic rejection tests**

Test missing `source_region_id`, cross-workspace IDs, input-hash mismatch, duplicate IDs, invalid relation endpoint, invalid relation endpoint type, and unknown relation kind. Assert the state is unchanged.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_semantic_validator.py -q`

Expected: FAIL until the validator exists.

- [ ] **Step 3: Implement deterministic validation**

Build an index from current Workbench plus the incoming typed DTO. Validate source regions, workspace, IDs, relation kinds, endpoint matrix, and relation direction. Produce structured diagnostics with `code`, `severity`, `block_id`, and `path`.

- [ ] **Step 4: Replace raw merge input**

Change the enrichment runner to call `validate_and_build_result()` before merge. `merge_block_result()` accepts only `ValidatedBlockResult`; keep a compatibility adapter only in tests and remove raw payload handling from the production path.

- [ ] **Step 5: Preserve one-block atomicity**

Wrap each valid merge in its own repository transaction, record output hash/provenance, and update only the current block status. Failed validation records the diagnostic and does not save the state.

- [ ] **Step 6: Run enrichment tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence -q`

Expected: PASS; invalid fixtures do not alter accepted or previously succeeded data.

### Task 7: Correct MBSE semantic generation

**Files:**
- Modify: `src/rflp_lite/application/mbse_semantics.py`
- Modify: `src/rflp_lite/application/mbse_modeling.py`
- Modify: `src/rflp_lite/application/mbse_exchange.py`
- Create: `tests/application/test_mbse_semantic_gaps.py`
- Modify: `tests/application/test_mbse_semantics.py`
- Modify: `tests/application/test_sysml_v2.py`

**Interfaces:**
- `build_mbse_semantic_model()` returns valid entities plus explicit `needs_analysis` gap records.
- `validate_mbse_semantic_model()` rejects unknown relation kinds and invalid endpoint matrices.

- [ ] **Step 1: Add regression tests for absence of fabricated realization**

Given accepted requirements with no architecture evidence, assert no Function/Logical/Physical placeholder is added and no `satisfiedBy`, `allocatedTo`, or `realizedBy` relation is emitted. Assert the model contains a gap for each missing layer.

- [ ] **Step 2: Add tests for evidence-backed relations**

Given explicit architecture items with matching `requirement_ids`, assert only the matching `satisfiedBy` relation exists; given explicit allocation/realization evidence, assert those relations are preserved.

- [ ] **Step 3: Add unknown-relation rejection tests**

Assert `validate_mbse_semantic_model()` returns a diagnostic for an unknown kind and `build_mbse_semantic_model()` excludes it from formal relations instead of normalizing it to `relatedTo`.

- [ ] **Step 4: Remove modulo and fabricated technical behavior**

Delete the fallback loops that create `function-*`, `logical-*`, `physical-*` entities and the `index % len(...)` allocations. Replace technical requirement creation with a predicate requiring an explicit verification method/parameter/domain rule.

- [ ] **Step 5: Add gap-aware legacy projection/export handling**

Project only formal entities/relations to legacy collections; expose gap records as `needs-analysis` items without pretending they are accepted architecture. Keep JSON/SysML export valid for incomplete models.

- [ ] **Step 6: Run MBSE tests**

Run: `.venv/bin/python -m pytest tests/application/test_mbse_semantics.py tests/application/test_mbse_semantic_gaps.py tests/application/test_mbse_modeling.py tests/application/test_sysml_v2.py -q`

Expected: PASS with updated assertions reflecting evidence-backed semantics.

### Task 8: Upgrade JobService to a recoverable state machine

**Files:**
- Modify: `src/rflp_lite/ports/jobs.py`
- Modify: `src/rflp_lite/application/jobs.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Create: `tests/application/test_jobs_recovery.py`
- Modify: `tests/application/intelligence/test_enrichment_jobs.py`

**Interfaces:**
- `JobRepositoryPort.recover_startup(now: float | None = None) -> tuple[dict[str, object], ...]`.
- `JobRepositoryPort.heartbeat(job_id: str, lease_id: str, now: float | None = None) -> dict[str, object] | None`.
- `JobRepositoryPort.retry(job_id: str, runner: JobRunner) -> dict[str, object]`.
- State set: `queued`, `running`, `succeeded`, `degraded`, `failed`, `interrupted`.

- [ ] **Step 1: Add recovery and idempotency tests**

Persist a running job with an expired lease, call `recover_startup()`, and assert `interrupted`. Retry with a stable idempotency key and assert succeeded blocks are not rerun. Assert exceptions populate `last_error` and increment `attempt`.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/test_jobs_recovery.py -q`

Expected: FAIL because the new Job Port methods do not exist.

- [ ] **Step 3: Implement durable fields and atomic transitions**

Extend the existing JSON record with `attempt`, `lease_id`, `lease_expires_at`, `heartbeat_at`, `last_error`, `block_states`, and `idempotency_key`. Use the existing temp-file + `os.replace` write path for every transition.

- [ ] **Step 4: Implement startup recovery and retry selection**

On `JobService` initialization, mark only `running` records without a valid lease as `interrupted`. The enrichment runner selects only non-succeeded block IDs and writes a new revision per successful block.

- [ ] **Step 5: Add heartbeat in the block loop**

Refresh the lease before and after each block; when heartbeat fails, stop the worker and mark the job interrupted rather than pretending the daemon thread remains authoritative.

- [ ] **Step 6: Run job and enrichment tests**

Run: `.venv/bin/python -m pytest tests/application/test_jobs_recovery.py tests/application/intelligence/test_enrichment_jobs.py -q`

Expected: PASS.

### Task 9: Close the Web/CLI interaction loop

**Files:**
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-review.html`
- Modify: `src/rflp_lite/interface/web/templates/run-center.html`
- Modify: `src/rflp_lite/interface/web/templates/rflp-model.html`
- Modify: `src/rflp_lite/interface/web/templates/mbse-diagrams.html`
- Modify: `src/rflp_lite/application/mbse_views.py`
- Create: `tests/interface/test_interaction_closure.py`

**Interfaces:**
- Presenter maps block IDs to Chinese labels and returns diagnostic/stale/gap fields without exposing implementation-only IDs as the primary label.
- View-render functions read saved semantic state and never call `GenerativeModel`.

- [ ] **Step 1: Add route/presenter tests**

Assert the input page hides advanced pack/model controls by default, progress exposes Chinese labels and per-block retry, review exposes provenance and stale groups, and MBSE view rendering does not call a fake model.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/interface/test_interaction_closure.py -q`

Expected: FAIL until presenter fields and retry routes exist.

- [ ] **Step 3: Add per-block retry action**

Add a POST route for retrying one failed/degraded/interrupted block. Validate the block ID against the saved Job, invoke the same Use Case/Job runner, and reject retry of `succeeded` blocks.

- [ ] **Step 4: Add visible status, provenance, stale, and gap fields**

Update presenters/templates with Chinese labels, error reason, producer, confidence, source region IDs, stale downstream groups, and explicit `needs-analysis` styling.

- [ ] **Step 5: Keep view switching read-only**

Ensure `mbse_views` and diagram endpoints consume the saved semantic model and selected renderer only; no path invokes a generation port.

- [ ] **Step 6: Run interface tests and render a local smoke page**

Run: `.venv/bin/python -m pytest tests/interface tests/application/test_mbse_views.py -q`

Expected: PASS; route paths and payload compatibility remain intact.

### Task 10: Add E2E, architecture, schema, and CI quality gates

**Files:**
- Modify: `tests/architecture/test_dependency_boundaries.py`
- Create: `tests/contracts/test_analysis_block_contract.py`
- Create: `tests/e2e/test_cross_workspace_and_partial_failure.py`
- Modify: `pyproject.toml`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`

**Interfaces:**
- Test fixtures expose two isolated workspaces, fake model responses, and deterministic repository/job adapters.
- CI command remains compatible with local development: pytest, Import Linter, compileall, and schema checks.

- [ ] **Step 1: Add architecture guards**

Fail on new Application/Interface adapter imports, new Use Case global dependency calls, route-level repository/LLM acquisition, and Application raw `chat_completion` calls.

- [ ] **Step 2: Add contract fixture matrix**

Cover empty response, truncated JSON with one repair, extra field, missing required field, bad confidence/NaN, unknown enum, missing source region, invalid relation endpoint/type, duplicate ID, provider 5xx/timeout, and valid transactional merge.

- [ ] **Step 3: Add E2E gates**

Run two workspaces concurrently and reject forged cross-project IDs; fail one architecture block while preserving other successes; edit one accepted requirement and assert only downstream objects become stale; switch all MBSE views without increasing model-call count; test renderer fallback and Evidence-only test execution.

- [ ] **Step 4: Run the complete verification set**

Run:

```bash
.venv/bin/python -m compileall -q src
.venv/bin/python -m pytest -q
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
```

Expected: all commands exit 0.

- [ ] **Step 5: Update status documentation**

Record completed phases, remaining compatibility callers if any, test counts, and the final acceptance criteria in `docs/DEVELOPMENT_STATUS.md` and `docs/CURRENT_ARCHITECTURE.md`.

## Self-review checklist

- [ ] All requirements from document section 9.1 map to Tasks 2, 3, 4, 5, 6, 7, 8, and 9.
- [ ] All final standards map to Tasks 1, 4, 6, 7, 8, 9, and 10.
- [ ] No task relies on an undefined file, type, or method.
- [ ] Existing CLI/Web/storage compatibility is explicit in Global Constraints and Tasks 3/9.
- [ ] Failure paths preserve prior successful Block state and reject invalid LLM data.

