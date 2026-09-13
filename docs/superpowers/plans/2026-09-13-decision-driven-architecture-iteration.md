# Decision-Driven Architecture Iteration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让已确认的 Logical/Physical Trade Study 选项真正驱动局部架构变体生成，并在同一 ModelGraph 上重新计算追溯、方法论和下一步 Controller 动作。

**Architecture:** 复用现有 `ControllerAction → controller_decision → ContextBundle → ModelGenerationService.reanalyze` 链路，只扩展离线 `VerticalRuleRuntime` 对结构化决定的消费。Logical 选择通过 CAS Patch 弃用未锁定旧分区并生成带 `architecture_decision` 的新分区；Physical 选择生成或更新候选变体，继续复制约束和 provenance，不改变未知测量或冲突语义。锁定/用户修改实体不被覆盖，旧候选始终保留为历史和比较依据。

**Tech Stack:** Python 3.11+, typed `ModelGraph`, existing `Patch`/`Deprecate`/`UpdateEntity`, `VerticalRuleRuntime`, `MethodologyEngine`, FastAPI Resource API, pytest.

## Global Constraints

- 保留现有 Controller API、CAS、PatchPolicy、Review、Run/Step 和审计边界。
- 不新增 EntityKind，不自动修改 Requirement 数值，不凭 Trade Study 选择填充物理实测值或宣称可行。
- 只消费 `option`、`option_id`、`action_id`、`task_id`、`revision` 这些有限标量决定字段。
- 未知 option、缺失 option、锁定实体和用户修改实体必须保持可追溯并给出兼容回退或明确阻塞，不抛出未处理异常。
- 旧实体和关系保留；弃用实体不再参与 active ModelGraph 分析，关系记录仍可用于历史追溯。
- 现有架构预算 `dict_str_object_occurrences=115` 不得增加，新增类型注解使用 `Mapping`/集合接口而不是 `dict[str, object]`。

---

### Task 1: Define failing tests for decision-aware Runtime variants

**Files:**
- Modify: `tests/runtime/test_vertical_rule_runtime.py`
- Modify: `tests/application/test_model_generation.py`
- Modify: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: `ContextBundle.controller_decisions`, `TaskExecutionRequest`, `VerticalRuleRuntime.execute`.
- Produces: tests for Logical repartition, shared coordinator, Physical alternative, lock protection and API-level decision flow.

- [ ] **Step 1: Add the Logical decision request helper and failing tests**

Add this helper to `tests/runtime/test_vertical_rule_runtime.py`:

```python
def _logical_request(entities, relations=(), decision=None):
    context = ContextBundle(
        "robot", "vertical.logical", 3, tuple(entities), tuple(relations),
        controller_decisions=(decision,) if decision else (),
    )
    return TaskExecutionRequest(
        "vertical.logical", "v2.1", context, (),
        {"output_kinds": ["logical_component", "interface", "state"]}, 3000,
    )
```

Add tests that create two Functions sharing `task_state`, an existing validated Logical Component, and `ALLOCATED_TO` relations; execute a decision with `option="one_component_per_function"`; apply the returned patch; and assert the old component is deprecated, two active components exist, and each has `architecture_variant` plus an `architecture_decision.option_id`. Add a second test with `option="shared_coordinator"` and assert one generated Logical Component has `architecture_variant="shared_coordinator"` and `coupling="high"`.

- [ ] **Step 2: Add failing Physical, lock, and API assertions**

Add a Runtime test with a Requirement containing `constraints: {"max_power_w": 50}`, an existing Physical Block with `power_w: 80`, and a decision whose option is `更换物理候选或计算架构`. Assert that the returned patch contains a Physical Block with `candidate_variant="alternative"`, the same `propagated_constraints`, the same Requirement source ID, and the decision option ID.

Add a Runtime test with a locked Logical Component and `shared_coordinator`; assert no returned operation deprecates the locked ID and a generated variant contains `blocked_by_locked_entity=True`.

Extend the existing API Trade Study test after its decision response:

```python
model_after_decision = client.get("/projects/p1/model").json()
assert any(
    entity["payload"].get("architecture_decision", {}).get("option_id") == option["id"]
    for entity in model_after_decision["entities"]
)
```

- [ ] **Step 3: Run the new tests and confirm they fail**

```bash
./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py -q -k 'variant or trade or locked'
./.venv/bin/pytest tests/interface/web/test_vertical_generation_api.py -q -k trade_study_decision
```

Expected: failures because the current Vertical Runtime ignores `controller_decisions` and emits no architecture variants.

---

### Task 2: Implement bounded decision helpers and Logical variants

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py`
- Test: `tests/runtime/test_vertical_rule_runtime.py`

**Interfaces:**
- Consumes: one `ContextBundle.controller_decisions` mapping.
- Produces: Logical Patch operations with bounded decision provenance, active Function allocations, and lock-safe deprecations.

- [ ] **Step 1: Add safe builder and decision helpers**

Import `Deprecate` and initialize `self.deprecated = set()` in `_VerticalPatchBuilder`. Add:

```python
    def deprecate(self, entity) -> None:
        if entity.meta.status in {EntityStatus.DEPRECATED, EntityStatus.LOCKED}:
            return
        if bool(entity.payload.get("user_modified")) or entity.id in self.deprecated:
            return
        self.deprecated.add(entity.id)
        self.operations.append(Deprecate(entity.id))

    def update_payload(self, entity, payload: Mapping[str, object]) -> bool:
        if entity.meta.status in {EntityStatus.DEPRECATED, EntityStatus.LOCKED}:
            return False
        if bool(entity.payload.get("user_modified")):
            return False
        self.operations.append(UpdateEntity(entity.id, {"payload": dict(payload)}))
        return True
```

Add these bounded helpers:

```python
_LOGICAL_VARIANTS = frozenset({
    "one_component_per_function", "shared_coordinator", "current_dependency_partition",
})
_PHYSICAL_VARIANTS = frozenset({
    "更换物理候选或计算架构", "降低计算或功耗需求",
    "调整需求约束或资源预算", "增加电池质量或资源预算",
})


def _controller_decision(context):
    for raw in reversed(context.controller_decisions):
        if isinstance(raw, Mapping):
            return raw
    return {}


def _decision_payload(decision: Mapping[str, object]) -> Mapping[str, object]:
    return {
        "action_id": str(decision.get("action_id", "")),
        "option_id": str(decision.get("option_id", "")),
        "option": str(decision.get("option", "")),
        "task_id": str(decision.get("task_id", "")),
        "source_revision": int(decision.get("revision", 0) or 0),
    }
```

Do not copy arbitrary controller fields into a graph payload.

- [ ] **Step 2: Apply Logical partition decisions**

At the start of `_logical`, choose groups as follows:

```python
decision = _controller_decision(request.context_bundle)
option = str(decision.get("option", "")).strip()
variant = option if option in _LOGICAL_VARIANTS else ""
functions = _context_entities(request.context_bundle, EntityKind.FUNCTION)
groups = _partition_functions(functions)
if variant == "one_component_per_function":
    groups = tuple((function,) for function in functions)
elif variant == "shared_coordinator" and functions:
    groups = (tuple(functions),)
```

For a recognized variant, deprecate active existing Logical Components, Interfaces, and States when they are not locked or user-modified. Generate variant-suffixed names and merge the existing Logical payload fields with:

```python
{
    "architecture_variant": variant,
    "architecture_decision": _decision_payload(decision),
    "blocked_by_locked_entity": bool(locked_or_user_modified_components),
}
```

Only include `blocked_by_locked_entity` when it is true. Set `coupling="high"` for `shared_coordinator`; preserve the current controlled/isolated behavior for `one_component_per_function`. Connect Functions, Logical Components, Interface, and State through the existing predicates. If the option is unknown or absent, preserve the current no-decision path exactly.

- [ ] **Step 3: Run Runtime tests and lint**

```bash
./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py -q -k 'variant or trade or locked'
./.venv/bin/ruff check src/rflp_lite/runtime/rule_based.py tests/runtime/test_vertical_rule_runtime.py
```

Expected: all new tests pass and Ruff reports no issues.

- [ ] **Step 4: Commit Logical iteration**

```bash
git add src/rflp_lite/runtime/rule_based.py tests/runtime/test_vertical_rule_runtime.py
git commit -m "feat: apply logical trade study decisions"
```

---

### Task 3: Implement Physical candidate variants without false feasibility

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py`
- Test: `tests/runtime/test_vertical_rule_runtime.py`

**Interfaces:**
- Consumes: bounded decision helpers and `_physical_payload` Requirement propagation.
- Produces: alternative Physical Blocks or lock-safe decision payload updates with constraints and provenance intact.

- [ ] **Step 1: Generate an alternative Physical Block**

At the start of `_physical`, consume only options in `_PHYSICAL_VARIANTS`; ignore Logical options in this stage. For `更换物理候选或计算架构`, add one candidate per active Logical Component with a deterministic name ending in `替代候选` and merge these fields into `_physical_payload(logical, requirements)`:

```python
{
    "candidate_variant": "alternative",
    "architecture_decision": _decision_payload(decision),
    "open_questions": ["替代物理候选的 SWaP-C 需要测量并重新验证"],
}
```

Allocate the alternative to the Logical Component. Keep the old block and its relations for comparison; an old measured conflict must remain visible.

- [ ] **Step 2: Record other Physical decisions safely**

For the other three Physical options, update an unlocked, non-user-modified existing Physical Block with `architecture_decision` and an `open_questions` entry. Do not change `power_w`, `mass_kg`, `endurance_h`, propagated constraints, or Requirement payloads. When update is blocked by a lock or user modification, create an alternative candidate with `candidate_variant="alternative"` and `blocked_by_locked_entity=True`; it remains unmeasured.

- [ ] **Step 3: Run Physical and regression tests**

```bash
./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py tests/application/test_model_generation.py tests/methodology/test_engine.py -q
./.venv/bin/ruff check src/rflp_lite/runtime/rule_based.py tests/runtime/test_vertical_rule_runtime.py
```

Expected: all tests pass and existing physical conflict/measurement semantics remain unchanged.

- [ ] **Step 4: Commit Physical iteration**

```bash
git add src/rflp_lite/runtime/rule_based.py tests/runtime/test_vertical_rule_runtime.py
git commit -m "feat: generate physical trade study variants"
```

---

### Task 4: Prove the complete Controller/API iteration loop

**Files:**
- Modify: `tests/application/test_model_generation.py`
- Modify: `tests/interface/web/test_vertical_generation_api.py`
- Modify: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: existing `execute_controller_action`, `reanalyze`, `controller_decision`, and `/controller/execute` response.
- Produces: evidence that a selected option changes ModelGraph while preserving active traceability and unresolved findings.

- [ ] **Step 1: Add an application-level Logical decision test**

Generate a project, edit two Functions to share `shared_state`, obtain the Logical Trade Study action, select `one_component_per_function`, and assert an increased revision, a deprecated old Logical Component, active variant components, `controller_decision` in the reanalysis response, and a nonzero complete traceability count. Pass `expected_revision` on every write.

- [ ] **Step 2: Extend the API Physical alternative test**

In `test_controller_trade_study_decision_runs_only_affected_downstream_stages`, choose the option labelled `更换物理候选或计算架构` and assert:

```python
assert payload["reanalysis"]["selected_stages"] == [
    "physical", "verification_validation"
]
assert any(
    item["payload"].get("candidate_variant") == "alternative"
    for item in client.get("/projects/p1/model").json()["entities"]
    if item["kind"] == "physical_block"
)
assert "physical_constraint_conflict" in {
    item["code"] for item in payload["reanalysis"]["methodology"]["findings"]
}
```

- [ ] **Step 3: Run Controller/API/E2E tests**

```bash
./.venv/bin/pytest tests/application/test_model_generation.py tests/interface/web/test_vertical_generation_api.py tests/e2e/test_vertical_model_generation.py -q
```

Expected: all tests pass, including existing CAS, lock, Controller iteration and SysML round-trip tests.

- [ ] **Step 4: Commit the end-to-end proof**

```bash
git add tests/application/test_model_generation.py tests/interface/web/test_vertical_generation_api.py tests/e2e/test_vertical_model_generation.py
git commit -m "test: prove decision-driven architecture iteration"
```

---

### Task 5: Document, verify, and push

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/plans/2026-09-13-decision-driven-architecture-iteration.md`

**Interfaces:**
- Consumes: Runtime variants, Controller loop and API/E2E evidence.
- Produces: documented user behavior and a GitHub-synchronized branch.

- [ ] **Step 1: Document the actual iteration behavior**

State that a user-selected Logical/Physical Trade Study flows through ContextBundle into local reanalysis; the result is a versioned architecture variant with decision provenance, while old candidates and unresolved measurement/conflict findings remain visible.

- [ ] **Step 2: Mark this plan complete and scan it**

Change every checkbox in this plan to `[x]`, then run:

```bash
rg -n '^- \[ \]' docs/superpowers/plans/2026-09-13-decision-driven-architecture-iteration.md || true
git diff --check
```

Expected: no unchecked step and no placeholder output.

- [ ] **Step 3: Run complete verification**

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```

Expected: every command exits 0 and architecture metrics remain `dict_str_object_occurrences=115`, `functions_over_150_lines=0`, `module_cycles=0`, and `adapter_to_application_edges=0`.

- [ ] **Step 4: Commit documentation and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/plans/2026-09-13-decision-driven-architecture-iteration.md
git commit -m "docs: record decision-driven architecture iteration"
git push origin codex/web-audit-2026-08-18
test "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}')"
```

Expected: the branch is clean and local HEAD equals `origin/codex/web-audit-2026-08-18`.
