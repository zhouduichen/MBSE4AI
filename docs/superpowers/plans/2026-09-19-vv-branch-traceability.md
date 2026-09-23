# V&V Branch Traceability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Activity 的五类分支转成可执行的 Verification/Validation 场景，并把分支级 Evidence、失败影响路径和定向重分析贯通到 ModelGraph、Assurance 和交付包。

**Architecture:** 继续复用现有 `VerificationCase` / `ValidationCase` payload，不新增实体类型或关系谓词。规则 Runtime 在 Assurance 阶段从 Activity 生成稳定的 `branch_scenarios`；Methodology Engine 只读计算结构化覆盖率；V&V execution service 通过 CAS 更新 Case 和可选的分支场景，现有 Controller 负责用户确认后的下游重分析。

**Tech Stack:** Python 3.11+, dataclasses, SQLite ModelGraph/CAS, FastAPI Resource API, Jinja2, pytest, Ruff, import-linter。

## Global Constraints

- 本切片只使用现有 ModelGraph、CAS Patch、Methodology Engine 和 Systems Engineering Controller。
- 离线验收不启动服务器、LLM、SSH 或 FreeCAD。
- `branch_type` 允许值为 `normal`、`failure`、`alternative`、`boundary`、`exception`；未知值为 `unknown` 且必须进入 `needs_review`。
- 现有 `covered_branches`、Case 级 `record_result` 和既有 API 调用保持兼容。
- 没有执行 Evidence 时不得显示或计算为通过；计划字段不等同于执行事实。
- 所有写入必须经过现有 CAS 和实体锁定检查，禁止绕过 ModelGraph。

---

### Task 1: Generate stable structured branch scenarios

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py` in `_verification_validation` and `_vertical_vv_plan_payload`
- Test: `tests/application/test_model_generation.py`
- Test: `tests/runtime/test_task_execution.py`

**Interfaces:**
- Consumes: `Activity.payload.branches`, `Activity.payload.branch_types`, `Activity.payload.branch_map`, `requirement.id`, `activity.id`。
- Produces: `_vertical_branch_scenarios(case_type: str, requirement: Entity, activities: Sequence[Entity]) -> list[dict[str, object]]`；`_vertical_vv_plan_payload` adds `branch_scenarios` and `covered_branch_types` while retaining `covered_branches`。

- [ ] **Step 1: Write the failing runtime test**

```python
def test_vertical_assurance_emits_five_structured_branch_scenarios(tmp_path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("branch-model")
    result = services.generation("branch-model").generate(
        "branch-model", requirement_text="系统应支持人工接管"
    )
    graph = services.model("branch-model").graph("branch-model")
    cases = [
        entity for entity in graph.entities
        if entity.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
    ]
    assert result.status == "completed"
    assert len(cases) == 2
    expected = {"normal", "failure", "alternative", "boundary", "exception"}
    for case in cases:
        scenarios = case.payload["branch_scenarios"]
        assert {item["branch_type"] for item in scenarios} == expected
        assert all(
            item["activity_id"] and item["requirement_ids"]
            and item["stimulus"] and item["procedure"]
            and item["expected_result"] and item["pass_criteria"]
            for item in scenarios
        )
        assert all(item["status"] == "planned" for item in scenarios)
```

- [ ] **Step 2: Run the test to verify the gap**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/application/test_model_generation.py::test_vertical_assurance_emits_five_structured_branch_scenarios
```

Expected: FAIL because generated Case payloads do not yet contain `branch_scenarios`.

- [ ] **Step 3: Implement the deterministic branch compiler**

Add these internal helpers beside `_vertical_vv_plan_payload`:

```python
_VERTICAL_BRANCH_TYPES = ("normal", "failure", "alternative", "boundary", "exception")


def _branch_type_and_label(value: object) -> tuple[str, str]:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "unknown", "未命名分支"
    prefix, separator, label = text.partition(":")
    branch_type = prefix.strip().casefold() if separator else ""
    if branch_type not in _VERTICAL_BRANCH_TYPES:
        return "unknown", text
    return branch_type, label.strip() or branch_type


def _vertical_branch_scenarios(case_type: str, requirement, activities):
    scenarios = []
    for activity in activities:
        raw_branches = activity.payload.get("branches", ())
        values = raw_branches if isinstance(raw_branches, (list, tuple)) else ()
        for raw_branch in values:
            branch_type, branch_label = _branch_type_and_label(raw_branch)
            scenario_id = f"{case_type}-scenario-{canonical_hash((requirement.id, activity.id, branch_type, branch_label))[:16]}"
            scenarios.append({
                "id": scenario_id,
                "branch_type": branch_type,
                "branch_label": branch_label,
                "activity_id": activity.id,
                "requirement_ids": [requirement.id],
                "stimulus": f"触发{branch_label}",
                "procedure": f"执行{branch_label}并记录状态转移与输出",
                "expected_result": f"系统完成{branch_label}对应的行为并保留可追溯结果",
                "pass_criteria": f"{branch_label}路径满足需求且结果可复核",
                "status": "planned" if branch_type != "unknown" else "needs_review",
            })
    return scenarios
```

Pass `activities` into `_vertical_vv_plan_payload`, add the returned list under `branch_scenarios`, and derive `covered_branch_types` from its `branch_type` values. Keep `covered_branches` labels unchanged so older structured-runtime fixtures remain valid.

- [ ] **Step 4: Run focused runtime tests**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/application/test_model_generation.py tests/runtime/test_task_execution.py
```

Expected: all tests pass; existing fixtures that only provide `covered_branches` remain accepted.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/runtime/rule_based.py tests/application/test_model_generation.py tests/runtime/test_task_execution.py
git commit -m "feat: generate structured V&V branch scenarios"
```

### Task 2: Measure structured branch coverage in Methodology

**Files:**
- Modify: `src/rflp_lite/methodology/engine.py` in `_analyze_vv` and `_record_vv_case_metrics`
- Test: `tests/methodology/test_engine.py`

**Interfaces:**
- Consumes: ready Verification/Validation Case payloads and Activity payloads。
- Produces: `branch_scenario_total`, `branch_scenario_complete`, `activity_branch_coverage`, `branch_execution_coverage`, and `branch_scenario_incomplete` findings in `MethodologyReport`。

- [ ] **Step 1: Write failing metric tests**

```python
def test_methodology_counts_complete_branch_scenarios_and_execution_progress(graph_with_branch_cases):
    report = MethodologyEngine().analyze(graph_with_branch_cases)
    assert report.metrics["branch_scenario_total"] == 10
    assert report.metrics["branch_scenario_complete"] == 10
    assert report.metrics["activity_branch_coverage"] == 1.0
    assert report.metrics["branch_execution_coverage"] == 0.0


def test_methodology_marks_incomplete_branch_scenario_for_review(graph_with_branch_cases):
    graph = replace_branch_scenario(graph_with_branch_cases, status="needs_review", stimulus="")
    report = MethodologyEngine().analyze(graph)
    assert report.metrics["branch_scenario_complete"] == 9
    assert report.metrics["activity_branch_coverage"] < 1.0
    assert any(item.code == "branch_scenario_incomplete" for item in report.findings)
```

The fixture helper must build one accepted Requirement, one ready Activity with exactly the five typed branch strings, and one VerificationCase plus one ValidationCase whose `branch_scenarios` are the Task 1 payloads.

- [ ] **Step 2: Run the metric tests to verify failure**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/methodology/test_engine.py -k branch_scenario
```

Expected: FAIL because the new metric keys are absent.

- [ ] **Step 3: Add the pure coverage calculator**

Add a pure helper near the existing V&V helpers:

```python
def _branch_scenario_metrics(cases, activities):
    required_types = {"normal", "failure", "alternative", "boundary", "exception"}
    scenarios = [
        dict(item)
        for case in cases
        for item in case.payload.get("branch_scenarios", ())
        if isinstance(item, Mapping)
    ]
    complete = [
        item for item in scenarios
        if str(item.get("branch_type", "")) in required_types
        and all(str(item.get(field, "")).strip() for field in ("activity_id", "stimulus", "procedure", "expected_result", "pass_criteria"))
    ]
    executable = [
        item for item in scenarios
        if str(item.get("status", "")) in {"passed", "failed", "blocked", "inconclusive"}
        or item.get("execution_evidence_ids")
    ]
    return {
        "branch_scenario_total": len(scenarios),
        "branch_scenario_complete": len(complete),
        "activity_branch_coverage": _ratio(len({str(item.get("branch_type")) for item in complete} & required_types), len(required_types)) if activities else 0.0,
        "branch_execution_coverage": _ratio(len(executable), len(scenarios)),
    }, tuple(item for item in scenarios if item not in complete)
```

Call it from `_analyze_vv`, merge its metrics, and append a `MethodologyFinding` with code `branch_scenario_incomplete`, severity `warning`, and stage `assurance` for incomplete scenarios. Preserve the existing text-based `activity_branch_coverage` behavior only as a fallback when no structured scenarios exist.

- [ ] **Step 4: Run all methodology tests**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/methodology
```

Expected: all methodology tests pass, including existing V&V and impact tests.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/methodology/engine.py tests/methodology/test_engine.py
git commit -m "feat: measure structured V&V branch coverage"
```

### Task 3: Persist branch-level Evidence and expose it in Assurance

**Files:**
- Modify: `src/rflp_lite/application/vv_execution.py` in `VvExecutionService.record_result`
- Modify: `src/rflp_lite/interface/web/resource_api.py` in the V&V execute endpoint
- Modify: `src/rflp_lite/application/projections/assurance.py`
- Modify: `src/rflp_lite/interface/web/templates/assurance.html`
- Test: `tests/application/test_vv_execution.py`
- Test: `tests/application/projections/test_assurance_projection.py`
- Test: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: optional `scenario_id` in `record_result(project_id: str, case_id: str, *, outcome: str, claim: str, excerpt: str, locator: str = "", source_type: str = "vv_execution", expected_revision: int | None = None, metadata: Mapping[str, object] | None = None, scenario_id: str | None = None)` and the existing case-level execution request。
- Produces: the selected scenario receives `status`, `execution_evidence_ids`, and `last_execution`; case-level calls remain backward compatible; Assurance rows contain `branch_scenarios` and `branch_summary`。

- [ ] **Step 1: Write the failing branch execution test**

```python
def test_vv_execution_updates_selected_branch_scenario(tmp_path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generated = services.generation("robot").generate("robot", requirement_text="系统应支持人工接管")
    graph = services.model("robot").graph("robot")
    case = next(item for item in graph.entities if item.kind is EntityKind.VERIFICATION_CASE)
    scenario = next(item for item in case.payload["branch_scenarios"] if item["branch_type"] == "failure")
    result = services.vv("robot").record_result(
        "robot", case.id, scenario_id=scenario["id"], outcome="failed",
        claim="失败分支未能安全接管", excerpt="测试记录显示未进入人工接管",
        expected_revision=generated.revision,
    )
    updated = services.model("robot").graph("robot").entity_index[case.id]
    changed = next(item for item in updated.payload["branch_scenarios"] if item["id"] == scenario["id"])
    assert changed["status"] == "failed"
    assert result.evidence_id in changed["execution_evidence_ids"]
```

- [ ] **Step 2: Run the test to verify failure**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/application/test_vv_execution.py::test_vv_execution_updates_selected_branch_scenario
```

Expected: FAIL because `record_result` does not accept `scenario_id`.

- [ ] **Step 3: Add scenario validation and CAS update**

Extend the method signature with `scenario_id: str | None = None`. Before creating the Patch, validate that the ID belongs to `case.payload["branch_scenarios"]`; otherwise raise `NotFoundError`. Include `scenario_id` in the evidence hash and execution record. When present, update only the matching dictionary with:

```python
{
    "status": normalized,
    "execution_evidence_ids": [*old_ids, evidence_id],
    "last_execution": record,
}
```

Add the resulting list under the Case payload update in the same existing Patch. Keep Case `execution_status` and Issue behavior unchanged so legacy calls still work.

- [ ] **Step 4: Add projection and HTTP assertions**

The resource endpoint reads `scenario_id = str(payload.get("scenario_id", "")).strip() or None` and passes it to `record_result`. `build_assurance_view` returns `branch_scenarios` and a `branch_summary` with `total`, `complete`, and `executed`. The template renders a compact branch selector and current status inside each Case row; the existing form submits the selected `scenario_id`.

- [ ] **Step 5: Run focused application/API tests**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/application/test_vv_execution.py tests/application/projections/test_assurance_projection.py tests/interface/web/test_vertical_generation_api.py
```

Expected: all tests pass and selected branch Evidence is visible through service and HTTP paths.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/vv_execution.py src/rflp_lite/interface/web/resource_api.py src/rflp_lite/application/projections/assurance.py src/rflp_lite/interface/web/templates/assurance.html tests/application/test_vv_execution.py tests/application/projections/test_assurance_projection.py tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: persist branch-level V&V evidence"
```

### Task 4: Include branch coverage in deliverables and full vertical acceptance

**Files:**
- Modify: `src/rflp_lite/application/deliverables.py` in `_vv_plan`
- Test: `tests/application/test_deliverables.py`
- Test: `tests/e2e/test_local_product_acceptance.py`

**Interfaces:**
- Consumes: Assurance rows with `branch_scenarios`, `branch_summary`, and Methodology metrics。
- Produces: `vv-plan.json`, `vv-plan.md`, SysML round-trip, and the complete package retain branch plans, coverage, execution status, and the same revision/snapshot hash。

- [ ] **Step 1: Write the failing deliverable assertion**

```python
def test_vv_deliverable_contains_branch_coverage(tmp_path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("deliverable")
    services.generation("deliverable").generate("deliverable", requirement_text="系统应支持人工接管")
    package = services.deliverables("deliverable").build("deliverable")
    vv_plan = package["artifacts"]["vv_plan"]["content"]
    assert vv_plan["metrics"]["branch_scenario_total"] == 10
    assert vv_plan["rows"][0]["branch_scenarios"]
    assert package["revision"] == package["artifacts"]["vv_plan"]["revision"]
```

Add to the existing local acceptance test an export/import assertion that the restored Case payload has the same `branch_scenarios` and status values as the source graph.

- [ ] **Step 2: Run the failing deliverable test**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/application/test_deliverables.py tests/e2e/test_local_product_acceptance.py -k branch
```

Expected: FAIL because `_vv_plan` does not expose branch metrics explicitly.

- [ ] **Step 3: Extend `_vv_plan` without creating new model state**

Copy each row's `branch_scenarios` and `branch_summary`, then compute:

```python
branch_scenarios = [item for row in rows for item in row.get("branch_scenarios", ())]
metrics.update({
    "branch_scenario_total": len(branch_scenarios),
    "branch_scenario_complete": sum(item.get("status") != "needs_review" for item in branch_scenarios),
    "branch_execution_coverage_percent": round(
        100 * sum(item.get("status") in {"passed", "failed", "blocked", "inconclusive"} for item in branch_scenarios) / len(branch_scenarios), 2
    ) if branch_scenarios else 0.0,
})
```

Use the existing generic SysML serializer; no special parser changes are needed because Case payload fields are already JSON-safe. Add a branch summary column to the V&V Markdown table instead of expanding one row per branch.

- [ ] **Step 4: Run package and full offline acceptance tests**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python -m pytest -q tests/application/test_deliverables.py tests/e2e/test_local_product_acceptance.py tests/e2e/test_vertical_model_generation.py
```

Expected: all tests pass and package artifacts remain revision-bound.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/application/deliverables.py tests/application/test_deliverables.py tests/e2e/test_local_product_acceptance.py
git commit -m "feat: deliver V&V branch coverage"
```

### Task 5: Project verification and push

**Files:**
- Verify: `scripts/verify_full.py`
- Verify: `src/rflp_lite/runtime/rule_based.py`, `src/rflp_lite/methodology/engine.py`, `src/rflp_lite/application/vv_execution.py`, `src/rflp_lite/application/projections/assurance.py`, `src/rflp_lite/application/deliverables.py`, and related tests

- [ ] **Step 1: Validate source hygiene and template syntax**

```bash
git diff --check
node <<'NODE'
const fs = require('fs');
const source = fs.readFileSync('src/rflp_lite/interface/web/templates/assurance.html', 'utf8');
const match = source.match(/<script>([\s\S]*)<\/script>/);
if (!match) throw new Error('assurance script block not found');
new Function(match[1].replace('{{ project_id|tojson }}', JSON.stringify('p1')));
console.log('assurance script parses');
NODE
```

Expected: no diff errors and `assurance script parses`.

- [ ] **Step 2: Run the full offline verifier**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview .venv/bin/python scripts/verify_full.py
```

Expected: pytest passes with only the existing skip, architecture metrics retain `module_cycles=0`, `adapter_to_application_edges=0`, `functions_over_150_lines=0`, Ruff passes, and import-linter reports 5 kept contracts.

- [ ] **Step 3: Review and push**

```bash
git status --short
git log --oneline -8
git push origin codex/web-audit-2026-08-18
```

Expected: only intended commits are present, push succeeds, and `git status --short` is empty.

## Coverage review

- Task 1 covers all five branch types, stable IDs, unknown branch handling, and backward compatibility.
- Task 2 covers structured completeness, execution progress, missing Activity fallback, and Methodology findings.
- Task 3 covers scenario-level execution, CAS, Issue impact paths, Controller entry, and Web exposure.
- Task 4 covers V&V package metrics, SysML preservation, and revision binding.
- Task 5 covers templates, full verifier, architecture boundaries, and GitHub push.

## Plan self-review

- No new entity kind or relation predicate is introduced.
- `branch_scenario_total` counts structured records; `branch_scenario_complete` counts only known branch types with all required fields.
- `activity_branch_coverage` is 1.0 only when all five known branch types have complete scenarios; execution coverage is separate.
- `scenario_id` is optional, so existing Case-level API and service calls remain valid.
- Locked entities continue through existing conflict handling; no step writes outside ModelGraph CAS.
- No real model, server, SSH, FreeCAD, or repeated benchmark experiments are included.
