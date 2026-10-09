# ModelGraph Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 MBSE 模型页提供按工程层分组的真实 ModelGraph 实体，并让 Functional、Logical、Physical 和 V&V 实体可直接 Review、Edit、Lock 和定向 Re-analyze。

**Architecture:** 新增只读 `build_model_workbench_view()` projection，按实体类型把当前 ModelGraph 分成 System Definition、Functional、Logical、Physical 和 V&V 五组。模型页消费该投影并调用已有 Review API；所有写操作继续通过 ReviewService、Patch、CAS Revision 和审计链，不新增另一套状态机或数据库。

**Tech Stack:** Python 3.11+, dataclasses, existing ModelGraph/SQLite repository, FastAPI/Jinja, browser fetch, pytest, Ruff, import-linter。

## Global Constraints

- ModelGraph remains the only model source of truth.
- Review writes must use the existing entity review endpoints and expected revision.
- Locked entities must remain non-editable.
- No new external dependency, database, frontend build system, or SysML format change.
- Existing `/ui/projects/{project_id}/model`, `/projects/{project_id}/model`, trace JSON, and export behavior remain compatible.
- Empty groups render an explicit empty state and never fabricate placeholder entities.

---

### Task 1: Create the model workbench projection

**Files:**
- Create: `src/rflp_lite/application/projections/model_workbench.py`
- Modify: `src/rflp_lite/application/projections/__init__.py`
- Test: `tests/application/projections/test_model_workbench.py`

**Interfaces:**
- Consumes: `ModelGraph`, `EntityKind`, `EntityStatus`, `entity_card()`, `issues_by_entity()`.
- Produces: `build_model_workbench_view(graph, issues=()) -> Mapping[str, object]` with `groups`, `metrics`, `revision`, and `snapshot_hash`.

- [ ] **Step 1: Write the failing projection test**

```python
def test_model_workbench_groups_real_entities_by_engineering_layer():
    view = build_model_workbench_view(graph)
    assert [group["id"] for group in view["groups"]] == [
        "system", "functional", "logical", "physical", "assurance",
    ]
    assert view["metrics"]["entity_count"] == 5
    assert {item["id"] for item in view["groups"][1]["entities"]} == {function.id}
    assert view["groups"][4]["entities"][0]["kind"] == "validation_case"
```

Use a `ModelGraph` containing one Function, LogicalComponent, PhysicalBlock, VerificationCase, and ValidationCase. Do not assert against a hard-coded generated ID.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `./.venv/bin/pytest -q tests/application/projections/test_model_workbench.py`

Expected: FAIL because the projection module does not exist.

- [ ] **Step 3: Implement the projection**

Define immutable group metadata with these exact groups and kinds:

```python
(
    ("system", "System Definition", (SYSTEM, STAKEHOLDER, CONCERN, LIFECYCLE_STAGE, LIFECYCLE_TRANSITION, SCENARIO_HYPOTHESIS, USE_CASE, OPERATIONAL_SCENARIO, ACTIVITY)),
    ("functional", "Functional", (FUNCTION, FUNCTIONAL_FLOW, FUNCTIONAL_SCENARIO)),
    ("logical", "Logical", (LOGICAL_COMPONENT, INTERFACE, STATE)),
    ("physical", "Physical", (PHYSICAL_BLOCK,)),
    ("assurance", "V&V", (VERIFICATION_CASE, VALIDATION_CASE, HAZARD, FAILURE_MODE)),
)
```

For every graph entity, create an `entity_card`, add `source_count`, `evidence_count`, `relation_count`, and `issue_count`, then place it in exactly one group. Sort groups by the constant order and entities by `(kind, id)`. Return group counts and total entity/relation counts plus the graph header. Do not include entities not in the five groups in the grouped cards; report their count as `ungrouped_entity_count`.

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `./.venv/bin/pytest -q tests/application/projections/test_model_workbench.py`

Expected: PASS.

- [ ] **Step 5: Commit the projection**

```bash
git add src/rflp_lite/application/projections/model_workbench.py src/rflp_lite/application/projections/__init__.py tests/application/projections/test_model_workbench.py
git commit -m "feat: add layered model workbench projection"
```

### Task 2: Render layered entities and review controls in the model page

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/base.html` only if a label/link needs updating
- Test: `tests/interface/web/test_model_workbench.py`

**Interfaces:**
- Consumes: `build_trace_view()` and `build_model_workbench_view()`.
- Produces: a model page with five real-data sections, one entity card per grouped entity, and controls with stable `data-entity-id`/`data-action` attributes.

- [ ] **Step 1: Write the failing page test**

```python
def test_model_page_exposes_layered_entities_and_review_controls(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    page = client.get("/ui/projects/p1/model")
    assert page.status_code == 200
    assert "Functional" in page.text
    assert "Logical" in page.text
    assert "Physical" in page.text
    assert "V&amp;V" in page.text
    assert 'data-action="edit"' in page.text
    assert "Manage energy" in page.text
    assert "Battery pack" in page.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/pytest -q tests/interface/web/test_model_workbench.py`

Expected: FAIL because the model page currently renders only the trace and export panels.

- [ ] **Step 3: Pass the projection into the page**

Import `build_model_workbench_view` in `resource_pages.py`, build it from the same graph and issue snapshot used by the model page, and pass it as `workbench` in the `model.html` context. Keep `trace` unchanged so the existing five-node trace JSON and page tests remain valid.

- [ ] **Step 4: Add the layered entity cards**

Render one section per `workbench.groups` with the group title, count, and empty state. Each card must display the entity kind, name, ID, status, source/evidence/relation counts, and payload JSON. Use the existing HTML classes (`panel`, `module-grid`, `card`, `status-badge`, `workbench-actions`) so no frontend dependency is introduced.

- [ ] **Step 5: Add review/edit/re-analysis controls**

For each non-locked entity render the applicable existing actions: candidate/validated → Accept and Reject; accepted → Lock; locked → Unlock; all unlocked entities → Edit; all entities → Re-analyze. Include a compact edit form with name and full payload JSON. The browser code must:

```javascript
const payload = JSON.parse(form.querySelector("textarea").value);
await fetch(`/projects/${projectId}/entities/${entityId}/edit`, {
  method: "POST",
  headers: {"content-type": "application/json"},
  body: JSON.stringify({expected_revision: revision, name, payload}),
});
```

Send the action endpoints already exposed by `resource_api.py`, show parse/API errors in a page callout, and reload after success. Never update the card optimistically.

- [ ] **Step 6: Run the page test and compatibility tests**

Run: `./.venv/bin/pytest -q tests/interface/web/test_model_workbench.py tests/interface/web/test_model_trace.py tests/interface/web/test_resource_api.py`

Expected: PASS, with the existing trace and export behavior unchanged.

- [ ] **Step 7: Commit the workbench UI**

```bash
git add src/rflp_lite/interface/web/resource_pages.py src/rflp_lite/interface/web/templates/model.html tests/interface/web/test_model_workbench.py
git commit -m "feat: make model layers reviewable in web workbench"
```

### Task 3: Prove generic entity editing preserves identity and revision history

**Files:**
- Modify: `tests/interface/web/test_model_workbench.py`
- Test existing: `src/rflp_lite/application/review_service.py`, `src/rflp_lite/interface/web/resource_api.py`

**Interfaces:**
- Consumes: existing `POST /projects/{project_id}/entities/{entity_id}/edit`, accept, lock, and patch endpoints.
- Produces: acceptance evidence that generated architecture entities are editable without bypassing CAS or changing IDs.

- [ ] **Step 1: Add the API behavior test**

```python
def test_function_edit_keeps_id_marks_user_change_and_lock_protects_it(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    model = client.get("/projects/p1/model").json()
    function = next(item for item in model["entities"] if item["kind"] == "function")
    edited = client.post(
        f"/projects/p1/entities/{function['id']}/edit",
        json={"expected_revision": model["revision"], "name": "Manage energy revised", "payload": function["payload"]},
    )
    assert edited.status_code == 200
    current = client.get("/projects/p1/model").json()
    changed = next(item for item in current["entities"] if item["id"] == function["id"])
    assert changed["producer"] == "user"
    assert changed["payload"]["user_modified"] is True
    assert current["revision"] == model["revision"] + 1
```

Then accept and lock the same entity, attempt another edit using the current revision, and assert HTTP 409. Use the existing endpoint behavior; do not add a second write path.

- [ ] **Step 2: Run the behavior test**

Run: `./.venv/bin/pytest -q tests/interface/web/test_model_workbench.py`

Expected: PASS.

- [ ] **Step 3: Run the full product verification**

```bash
./.venv/bin/python scripts/verify_full.py
```

Expected: all tests pass, architecture metrics remain within budget, Ruff passes, and import-linter reports 5 kept / 0 broken.

- [ ] **Step 4: Commit and push the implementation**

```bash
git add tests/interface/web/test_model_workbench.py
git commit -m "test: prove layered model review preserves identity"
git push origin codex/web-audit-2026-08-18
```

## Self-Review

- The projection is read-only and contains no repository or ReviewService dependency.
- UI writes use only existing review endpoints and expected revisions.
- Trace JSON and SysML exports are not changed.
- Empty groups and ungrouped entity counts are explicit; no placeholder card is created.
- The tests cover both rendering and a real Function edit/lock lifecycle.
