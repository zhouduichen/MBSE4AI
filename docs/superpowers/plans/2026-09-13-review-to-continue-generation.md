# Review 后继续生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit Review-to-Continue operation that runs only downstream vertical stages and preserves user-confirmed ModelGraph entities.

**Architecture:** Add one canonical entity-kind-to-vertical-stage mapping beside the existing five-stage contracts. `ModelGenerationService.continue_generation` will validate the user-confirmed trigger, select stages after its layer, execute the existing `TaskExecutor` pipeline in a `vertical_continuation` Run, and return the same trace/methodology payload used by normal generation. The Web workbench will call a small resource endpoint and render the result without exposing TaskSpec, Patch, or CAS internals.

**Tech Stack:** Python 3.11+, dataclasses, SQLite ModelGraph/Run ledger, FastAPI/Jinja, existing Runtime/Validator/CAS layers, pytest, Ruff.

## Global Constraints

- 五阶段 UX 顺序固定为 Requirements → Functional → Logical → Physical → Verification & Validation。
- ModelGraph 是唯一内部语义真源；SysML v2 只是 interchange/export format。
- 继续生成是显式用户动作，不在 Accept/Lock 请求中自动调用 LLM。
- 触发实体状态必须为 `accepted` 或 `locked`；`locked` 实体可以作为只读上下文但不能被更新。
- 继续生成从触发实体所属阶段的下一个阶段开始，不重复改写已确认阶段。
- 继续生成使用独立 `vertical_continuation` Run，并保留 CAS、Revision、审计和现有失败语义。
- 不增加数据库表、第三方依赖或新的 Runtime/编排器。

---

### Task 1: Add canonical downstream routing and application continuation service

**Files:**
- Modify: `src/rflp_lite/methodology/vertical_generation.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Test: `tests/methodology/test_vertical_generation.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: `VerticalStage`, `VerticalStageSpec`, `EntityKind`, `MethodologyEngine`, existing `_execute_stage` and `_reanalysis_payload` behavior.
- Produces: `vertical_stage_index_for_kind(kind: EntityKind) -> int`, `downstream_vertical_stages(kind: EntityKind) -> tuple[VerticalStageSpec, ...]`, and `ModelGenerationService.continue_generation(project_id: str, entity_id: str, *, expected_revision: int | None = None, controller_decision: Mapping[str, object] | None = None) -> Mapping[str, object]`.

- [ ] **Step 1: Write failing routing and service tests**

Add these assertions to the existing tests:

```python
def test_downstream_routing_skips_the_confirmed_stage():
    assert [item.stage.value for item in downstream_vertical_stages(EntityKind.FUNCTION)] == [
        "logical", "physical", "verification_validation"
    ]
    assert downstream_vertical_stages(EntityKind.VALIDATION_CASE) == ()
```

For the application path, generate an offline model, accept its Function, call `continue_generation`, and assert `selected_stages` starts at `logical`, the trigger ID/status/name/payload/updated revision are unchanged, and the returned `run_id` is different from the original generation run.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/methodology/test_vertical_generation.py tests/application/test_model_generation.py -q
```

Expected: FAIL because downstream routing and `continue_generation` do not exist.

- [ ] **Step 3: Implement canonical routing**

In `vertical_generation.py`, define the product-stage index once:

```python
_KIND_STAGE_INDEX = {
    EntityKind.SYSTEM: 0,
    EntityKind.STAKEHOLDER: 0,
    EntityKind.CONCERN: 0,
    EntityKind.LIFECYCLE_STAGE: 0,
    EntityKind.LIFECYCLE_TRANSITION: 0,
    EntityKind.SCENARIO_HYPOTHESIS: 0,
    EntityKind.USE_CASE: 0,
    EntityKind.OPERATIONAL_SCENARIO: 0,
    EntityKind.ACTIVITY: 0,
    EntityKind.REQUIREMENT: 0,
    EntityKind.FUNCTION: 1,
    EntityKind.FUNCTIONAL_FLOW: 1,
    EntityKind.FUNCTIONAL_SCENARIO: 1,
    EntityKind.LOGICAL_COMPONENT: 2,
    EntityKind.INTERFACE: 2,
    EntityKind.STATE: 2,
    EntityKind.PHYSICAL_BLOCK: 3,
    EntityKind.HAZARD: 4,
    EntityKind.FAILURE_MODE: 4,
    EntityKind.VERIFICATION_CASE: 4,
    EntityKind.VALIDATION_CASE: 4,
    EntityKind.EVIDENCE: 4,
}

def vertical_stage_index_for_kind(kind: EntityKind) -> int:
    return _KIND_STAGE_INDEX.get(EntityKind(kind), 0)

def downstream_vertical_stages(kind: EntityKind) -> tuple[VerticalStageSpec, ...]:
    return vertical_stage_specs()[vertical_stage_index_for_kind(kind) + 1:]
```

Use this mapping for the existing reanalysis start lookup as well, so continuation and reanalysis cannot drift.

- [ ] **Step 4: Implement continuation with existing stage execution**

Add `continue_generation` to `ModelGenerationService` with this behavior:

```python
graph = self.repository.load_graph(project_id)
if expected_revision is not None and int(expected_revision) != graph.revision:
    raise ConflictError(...)
entity = graph.entity_index.get(entity_id)
if entity is None:
    raise ContractViolation(...)
if entity.meta.status not in {EntityStatus.ACCEPTED, EntityStatus.LOCKED}:
    raise ContractViolation("only accepted or locked entities can continue generation")
stages = downstream_vertical_stages(entity.kind)
```

When `stages` is empty, return a payload with `execution_status="no_downstream_work"`, the current revision, empty `stage_results`, current traceability/methodology/controller, and do not create a Run or Revision. Otherwise create a new Run with `phase="vertical_continuation"`, audit `model_generation.continuation.started`, execute each selected stage through `_execute_stage(..., controller_decision=controller_decision)`, stop and mark the Run failed on the first structural/reference/policy failure, then compute the final graph report and return `_reanalysis_payload`-compatible fields with `execution_status="completed"` and `selected_stages`.

Before appending a generated patch, retain the existing `TaskExecutor.validate_response` identity check. It must reject `UpdateEntity` operations targeting a locked or `user_modified` entity; relation additions that merely reference a locked trigger remain allowed. Record `model_generation.continuation.completed` with trigger ID, selected stages, revision and traceability.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
./.venv/bin/python -m pytest tests/methodology/test_vertical_generation.py tests/application/test_model_generation.py -q
./.venv/bin/ruff check src/rflp_lite/methodology/vertical_generation.py src/rflp_lite/application/model_generation.py tests/methodology/test_vertical_generation.py tests/application/test_model_generation.py
```

Expected: PASS.

```bash
git add src/rflp_lite/methodology/vertical_generation.py src/rflp_lite/application/model_generation.py tests/methodology/test_vertical_generation.py tests/application/test_model_generation.py
git commit -m "feat: continue model generation after review"
```

### Task 2: Expose continuation in the resource API and ModelGraph workbench

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/requirement-detail.html`
- Test: `tests/interface/web/test_model_workbench.py`
- Test: `tests/interface/web/test_review_actions.py`

**Interfaces:**
- Consumes: `ModelGenerationService.continue_generation` and `POST /projects/{project_id}/entities/{entity_id}/continue`.
- Produces: a JSON `continuation` payload and a visible `继续生成下游` action on cards for Requirements/Functional/Logical/Physical entities.

- [ ] **Step 1: Write failing API/page tests**

Add tests that generate a model through the API, accept a Function, call:

```python
response = client.post(
    f"/projects/p1/entities/{function_id}/continue",
    json={"expected_revision": accepted_revision},
)
assert response.status_code == 200
assert response.json()["continuation"]["selected_stages"][0] == "logical"
```

Add a page assertion for `继续生成下游` and `data-review-action="continue"`; assert the accepted Requirement detail page also exposes `data-action="continue"`, while a V&V-only fixture does not render that action.

- [ ] **Step 2: Run the focused interface tests and verify failure**

Run:

```bash
./.venv/bin/python -m pytest tests/interface/web/test_model_workbench.py -q
```

Expected: FAIL because the route and button do not exist.

- [ ] **Step 3: Add the API endpoint**

Place the endpoint beside the existing entity review endpoints:

```python
@resource_api.post("/projects/{project_id}/entities/{entity_id}/continue")
async def continue_entity_generation(request: Request, project_id: str, entity_id: str):
    try:
        payload = await _json_object(request)
        result = _services(request).generation(project_id).continue_generation(
            project_id,
            entity_id,
            expected_revision=_expected_revision(payload),
        )
        return {"status": "ok", "continuation": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
```

The route must return the existing error mapping, including 409 for stale revision/locked write conflicts, and must not call the old request-only reanalysis endpoint.

- [ ] **Step 4: Add the workbench action**

In `model_workbench.py`, expose `can_continue` when the card kind is in the first four product layers and the status is `accepted` or `locked`; expose `continue_label` as `继续生成下游` or `基于锁定实体继续生成`. Render a button only when `can_continue` is true. Extend the workbench script to POST `/continue` with the page revision, display API errors in the existing feedback area, and reload only after `status == "ok"`. Add the same explicit action to `requirement-detail.html`, because Requirements remain a separate user-facing workbench; its existing request-only and execute-reanalysis actions remain unchanged.

- [ ] **Step 5: Run interface tests and commit**

Run:

```bash
./.venv/bin/python -m pytest tests/interface/web/test_model_workbench.py tests/interface/web/test_review_actions.py tests/interface/web/test_vertical_generation_api.py -q
./.venv/bin/ruff check src/rflp_lite/interface/web/resource_api.py tests/interface/web/test_model_workbench.py tests/interface/web/test_review_actions.py
```

Expected: PASS.

```bash
git add src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/templates/model.html src/rflp_lite/interface/web/templates/requirement-detail.html tests/interface/web/test_model_workbench.py tests/interface/web/test_review_actions.py
git commit -m "feat: expose downstream continuation in model workbench"
```

### Task 3: Prove lock protection, no-op continuation, and document the product loop

**Files:**
- Modify: `tests/application/test_model_generation.py`
- Modify: `tests/interface/web/test_model_workbench.py`
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: continuation service/API, identity validator, existing SysML/traceability assertions.
- Produces: regression evidence for accepted/candidate/locked/V&V semantics and user-facing documentation of the explicit iteration loop.

- [ ] **Step 1: Add the lock and no-downstream regressions**

Use a scripted continuation runtime that returns an `UpdateEntity` for the locked trigger during `vertical.logical`; assert continuation returns `execution_status="failed"`, the graph snapshot and trigger payload are unchanged, and the continuation Run is marked failed. Also assert a candidate trigger returns HTTP 422/contract failure until accepted, and a ValidationCase returns `no_downstream_work` with unchanged graph revision.

- [ ] **Step 2: Update product documentation**

Add the explicit loop to the Web and product-path sections:

```text
Review 实体 → 接受/锁定 → 继续生成下游 → 重新计算 Trace/Methodology → Review 新结果
```

Document that locked entities are read-only anchors and that V&V is the terminal stage for continuation.

- [ ] **Step 3: Run the complete verification matrix**

Run:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
git diff --check
```

Expected: all tests pass, architecture metrics remain within budget, import-linter reports 0 broken contracts, and diff check is clean.

- [ ] **Step 4: Commit and push the product slice**

```bash
git add tests/application/test_model_generation.py tests/interface/web/test_model_workbench.py README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md
git commit -m "docs: document review continuation loop"
git push origin HEAD
```
