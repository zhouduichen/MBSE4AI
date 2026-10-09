# Executable V&V Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution in this session, task-by-task with the checkpoints below.

**Goal:** Make generated VerificationCase and ValidationCase entities carry a complete executable V&V plan and expose it consistently through analysis, UI, and deliverables.

**Architecture:** Add one small shared V&V contract module containing the canonical required plan fields and missing-field helper. Reuse it from the LLM-facing payload schema, semantic validator, Methodology Engine, and deliverable projection. Update both deterministic producers and the user-facing assurance views, while preserving the existing ModelGraph, review, CAS, and execution-evidence boundaries.

**Tech Stack:** Python 3.12, dataclasses/typed ModelGraph, JSON Schema contracts, pytest, Jinja templates, Markdown/JSON deliverables.

## Global Constraints

- Do not start, probe, or call Ollama or any local model endpoint.
- Keep `VerificationCase` and `ValidationCase` separate and keep `ModelGraph` as the only semantic source of truth.
- `evidence_ids` means source/design evidence; `execution_evidence_ids` means actual V&V execution evidence.
- A complete plan must never be reported as an executed or passed test.
- Preserve compatibility for old imported/manual cases by reporting missing fields instead of silently fabricating them.

---

### Task 1: Establish the shared executable-plan contract

**Files:**
- Create: `src/rflp_lite/methodology/vv_contract.py`
- Modify: `src/rflp_lite/methodology/tasks.py:287-315`
- Modify: `src/rflp_lite/methodology/validators/semantic.py:31-46`
- Modify: `src/rflp_lite/methodology/engine.py:31-41,1135-1140`
- Test: `tests/methodology/test_vv_contract.py`
- Test: `tests/methodology/validators/test_semantic_validator.py`

**Interfaces:**
- Produce `VV_PLAN_FIELDS: tuple[str, ...]` with exactly `method`, `verification_objective`, `precondition`, `test_condition`, `input`, `stimulus`, `procedure`, `expected_result`, `pass_criteria`.
- Produce `missing_vv_plan_fields(payload: Mapping[str, object]) -> tuple[str, ...]`, treating blank strings, `None`, and absent values as missing.
- The schema builder uses every field as `{"type": "string", "minLength": 1}` and adds `required=list(VV_PLAN_FIELDS)`.
- Semantic validation raises `MethodologyValidationError("semantic_invalid", ...)` when a non-placeholder V&V case has any missing field.

- [ ] **Step 1: Write the failing contract and semantic tests**

```python
def test_missing_vv_plan_fields_is_ordered_and_explicit():
    assert missing_vv_plan_fields({"method": "test", "pass_criteria": "通过"}) == (
        "verification_objective", "precondition", "test_condition", "input",
        "stimulus", "procedure", "expected_result",
    )


def test_vv_payload_schema_requires_executable_fields():
    task = next(item for item in task_catalog() if item.id == "verification_validation")
    schemas = output_contract(task)["x-payload-schemas"]
    assert schemas[EntityKind.VERIFICATION_CASE.value]["required"] == list(VV_PLAN_FIELDS)


def test_semantic_validator_rejects_missing_test_condition():
    entity = make_entity(EntityKind.VERIFICATION_CASE, "验证配送", {
        "method": "test", "verification_objective": "证明配送完成",
        "precondition": "设备上电", "input": "配送任务", "stimulus": "提交任务",
        "procedure": "执行任务", "expected_result": "任务完成",
        "pass_criteria": "结果满足需求",
    })
    task = next(item for item in task_catalog() if item.id == "verification_validation")
    patch = Patch.create("p1", task.id, (AddEntity(entity),), "semantic", 0)
    response = TaskExecutionResponse(StepStatus.COMPLETED, patch)
    context = ValidationContext(
        "p1", task, ModelGraph("p1"), ContextBundle("p1", task.id, 0, ()), response,
    )
    with pytest.raises(MethodologyValidationError, match="test_condition"):
        validate(context)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./.venv/bin/pytest -q tests/methodology/test_vv_contract.py tests/methodology/validators/test_semantic_validator.py`

Expected: FAIL because the shared contract module and the new schema/semantic requirements do not exist yet.

- [ ] **Step 3: Implement the shared helper and wire the contract**

```python
# src/rflp_lite/methodology/vv_contract.py
from collections.abc import Mapping

VV_PLAN_FIELDS = (
    "method", "verification_objective", "precondition", "test_condition",
    "input", "stimulus", "procedure", "expected_result", "pass_criteria",
)


def missing_vv_plan_fields(payload: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        field for field in VV_PLAN_FIELDS
        if not str(payload.get(field, "") or "").strip()
    )
```

Import the tuple/helper in all four consumers. In `_vv_payload_schema`, add the nine properties, return the existing bounded object schema with `required=list(VV_PLAN_FIELDS)`, and retain the existing optional scope/evidence properties. Use the helper in the semantic validator and in `_complete_vv_case`/`_vv_findings` instead of maintaining a second field list.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `./.venv/bin/pytest -q tests/methodology/test_vv_contract.py tests/methodology/validators/test_semantic_validator.py tests/methodology/test_prompt_contracts.py`

Expected: PASS, with the V&V contract schema exposing all nine required fields and incomplete cases rejected semantically.

- [ ] **Step 5: Commit the contract change**

```bash
git add src/rflp_lite/methodology/vv_contract.py src/rflp_lite/methodology/tasks.py src/rflp_lite/methodology/validators/semantic.py src/rflp_lite/methodology/engine.py tests/methodology/test_vv_contract.py tests/methodology/validators/test_semantic_validator.py
git commit -m "feat: enforce executable V&V plan fields"
```

### Task 2: Make all generation paths produce executable plans

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py:930-980,760-900`
- Modify: `src/rflp_lite/runtime/lifecycle_rule.py:814-843`
- Modify: `src/rflp_lite/resources/prompts/vertical/verification_validation.v1.md:1-9`
- Modify: `tests/application/test_model_generation.py` V&V fixtures
- Modify: `tests/methodology/test_engine.py` complete V&V fixture
- Add assertions: `tests/e2e/test_campus_delivery_robot.py`

**Interfaces:**
- `_vertical_vv_plan_payload(...)` returns all nine `VV_PLAN_FIELDS`, plus existing RFLP scope, branch, source evidence, and execution evidence fields.
- `_case_payload(...)` in the lifecycle runtime returns the same nine fields.
- Existing script-model fixtures used as remote structured-runtime stand-ins must include the same contract so the live integration path is tested without a model call.

- [ ] **Step 1: Add failing assertions for generated condition and stimulus**

```python
def test_vertical_generation_emits_executable_vv_plan(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园配送机器人")
    result = services.generation("robot").generate("robot", requirement_text="系统应完成配送")
    assert result.status == "completed"
    graph = services.model("robot").graph("robot")
    cases = [item for item in graph.entities if item.kind in {
        EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE,
    }]
    assert cases
    assert all(not missing_vv_plan_fields(item.payload) for item in cases)
    assert all(item.payload["test_condition"] for item in cases)
    assert all(item.payload["stimulus"] for item in cases)
```

- [ ] **Step 2: Run the focused generation tests and verify they fail**

Run: `./.venv/bin/pytest -q tests/e2e/test_campus_delivery_robot.py tests/application/test_model_generation.py -k 'generation or vertical'`

Expected: FAIL because existing deterministic and scripted V&V payloads do not include `test_condition`, `stimulus`, and `verification_objective`.

- [ ] **Step 3: Update deterministic producers and test fixtures**

For verification use values such as `"标准运行环境、额定负载和需求边界条件"` and `"提交需求并施加正常、异常及人工接管事件"`; for validation use `"典型用户、真实运行场景和代表性任务条件"` and `"由运营人员执行任务并触发必要的用户操作"`. Keep `evidence_ids` and `execution_evidence_ids` separate, and set `evidence_required` from whether execution evidence exists. Update all complete scripted payloads with explicit values; leave intentionally incomplete fixtures incomplete so the Methodology tests still prove the finding.

- [ ] **Step 4: Run the focused generation tests and verify they pass**

Run: `./.venv/bin/pytest -q tests/e2e/test_campus_delivery_robot.py tests/application/test_model_generation.py tests/methodology/test_engine.py`

Expected: PASS, including scripted structured-runtime generation and offline rule generation without any local model invocation.

- [ ] **Step 5: Commit the producer change**

```bash
git add src/rflp_lite/runtime/rule_based.py src/rflp_lite/runtime/lifecycle_rule.py tests/application/test_model_generation.py tests/methodology/test_engine.py tests/e2e/test_campus_delivery_robot.py
git commit -m "feat: generate executable verification and validation plans"
```

### Task 3: Align analysis, projection, UI, and deliverables

**Files:**
- Modify: `src/rflp_lite/application/projections/assurance.py:88-105`
- Modify: `src/rflp_lite/application/deliverables.py:192-220,286-310`
- Modify: `src/rflp_lite/interface/web/templates/assurance.html:24-34`
- Modify: `src/rflp_lite/methodology/coverage_matrix.py:103-125`
- Test: `tests/application/test_deliverables.py`
- Test: `tests/application/projections/test_assurance_projection.py`
- Test: `tests/interface/web/test_assurance_view.py`

**Interfaces:**
- Assurance rows include `verification_objective`, `precondition`, `test_condition`, `input`, `stimulus`, `procedure`, and `expected_result`.
- Plan completeness and `missing` use `missing_vv_plan_fields`.
- `execution_evidence_ids` in the projection comes only from `case.payload["execution_evidence_ids"]`; source `evidence_ids` never counts as execution evidence.
- `vv-plan.md` includes Condition and Stimulus columns while retaining stable JSON row keys.

- [ ] **Step 1: Write failing projection and artifact tests**

```python
def test_source_evidence_is_not_exposed_as_execution_evidence(tmp_path: Path):
    services = _services_with_complete_graph(tmp_path)
    graph = services.model("p1").graph("p1")
    case = next(item for item in graph.entities if item.kind is EntityKind.VERIFICATION_CASE)
    revised = case.__class__(case.meta, {
        **case.payload, "evidence_ids": ["source-1"], "execution_evidence_ids": [],
    })
    # Build the same graph with the revised case, then project assurance.
    view = build_assurance_view(ModelGraph("p1", tuple(
        revised if item.id == case.id else item for item in graph.entities
    ), graph.relations, graph.revision))
    row = next(item for item in view["verification_validation"] if item["case_id"] == case.id)
    assert row["execution_evidence_ids"] == []
    assert row["test_condition"]
    assert row["stimulus"]
```

- [ ] **Step 2: Run the focused projection tests and verify they fail**

Run: `./.venv/bin/pytest -q tests/application/test_deliverables.py tests/application/projections/test_assurance_projection.py tests/interface/web/test_assurance_view.py`

Expected: FAIL because the projection currently copies `evidence_ids` as execution evidence and does not expose the new plan fields.

- [ ] **Step 3: Implement the aligned projections and views**

Use the shared helper to calculate missing fields. Add the plan fields to each assurance row and display a compact “计划详情” disclosure in the V&V table with condition, stimulus, procedure, expected result, and objective. Add Condition and Stimulus to the Markdown table. Update the coverage metric to count a verification case complete only when `missing_vv_plan_fields` is empty; keep evidence coverage independent.

- [ ] **Step 4: Run the focused projection tests and verify they pass**

Run: `./.venv/bin/pytest -q tests/application/test_deliverables.py tests/application/projections/test_assurance_projection.py tests/interface/web/test_assurance_view.py tests/methodology/test_coverage_matrix.py`

Expected: PASS, with source evidence and execution evidence separated and the exported/UI plan showing executable details.

- [ ] **Step 5: Commit the projection change**

```bash
git add src/rflp_lite/application/projections/assurance.py src/rflp_lite/application/deliverables.py src/rflp_lite/interface/web/templates/assurance.html src/rflp_lite/methodology/coverage_matrix.py tests/application/test_deliverables.py tests/application/projections/test_assurance_projection.py tests/interface/web/test_assurance_view.py tests/methodology/test_coverage_matrix.py
git commit -m "feat: expose executable V&V plans"
```

### Task 4: Run the complete offline acceptance gates and update status documentation

**Files:**
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: all existing tests and static gates

**Interfaces:**
- Documentation states that the V&V stage contains the nine-field executable plan and that execution evidence remains a separate lifecycle event.
- No documentation claims live local-model acceptance.

- [ ] **Step 1: Run all offline verification gates**

Run:

```bash
./.venv/bin/pytest -q
./.venv/bin/python -m compileall -q src tests
./.venv/bin/ruff check src tests
./.venv/bin/python -m import_linter
git diff --check
```

Expected: all commands exit 0. Do not set `RFLP_RUN_LIVE_LLM=1` and do not invoke any local endpoint.

- [ ] **Step 2: Add the verified capability statement**

Document the executable V&V fields, the source/execution evidence distinction, and the offline acceptance boundary in the three status/architecture documents. Keep historical local-Ollama records explicitly historical and do not rerun them.

- [ ] **Step 3: Re-run the complete gates after documentation changes**

Run: `./.venv/bin/pytest -q && ./.venv/bin/python -m compileall -q src tests && ./.venv/bin/ruff check src tests && git diff --check`

Expected: PASS with a clean diff check.

- [ ] **Step 4: Commit the verified documentation**

```bash
git add docs/CAPABILITY_MATRIX.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md
git commit -m "docs: record executable V&V coverage"
```

- [ ] **Step 5: Push and verify GitHub state**

```bash
git push origin codex/web-audit-2026-08-18
git status --short
git log -4 --oneline
```

Expected: push succeeds, the worktree is clean, and the remote branch contains the design, contract, producer, projection, and documentation commits.
