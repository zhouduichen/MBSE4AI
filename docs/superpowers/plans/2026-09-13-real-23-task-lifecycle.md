# 真实 23-task 端到端生命周期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自然语言/文档输入通过现有 `WorkflowRunner` 真正执行 23 个方法论任务，并在同一份 ModelGraph 中形成完整可编辑的 R→F→L→P→V&V 结果。

**Architecture:** 保留 WorkflowRunner、TaskSpec、TaskExecutor、StructuredModelRuntime、CAS、Gate 和交付投影。新增应用层 RequirementInputService 供 pipeline/CLI/文档入口复用，并新增 LifecycleTaskRuleRuntime 为 23 个离线任务提供任务级语义；配置 LLM 时仍由现有 Structured Runtime 逐任务执行。

**Tech Stack:** Python 3.11+, typed ModelGraph, SQLite repository, FastAPI, argparse, pytest, existing structured LLM compiler and SysML subset exchange.

## Global Constraints

- `Typed ModelGraph` remains the only source of truth; SysML, reports, and UI are projections.
- Do not add a database table, provider, second workflow state machine, or external simulation executor.
- A task may be a no-op only when its semantic target already exists during an idempotent rerun.
- Locked or `user_modified` entities are read-only anchors for the lifecycle runtime.
- Unknown physical measurements remain `None`/`needs_measurement`; no fabricated feasibility result is allowed.
- The existing five-stage generation, Controller, SysML, deliverable, and fixture paths must remain passing.

---

### Task 1: Share Requirement input preparation with the 23-task pipeline

**Files:**
- Create: `src/rflp_lite/application/requirement_input.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/cli_v2.py`
- Test: `tests/application/test_requirement_input.py`
- Test: `tests/interface/web/test_analysis_workflow.py`
- Test: `tests/interface/test_cli_v2.py`

**Interfaces:**
- `RequirementInputService(repository, project_id).ensure_text_requirements(text: str) -> tuple[str, ...]`
- `RequirementInputService(repository, project_id).ensure_document_requirements(document_ids: tuple[str, ...] = ()) -> tuple[str, ...]`

- [x] **Step 1: Write failing tests for text, document, and duplicate input**

Test that repeated text returns the same two requirement IDs and that document-region input preserves the region ID in `EntityMeta.source_ids`.

- [x] **Step 2: Run the focused tests and verify the expected missing service**

Run: `./.venv/bin/pytest -q tests/application/test_requirement_input.py`

Expected: FAIL because `RequirementInputService` is not implemented.

- [x] **Step 3: Implement the service and wire both entry points**

Use `split_requirement_statements` and `extract_requirement_constraints`. Build `USER`/`CANDIDATE` Requirements with `statement`, `source`, `level=system`, `type=functional`, `obligation`, `verification_method`, parsed constraints, and source IDs. Append one `user.requirement_input` Patch only for new statements. Add `V2Services.requirements_input(project_id)`. Allow Web `mode=pipeline` to accept `requirement_text`, and add `--text`/`--input` to CLI `analyze run`; both must call this service before `AnalysisService.run`.

- [x] **Step 4: Run and commit Task 1**

```bash
./.venv/bin/pytest -q tests/application/test_requirement_input.py tests/interface/web/test_analysis_workflow.py tests/interface/test_cli_v2.py
git add src/rflp_lite/application/requirement_input.py src/rflp_lite/bootstrap/v2.py src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/cli_v2.py tests/application/test_requirement_input.py tests/interface/web/test_analysis_workflow.py tests/interface/test_cli_v2.py
git commit -m "feat: add real pipeline requirement input"
```

### Task 2: Implement operational and functional task semantics

**Files:**
- Create: `src/rflp_lite/runtime/lifecycle_rule.py`
- Modify: `src/rflp_lite/runtime/rule_based.py`
- Test: `tests/runtime/test_lifecycle_rule_runtime.py`
- Test: `tests/e2e/test_legacy_pipeline.py`

**Interfaces:**
- `LifecycleTaskRuleRuntime.execute(request: TaskExecutionRequest) -> TaskExecutionResponse`
- `RuleRuntime.execute` delegates the 14 operational/functional task IDs to this runtime; `vertical.*` and unrelated historical IDs retain their current dispatch.

- [x] **Step 1: Write the failing real-input tests**

```python
def test_pipeline_from_text_creates_operational_and_functional_objects(tmp_path):
    graph, summary = run_pipeline_from_text(tmp_path, "系统应支持自主配送并允许人工接管")

    assert {EntityKind.SYSTEM, EntityKind.STAKEHOLDER, EntityKind.CONCERN,
            EntityKind.LIFECYCLE_STAGE, EntityKind.SCENARIO_HYPOTHESIS,
            EntityKind.USE_CASE, EntityKind.OPERATIONAL_SCENARIO,
            EntityKind.ACTIVITY, EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW,
            EntityKind.FUNCTIONAL_SCENARIO} <= active_kinds(graph)
    assert len(summary.completed_tasks) >= 9
```

- [x] **Step 2: Run the tests and confirm the current generic runtime gap**

Run: `./.venv/bin/pytest -q tests/runtime/test_lifecycle_rule_runtime.py tests/e2e/test_legacy_pipeline.py`

Expected: FAIL because current `RuleRuntime` emits generic candidates/no-op responses.

- [x] **Step 3: Implement `TaskGraphBuilder` and operational handlers**

`TaskGraphBuilder` keeps context entities, added entities, operation list, and relation triples. `add` creates `VALIDATED`/`RULE` entities at the context revision; `relate` de-duplicates triples; `update` refuses locked, deprecated, or user-modified entities; `response` returns a Patch only when operations exist. Implement the nine operational tasks with System, Stakeholder, Concern, LifecycleStage, ScenarioHypothesis, UseCase, OperationalScenario, Activity, and Requirement enrichment plus typed `HAS_CONCERN`, `DECOMPOSES`, `DERIVED_FROM`, `PARTICIPATES_IN`, and `OCCURS_IN` relations.

```python
def relate(self, source, predicate, target):
    if source is None or target is None:
        return
    key = (source.id, predicate, target.id)
    if key not in self.relation_keys:
        self.relation_keys.add(key)
        self.operations.append(Relate(*key))
```

- [x] **Step 4: Implement the five functional handlers**

Create/reuse one Function for each active Requirement and add `SATISFIED_BY`; update Function decomposition metadata; create FunctionalFlow and `EXCHANGES_WITH`; create FunctionalScenario with function IDs and steps; update Requirements with `functional_behavior_ids`. Preserve existing payload values and use stable names for idempotency.

- [x] **Step 5: Run and commit Task 2**

```bash
./.venv/bin/pytest -q tests/runtime/test_lifecycle_rule_runtime.py tests/e2e/test_legacy_pipeline.py
git add src/rflp_lite/runtime/lifecycle_rule.py src/rflp_lite/runtime/rule_based.py tests/runtime/test_lifecycle_rule_runtime.py tests/e2e/test_legacy_pipeline.py
git commit -m "feat: add operational and functional task semantics"
```

---

### Task 3: Implement Logical, Physical, and Assurance task semantics

**Files:**
- Modify: `src/rflp_lite/runtime/lifecycle_rule.py`
- Test: `tests/runtime/test_lifecycle_rule_runtime.py`
- Test: `tests/e2e/test_legacy_pipeline.py`

- [x] **Step 1: Write failing tests for all remaining typed objects and trace closure**

```python
def test_pipeline_closes_logical_physical_and_assurance_layers(tmp_path):
    graph, summary = run_pipeline_from_text(tmp_path, "系统功耗不超过 50 W 且续航不少于 10 h")

    assert {EntityKind.LOGICAL_COMPONENT, EntityKind.INTERFACE, EntityKind.STATE,
            EntityKind.PHYSICAL_BLOCK, EntityKind.HAZARD, EntityKind.FAILURE_MODE,
            EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE} <= active_kinds(graph)
    assert len(summary.completed_tasks) == 23
    assert summary.status.value == "completed"
    assert complete_rflp_vv_path_exists(graph)
```

- [x] **Step 2: Implement Logical and Physical handlers**

Create one LogicalComponent per Function and one PhysicalBlock per LogicalComponent. Propagate only explicit canonical constraints/provenance. Update allocation trade-study metadata without changing measurements. Generate `level=technical` Requirements for explicit `max_*`/`min_*` constraints and connect them with `DERIVED_FROM` and `SATISFIED_BY`; otherwise mark the PhysicalBlock `technical_requirement_status=no_explicit_constraints`.

- [x] **Step 3: Implement Interface/State and Assurance handlers**

Create Interface and State with `CONNECTED_TO`/`DECOMPOSES`; create one Hazard and FailureMode per Requirement with `CAUSES` and `MITIGATED_BY`; create independent VerificationCase and ValidationCase for every Requirement with `VERIFIED_BY` and `VALIDATED_BY`.

- [x] **Step 4: Implement Reverse and Global handlers**

Update physical/technical requirements with measured-versus-required feasibility review fields without changing measurements. Update verification cases with `cross_analysis_status=checked`, ensure missing typed V&V edges, and return a real Patch. Repeat execution must not duplicate entities or relations.

- [x] **Step 5: Run and commit Task 3**

```bash
./.venv/bin/pytest -q tests/runtime/test_lifecycle_rule_runtime.py tests/e2e/test_legacy_pipeline.py
git add src/rflp_lite/runtime/lifecycle_rule.py tests/runtime/test_lifecycle_rule_runtime.py tests/e2e/test_legacy_pipeline.py
git commit -m "feat: complete logical physical assurance task semantics"
```

---

### Task 4: Make task completion and lifecycle status truthful

**Files:**
- Modify: `src/rflp_lite/methodology/completion.py`
- Modify: `src/rflp_lite/methodology/workflow.py`
- Modify: `src/rflp_lite/methodology/tasks.py`
- Test: `tests/methodology/test_completion.py`
- Test: `tests/methodology/test_workflow.py`

- [x] **Step 1: Add failing tests for semantic task evidence and degraded closure**

Assert a degraded phase remains `RunStatus.DEGRADED` and that its closure is blocked rather than reported as completed.

- [x] **Step 2: Add lifecycle-specific completion checks**

Key the checks by task ID. Require an active output kind and first-run Patch for entity tasks, actual typed relations for relation tasks, and named payload markers for update tasks. Apply the stricter branch to lifecycle runtime responses while preserving generic FakeRuntime compatibility tests.

- [x] **Step 3: Block Closure after a degraded phase**

After `_run_phase`, if the phase summary is not `RunStatus.COMPLETED`, persist `DEGRADED`, block later phases and Closure, and return a blocked closure payload. A passing Gate cannot hide a degraded task ledger.

- [x] **Step 4: Run and commit Task 4**

```bash
./.venv/bin/pytest -q tests/methodology/test_completion.py tests/methodology/test_workflow.py
git add src/rflp_lite/methodology/completion.py src/rflp_lite/methodology/workflow.py src/rflp_lite/methodology/tasks.py tests/methodology/test_completion.py tests/methodology/test_workflow.py
git commit -m "fix: make 23-task completion status truthful"
```

---

### Task 5: Prove structured LLM, SysML, delivery, and end-to-end acceptance

**Files:**
- Test: `tests/e2e/test_legacy_pipeline.py`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/application/test_sysml_v2.py`
- Test: `tests/interface/web/test_deliverables_api.py`
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/specs/2026-09-13-real-23-task-lifecycle-design.md`
- Modify: `docs/superpowers/plans/2026-09-13-real-23-task-lifecycle.md`

- [x] **Step 1: Add the scripted structured-LLM acceptance test**

Create `LifecycleModel.complete_json(request)` that records each task ID and returns one minimal valid Proposal for that task. Run it through `StructuredModelRuntime`, `TaskExecutor`, proposal compiler, validators, and `WorkflowRunner`; assert exactly `task_catalog()` order, 23 stored Steps, valid Patch writes, and complete trace. The test double must not invoke RuleRuntime.

- [x] **Step 2: Prove SysML round-trip, editability, and deliverables**

Export the final graph with `graph_to_sysml`, import with `sysml_to_graph`, compare IDs/kinds/key payloads/relations, then apply a Function review edit. Assert model, RFLP, traceability, V&V plan, and `model.sysml` deliverables contain the Technical Requirement and physical relation.

- [x] **Step 3: Update product documentation**

Document `mode=pipeline` as the real 23-task path while retaining the five-stage path as the default user-facing fast path. Retain historical Provider stability limitations and do not claim live stability from the scripted model.

- [x] **Step 4: Run the complete verification suite**

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```

- [x] **Step 5: Mark complete, commit, push, and verify remote equality**

```bash
git status --short
git rev-parse HEAD
git rev-parse '@{u}'
```

Expected: empty status output and identical local/upstream commit IDs.
