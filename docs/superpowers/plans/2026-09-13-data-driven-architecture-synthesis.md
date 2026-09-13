# Data-Driven Architecture Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checklist syntax for tracking.

**Goal:** Replace fixed fallback Logical/Physical names with graph-driven partitioning, allocation, and requirement-constraint propagation.

**Architecture:** Keep Functional output as the source of responsibilities. Group Functions using explicit partition signals or stable Function IDs, emit one Logical Component per group plus shared Interface/State context, then emit one Physical Block candidate per Logical Component with propagated Requirement metadata. Let Methodology and Controller retain authority over coupling review and feasibility.

**Tech Stack:** Python 3.11+, typed ModelGraph, existing Patch/RelationPredicate, offline `VerticalRuleRuntime`, Methodology Engine, pytest.

## Global Constraints

- One component per explicit partition group; no signal falls back to one component per Function.
- A group with multiple Functions is marked `coupling=high` and remains reviewable.
- Every active Logical Component receives at least one Physical Block candidate.
- Physical constraints and source Requirement IDs are copied only from existing graph data.
- No existing entity is updated or deleted by this fallback synthesis.
- Single-requirement generation remains one complete trace with physical feasibility `needs_measurement`.

---

### Task 1: Add deterministic Function partitioning helpers

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py:380-430`
- Test: `tests/runtime/test_vertical_rule_runtime.py`

**Interfaces:**
- Consumes: Function payload fields `logical_partition`, `partition_key`, `shared_state`, and stable Function IDs.
- Produces: `_partition_functions(functions) -> tuple[tuple[object, ...], ...]` with stable groups and `_partition_label(group) -> str`.

- [x] **Step 1: Write partition regression tests**

```python
def test_partition_functions_uses_explicit_key_and_falls_back_to_function_id():
    first = make_entity(EntityKind.FUNCTION, "规划", {"partition_key": "任务管理"})
    second = make_entity(EntityKind.FUNCTION, "执行", {"partition_key": "任务管理"})
    third = make_entity(EntityKind.FUNCTION, "监控", {})

    groups = _partition_functions((first, second, third))

    assert [[item.meta.name for item in group] for group in groups] == [
        ["规划", "执行"],
        ["监控"],
    ]


def test_partition_functions_groups_shared_state_and_exposes_labels():
    first = make_entity(EntityKind.FUNCTION, "采集", {"shared_state": ["任务状态"]})
    second = make_entity(EntityKind.FUNCTION, "调度", {"shared_state": ["任务状态"]})

    groups = _partition_functions((first, second))

    assert len(groups) == 1
    assert _partition_label(groups[0]) == "共享状态：任务状态"
```

Add imports for `EntityKind`, `make_entity`, `_partition_functions`, and `_partition_label` to the runtime test module.

- [x] **Step 2: Run the partition tests**

Run: `./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py -q`

Expected: PASS after the helper implementation.

- [x] **Step 3: Implement stable partition helpers**

```python
def _partition_functions(functions):
    groups = {}
    for function in functions:
        payload = function.payload
        explicit = str(payload.get("logical_partition") or payload.get("partition_key") or "").strip()
        shared = payload.get("shared_state")
        shared_values = tuple(sorted(str(item).strip() for item in shared if str(item).strip())) if isinstance(shared, (list, tuple)) else ()
        key = ("explicit", explicit) if explicit else ("shared", shared_values) if shared_values else ("function", function.id)
        groups.setdefault(key, []).append(function)
    return tuple(tuple(group) for group in groups.values())


def _partition_label(group):
    first = group[0]
    payload = first.payload
    explicit = str(payload.get("logical_partition") or payload.get("partition_key") or "").strip()
    if explicit:
        return explicit
    shared = payload.get("shared_state")
    if isinstance(shared, (list, tuple)):
        values = tuple(str(item).strip() for item in shared if str(item).strip())
        if values:
            return "共享状态：" + "、".join(values)
    return first.meta.name[:32]
```

- [x] **Step 4: Run the partition tests and verify they pass**

Run: `./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py -q`

Expected: PASS.

- [x] **Step 5: Commit the partition helpers**

```bash
git add src/rflp_lite/runtime/rule_based.py tests/runtime/test_vertical_rule_runtime.py
git commit -m "feat: derive logical partitions from functions"
```

### Task 2: Generate graph-driven Logical and Physical architecture

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py:383-455,500-545`
- Modify: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: `_partition_functions`, Function→Logical and Requirement→Function relations in `TaskExecutionRequest.context_bundle`.
- Produces: one Logical Component per partition group, shared Interface/State relations, and one Physical Block per Logical Component with `source_requirement_ids` and `propagated_constraints`.

- [x] **Step 1: Write multi-architecture regression assertions**

```python
def test_multi_requirement_generation_derives_separate_logical_and_physical_architecture(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot",
        requirement_text="系统应自主配送；系统应支持人工接管；系统应在断网后安全运行",
    )
    graph = services.model("robot").graph("robot")

    logicals = [item for item in graph.entities if item.kind is EntityKind.LOGICAL_COMPONENT]
    physicals = [item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK]
    functions = [item for item in graph.entities if item.kind is EntityKind.FUNCTION]

    assert len(functions) == len(logicals) == len(physicals) == 3
    assert result.traceability.complete_count == 3
    assert all(
        any(
            relation.source_id == function.id
            and relation.predicate is RelationPredicate.ALLOCATED_TO
            and graph.entity_index[relation.target_id].kind is EntityKind.LOGICAL_COMPONENT
            for relation in graph.relations
        )
        for function in functions
    )


def test_physical_candidate_carries_requirement_constraints(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    requirement = services.projects.add_requirement("robot", "系统应在功耗约束内运行")
    requirement_id = requirement["requirement"]["id"]
    graph = services.model("robot").graph("robot")
    services.review("robot").edit_entity(
        "robot", requirement_id,
        payload={"constraints": {"max_power_w": 50}},
        expected_revision=graph.revision,
    )
    services.generation("robot").generate("robot")
    graph = services.model("robot").graph("robot")
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)

    assert physical.payload["source_requirement_ids"]
    assert physical.payload["propagated_constraints"]
```

- [x] **Step 2: Run the architecture tests**

Run: `./.venv/bin/pytest tests/e2e/test_vertical_model_generation.py::test_multi_requirement_generation_derives_separate_logical_and_physical_architecture tests/e2e/test_vertical_model_generation.py::test_physical_candidate_carries_requirement_constraints -q`

Expected: PASS after the graph-driven synthesis implementation.

- [x] **Step 3: Replace fixed Logical synthesis with partition groups**

In `_logical`, collect active context Functions, call `_partition_functions`, create a component for each group, and add `ALLOCATED_TO` for each Function in the group. Set `dependencies`, `shared_state`, `partition_basis`, `architecture_rationale`, `cohesion`, and `coupling` from the group. Create one shared Interface and State model, connect every component to the interface, and keep Function↔Interface exchanges. Preserve the old single-function names when the group contains exactly one Function so single-input snapshots remain readable and stable.

- [x] **Step 4: Replace fixed Physical synthesis and propagate source constraints**

In `_physical`, for every Logical Component, find its allocated Functions, then find Requirement sources through `SATISFIED_BY`. Merge their `constraints` and `limits` mappings into a deterministic `propagated_constraints` mapping, collect Requirement IDs, call `_physical_payload(logical, requirements)`, and create a Physical Block named from the Logical Component. Keep all unknown numeric fields and `needs_measurement` status unchanged.

- [x] **Step 5: Run focused architecture and existing generation tests**

Run: `./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py tests/e2e/test_vertical_model_generation.py tests/application/test_model_generation.py -q`

Expected: PASS; single-input behavior remains complete and multi-input architecture has one L/P pair per partition.

- [x] **Step 6: Commit the architecture synthesis**

```bash
git add src/rflp_lite/runtime/rule_based.py tests/runtime/test_vertical_rule_runtime.py tests/e2e/test_vertical_model_generation.py
git commit -m "feat: synthesize logical and physical architecture from graph"
```

### Task 3: Document and verify architecture reasoning

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/plans/2026-09-13-data-driven-architecture-synthesis.md`

**Interfaces:**
- Consumes: graph-driven Logical/Physical synthesis from Tasks 1–2.
- Produces: documented architecture reasoning and a verified pushed branch.

- [x] **Step 1: Document data-driven F/L/P behavior**

State that Functions are partitioned by explicit responsibility/shared-state signals, each partition receives a Logical Component and Physical candidate, and physical requirements remain measurable constraints rather than invented feasibility.

- [x] **Step 2: Mark this plan complete and scan it**

Change completed checkboxes to `[x]`. Run:

```bash
rg -n 'TODO|TBD|FIXME|Similar to Task|add appropriate' docs/superpowers/plans/2026-09-13-data-driven-architecture-synthesis.md | rg -v 'rg -n'
```

Expected: no output.

- [x] **Step 3: Run complete verification**

Run:

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```

Expected: every command exits 0.

- [x] **Step 4: Commit and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/README.md docs/superpowers/plans/2026-09-13-data-driven-architecture-synthesis.md
git commit -m "docs: record data-driven architecture synthesis"
git push origin codex/web-audit-2026-08-18
```
