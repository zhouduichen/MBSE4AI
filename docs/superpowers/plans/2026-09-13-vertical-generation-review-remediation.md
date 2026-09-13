# 纵向模型生成评审修正实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正语义失败放行和宽松追溯口径，并把五阶段入口补成保留完整 Operational/Architecture reasoning 的产品链。

**Architecture:** 保留 `ModelGenerationService` 作为产品编排器，扩展 `TaskProposal` 的有界决策记录和 `VerticalStageSpec` 的内部任务映射。语义失败保存候选并建 Issue，结构失败仍拒绝；追溯服务用有效状态过滤下游实体，并分别计算 RFLP、Verification、Validation 和端到端覆盖。

**Tech Stack:** Python 3.11+, dataclasses, SQLite ModelGraph/Run Ledger, JSON Schema, FastAPI/Jinja, pytest, Ruff, import-linter。

## Global Constraints

- 五阶段 UX 顺序固定为 Requirements → Functional → Logical → Physical → Verification & Validation。
- 23-task catalog 保留，并作为五阶段的内部 reasoning task 映射，不删除旧 pipeline 入口。
- `semantic_invalid` 只能保存 `CANDIDATE`，不得保存为 `VALIDATED`。
- `end_to_end_complete` 必须同时需要 `satisfiedBy`、两级 `allocatedTo`、`verifiedBy` 和 `validatedBy`。
- 不增加外部依赖；保持 SysML v2 subset 的现有 round-trip 行为。

---

### Task 1: Lock semantic candidate behavior

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: `TaskExecutor.validate_response`, `MethodologyValidationError`, `ModelRepository.save_issue`。
- Produces: `_promote_generated_entities(patch, validated: bool)`, `StageResult.status == "needs_review"` for semantic failures, and an open `semantic_invalid` issue.

- [ ] **Step 1: Write the failing test**

Add a scripted model output whose Functional stage contains a hardware-specific Function name. Assert that generation returns `completed_with_warnings`, the Function status is `candidate`, and the project has an open `semantic_invalid` issue.

- [ ] **Step 2: Run the focused test**

Run:

```bash
./.venv/bin/python -m pytest tests/application/test_model_generation.py -q
```

Expected: FAIL because the current implementation removes the semantic validator and promotes the Function to `validated`.

- [ ] **Step 3: Implement the explicit semantic branch**

Use this behavior inside `_execute_stage`:

```python
semantic_invalid = None
try:
    self.executor.validate_response(project_id, task, graph, context, response)
except MethodologyValidationError as exc:
    if exc.code != "semantic_invalid":
        raise
    semantic_invalid = str(exc)
    relaxed = replace(task, validators=tuple(item for item in task.validators if item != "semantic"))
    self.executor.validate_response(project_id, relaxed, graph, context, response)

patch = _promote_generated_entities(response.patch, validated=semantic_invalid is None)
if semantic_invalid:
    self.repository.save_issue(project_id, {
        "id": f"issue-{canonical_hash((run_id, task.id, semantic_invalid))[:16]}",
        "run_id": run_id,
        "task_id": task.id,
        "code": "semantic_invalid",
        "severity": "warning",
        "entity_ids": [operation.entity.id for operation in patch.operations if isinstance(operation, AddEntity)],
        "suggested_rollback": task.id,
        "status": "open",
    })
```

Return `needs_review` and retain candidate status when `semantic_invalid` is set. Only `validated=True` may promote LLM entities.

- [ ] **Step 4: Run the focused test**

Run the same pytest command. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py
git commit -m "fix: keep semantic-invalid model output in review"
```

### Task 2: Split traceability into RFLP, verification, validation, and end-to-end

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py`
- Test: `tests/application/test_model_generation.py`
- Test: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: `ModelGraph`, `RelationPredicate`, entity status.
- Produces: `TraceabilitySummary` fields `rflp_complete_count`, `verification_complete_count`, `validation_complete_count`, `end_to_end_complete_count`, plus backward-compatible aliases.

- [ ] **Step 1: Write failing tests**

Construct graphs with RFLP only, RFLP plus Verification, RFLP plus Validation, and all five links. Assert only the last graph has `end_to_end_complete_count == 1`; assert old `complete_count` equals the end-to-end count.

- [ ] **Step 2: Run the focused tests**

```bash
./.venv/bin/python -m pytest tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py -q
```

Expected: FAIL because the current summary counts Verification **or** Validation as complete.

- [ ] **Step 3: Implement status-aware split metrics**

Filter downstream entities to `validated`, `accepted`, or `locked`; keep the root Requirement active unless rejected/deprecated. Compute the four independent counters and set `complete_count` to `end_to_end_complete_count`. Include both verification and validation IDs in complete paths.

- [ ] **Step 4: Run focused and API tests**

```bash
./.venv/bin/python -m pytest tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py tests/interface/web/test_vertical_generation_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py
git commit -m "fix: split model generation traceability metrics"
```

### Task 3: Preserve operational reasoning inside Requirements

**Files:**
- Modify: `src/rflp_lite/methodology/vertical_generation.py`
- Modify: `src/rflp_lite/resources/prompts/vertical/requirements.v1.md`
- Modify: `src/rflp_lite/runtime/rule_based.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Test: `tests/methodology/test_vertical_generation.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: existing 23-task catalog and `VerticalStageSpec`.
- Produces: `reasoning_tasks` mapping and Requirements minimum kinds containing lifecycle, scenario, use case, activity, and requirement objects.

- [ ] **Step 1: Write failing contract tests**

Assert Requirements `required_kinds` contains `SYSTEM`, `STAKEHOLDER`, `LIFECYCLE_STAGE`, `SCENARIO_HYPOTHESIS`, `USE_CASE`, `OPERATIONAL_SCENARIO`, `ACTIVITY`, and `REQUIREMENT`; assert the stage exposes the internal task IDs.

- [ ] **Step 2: Run the focused contract test**

```bash
./.venv/bin/python -m pytest tests/methodology/test_vertical_generation.py -q
```

Expected: FAIL because only System, Stakeholder, and Requirement are required today.

- [ ] **Step 3: Implement the operational contract**

Extend Requirements output kinds, allowed predicates, and `reasoning_tasks`. Update the requirements prompt to require lifecycle stages, scenario hypothesis, use case, operational scenario, activity, and derived requirements with local references. Extend `VerticalRuleRuntime` to produce one deterministic object of each kind and valid relations.

- [ ] **Step 4: Update structured LLM fixture and run tests**

Add those objects and relations to `ScriptedModel` in `tests/application/test_model_generation.py`, then run:

```bash
./.venv/bin/python -m pytest tests/methodology/test_vertical_generation.py tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/methodology/vertical_generation.py src/rflp_lite/resources/prompts/vertical/requirements.v1.md src/rflp_lite/runtime/rule_based.py src/rflp_lite/application/model_generation.py tests/methodology/test_vertical_generation.py tests/application/test_model_generation.py
git commit -m "feat: preserve operational reasoning in requirements stage"
```

### Task 4: Add bounded architecture decision records and SWaP-C fields

**Files:**
- Modify: `src/rflp_lite/methodology/contracts.py`
- Modify: `src/rflp_lite/methodology/proposal_compiler.py`
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/methodology/vertical_generation.py`
- Modify: `src/rflp_lite/resources/prompts/vertical/logical.v1.md`
- Modify: `src/rflp_lite/resources/prompts/vertical/physical.v1.md`
- Modify: `src/rflp_lite/runtime/rule_based.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Test: `tests/methodology/test_proposal_compiler.py`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: TaskProposal metadata contract and five-stage prompt registry.
- Produces: `TaskProposal.decision_records`, `TaskExecutionResponse.decision_records`, `StageResult.decision_records`, and non-placeholder Logical/Physical payload fields.

- [ ] **Step 1: Write failing metadata tests**

Pass `decision_records=[{"step": "dependency_clustering", "decision": "共享配送状态", "basis": ["function-1"]}]` through the compiler/runtime and assert it is returned in the stage result.

- [ ] **Step 2: Run focused tests**

```bash
./.venv/bin/python -m pytest tests/methodology/test_proposal_compiler.py tests/runtime/test_task_execution.py -q
```

Expected: FAIL because decision records are not part of the proposal contract.

- [ ] **Step 3: Implement bounded decision records**

Add a top-level optional `decision_records` array to the proposal schema with `step`, `decision`, and `basis` fields, maximum 24 records. Parse it, carry it through `TaskExecutionResponse`, and expose it in `StageResult.as_dict`.

- [ ] **Step 4: Enrich logical/physical contracts**

Update Logical prompt and offline payloads to cover `partition_basis`, `dependencies`, `shared_state`, `timing_constraints`, `safety_isolation`, `cohesion`, `coupling`, and `architecture_rationale`. Update Physical prompt and payloads to cover `mass_kg`, `power_w`, `compute`, `memory_mb`, `latency_ms`, `bandwidth_mbps`, `cost`, `thermal`, `reliability`, `availability`, `swap_c`, `constraints`, `feasibility`, `alternatives`, and `selection_rationale`.

- [ ] **Step 5: Run focused tests and commit**

```bash
./.venv/bin/python -m pytest tests/methodology/test_proposal_compiler.py tests/runtime/test_task_execution.py tests/application/test_model_generation.py -q
git add src/rflp_lite/methodology/contracts.py src/rflp_lite/methodology/proposal_compiler.py src/rflp_lite/runtime/structured_model.py src/rflp_lite/methodology/vertical_generation.py src/rflp_lite/resources/prompts/vertical/logical.v1.md src/rflp_lite/resources/prompts/vertical/physical.v1.md src/rflp_lite/runtime/rule_based.py src/rflp_lite/application/model_generation.py tests/methodology/test_proposal_compiler.py tests/runtime/test_task_execution.py tests/application/test_model_generation.py
git commit -m "feat: add bounded architecture decisions to vertical generation"
```

### Task 5: Expose the split metrics and reasoning records

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: `GenerateModelResult.as_dict()` with split traceability and stage decision records.
- Produces: UI labels for RFLP/Verification/Validation/End-to-end and a visible needs-review state.

- [ ] **Step 1: Write failing UI/API assertions**

Assert the API JSON contains all four metric families and the analysis page contains `端到端闭环` and `Validation` labels.

- [ ] **Step 2: Implement presentation changes**

Render the four counters, stage status, and a compact list of decision record steps. Keep raw diagnostics and candidate review visible.

- [ ] **Step 3: Run interface tests**

```bash
./.venv/bin/python -m pytest tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/rflp_lite/interface/web/templates/analysis.html README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md tests/interface/web/test_vertical_generation_api.py
git commit -m "docs: expose split vertical generation quality metrics"
```

### Task 6: Full verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run all checks**

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
```

Expected: all tests pass, architecture metrics remain within `architecture_budget.json`, and import-linter reports 5 kept / 0 broken.

- [ ] **Step 2: Inspect the final diff and commit status**

```bash
git diff --check
git status --short
```

Expected: only the intended review-remediation commits are present and no user-owned unrelated files are modified.
