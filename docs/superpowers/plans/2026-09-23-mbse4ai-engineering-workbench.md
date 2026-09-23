# MBSE4AI 工程工作台重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Web 页面重组为以输入、R/F/L/P、V&V、问题闭环和 Closure 为主线的统一 MBSE 工程工作台，同时保持既有领域能力与 API 兼容。

**Architecture:** 在现有 Web projection 层增加一个只读生命周期投影，统一为项目总览、工程流程和三个聚合工作台提供阶段状态、阻塞原因、追溯摘要和下一步动作。通过模板和导航隐藏技术页面平铺，但保留原路由作为深度 View；不修改 ModelGraph、CAS、Gate、Repair 或业务写入服务。

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx/原生 JavaScript, 单 CSS, pytest, Ruff。

## Global Constraints

- ModelGraph remains the model source of truth.
- All write operations continue through existing Application Services and APIs.
- Existing routes, API payloads, CAS Revision, Gate/Repair, Controller, V&V, Concept Design, CAD, and Deliverables behavior remain compatible.
- No frontend build step or new runtime dependency.
- UI copy remains Chinese; internal identifiers stay out of primary user-facing labels.

---

### Task 1: Lifecycle projection

**Files:**
- Create: `src/rflp_lite/interface/web/workflow_projection.py`
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Test: `tests/interface/web/test_workflow_projection.py`

**Interfaces:**
- Produces `build_workflow_projection(graph, project_id, has_input, analysis, issues, evidence_count) -> dict[str, object]`.
- Produces seven lifecycle stages with `id`, `label`, `status`, `status_label`, `summary`, `blockers`, `next_action`, `href`, `counts`, and `gate`.

- [ ] **Step 1: Add failing projection tests**

```python
def test_empty_project_starts_at_input_and_explains_blockers():
    view = build_workflow_projection(
        ModelGraph("p1"), "p1", False, None, (), 0,
    )
    assert view["stages"][0]["status"] == "not_started"
    assert view["stages"][0]["next_action"]["label"] == "补充工程输入"
    assert view["stages"][1]["status"] == "blocked"
    assert "工程输入" in view["stages"][1]["blockers"][0]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `.venv/bin/pytest tests/interface/web/test_workflow_projection.py -q`

Expected: FAIL because the projection module and function do not exist.

- [ ] **Step 3: Implement the read-only projection**

Implement explicit status labels and deterministic stage mapping. Use active entity counts and existing `analysis["gate_results"]`, `analysis["latest_run"]`, and `analysis["closure"]`; only use existing gate/closure functions when `analysis` lacks a result. Classify missing prerequisites as `blocked`, satisfied prerequisites without a result as `ready`, active runs as `running`, failed quality as `needs_review` when the latest run is degraded/failed, passed gates as `passed`, and completed Closure as `closed`.

- [ ] **Step 4: Run projection tests**

Run: `.venv/bin/pytest tests/interface/web/test_workflow_projection.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the isolated projection**

```bash
git add src/rflp_lite/interface/web/workflow_projection.py src/rflp_lite/interface/web/resource_pages.py tests/interface/web/test_workflow_projection.py
git commit -m "feat: add engineering lifecycle projection"
```

### Task 2: Unified shell and project overview

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `src/rflp_lite/interface/web/templates/projects.html`
- Create: `src/rflp_lite/interface/web/templates/project-overview.html`
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Test: `tests/interface/web/test_app.py`

**Interfaces:**
- Adds `GET /ui/projects/{project_id}` as a read-only project overview.
- Top-level `active` values become `overview`, `engineering-flow`, `model-workbench`, `verification`, `history`, and `settings`.

- [ ] **Step 1: Add failing navigation and overview assertions**

```python
def test_project_shell_has_six_engineering_workbench_entries(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    client.post("/projects", json={"id": "p1"})
    page = client.get("/ui/projects/p1")
    assert page.status_code == 200
    for label in ("项目总览", "工程流程", "模型工作台", "验证与问题", "历史与基线", "设置"):
        assert label in page.text
    assert "输入 → R → F → L → P → V&amp;V → Closure" in page.text
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `.venv/bin/pytest tests/interface/web/test_app.py::test_project_shell_has_six_engineering_workbench_entries -q`

Expected: FAIL because the project overview route/template and new shell do not exist.

- [ ] **Step 3: Add the project overview route and replace the flat sidebar**

The route calls `build_analysis_view()` and `build_workflow_projection()` and renders the project, lifecycle, traceability metrics, unresolved issues, and current action. The shell renders only the six requested primary entries when a project is selected; the project list remains the global entry page and links each card to the project overview.

- [ ] **Step 4: Run app page tests**

Run: `.venv/bin/pytest tests/interface/web/test_app.py -q`

Expected: PASS after updating only assertions that intentionally refer to old primary navigation labels.

- [ ] **Step 5: Commit the shell and overview**

```bash
git add src/rflp_lite/interface/web/resource_pages.py src/rflp_lite/interface/web/templates/base.html src/rflp_lite/interface/web/templates/projects.html src/rflp_lite/interface/web/templates/project-overview.html tests/interface/web/test_app.py
git commit -m "feat: add engineering workbench shell and overview"
```

### Task 3: Engineering flow lifecycle surface

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Modify: `src/rflp_lite/interface/web/templates/engineering-flow.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_app.py`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Existing `GET /ui/projects/{project_id}/engineering-flow` continues to render the existing input form and product-flow JavaScript.
- The page additionally renders lifecycle status, blockers, next actions, traceability, and Closure state before any run.

- [ ] **Step 1: Add failing assertions for pre-run lifecycle state**

```python
def test_engineering_flow_explains_empty_project_state(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    client.post("/projects", json={"id": "p1"})
    page = client.get("/ui/projects/p1/engineering-flow")
    assert "工程输入" in page.text
    assert "未开始" in page.text
    assert "为什么不能进入下一阶段" in page.text
    assert "补充工程输入" in page.text
```

- [ ] **Step 2: Run focused test and verify it fails**

Run: `.venv/bin/pytest tests/interface/web/test_app.py::test_engineering_flow_explains_empty_project_state -q`

Expected: FAIL because the current page only shows an input form and hidden result area.

- [ ] **Step 3: Render the lifecycle rail and action panel**

Add a stable `workflow-lifecycle` rail and one `workflow-focus` panel to the template. Keep the existing form IDs and JavaScript payload unchanged. Add a compact workflow status legend and retain the existing concept/CAD/behavior result links.

- [ ] **Step 4: Add styles and verify generated-run compatibility**

Add responsive styles for seven-stage rails, blocker cards, focus action cards, and status variants. Run the pre-existing generated and pipeline analysis page tests to ensure old analysis semantics remain visible.

- [ ] **Step 5: Commit engineering flow**

```bash
git add src/rflp_lite/interface/web/templates/engineering-flow.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_app.py tests/interface/web/test_analysis_workflow.py
git commit -m "feat: make engineering flow lifecycle-first"
```

### Task 4: Aggregate model, verification, and history workbenches

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/assurance.html`
- Modify: `src/rflp_lite/interface/web/templates/history.html`
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Test: `tests/interface/web/test_model_workbench.py`
- Test: `tests/interface/web/test_assurance_view.py`
- Test: `tests/interface/web/test_history_diff.py`

**Interfaces:**
- Existing deep URLs remain unchanged.
- Aggregate cards link to `/requirements`, `/rflp`, `/behavior`, `/concept-design`, `/cad-design`, `/traceability`, `/evidence`, `/assurance`, `/history`, and the existing deliverables API.

- [ ] **Step 1: Add failing assertions for contextual View groups**

```python
def test_model_workbench_groups_existing_views_by_engineering_context(tmp_path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    client.post("/projects", json={"id": "p1"})
    page = client.get("/ui/projects/p1/model")
    assert "模型工作台" in page.text
    assert "需求与追溯" in page.text
    assert "/ui/projects/p1/requirements" in page.text
    assert "/ui/projects/p1/cad-design" in page.text
```

- [ ] **Step 2: Run the focused tests and verify the new assertions fail**

Run: `.venv/bin/pytest tests/interface/web/test_model_workbench.py tests/interface/web/test_assurance_view.py tests/interface/web/test_history_diff.py -q`

Expected: existing deep page behavior passes or the new contextual assertions fail; no domain/API test is expected to fail.

- [ ] **Step 3: Add contextual View groups without deleting detail surfaces**

Keep current entity tables, assurance records, immutable history and revision diff controls. Add a top summary and grouped links so each page answers which engineering purpose the underlying View serves.

- [ ] **Step 4: Run the focused tests**

Run: `.venv/bin/pytest tests/interface/web/test_model_workbench.py tests/interface/web/test_assurance_view.py tests/interface/web/test_history_diff.py -q`

Expected: PASS.

- [ ] **Step 5: Commit aggregate workbenches**

```bash
git add src/rflp_lite/interface/web/resource_pages.py src/rflp_lite/interface/web/templates/model.html src/rflp_lite/interface/web/templates/assurance.html src/rflp_lite/interface/web/templates/history.html tests/interface/web/test_model_workbench.py tests/interface/web/test_assurance_view.py tests/interface/web/test_history_diff.py
git commit -m "feat: group model assurance and history views"
```

### Task 5: Full regression and UI acceptance

**Files:**
- Modify: `src/rflp_lite/interface/web/static/app.css` only for verified visual defects
- Modify: targeted templates/tests only for verified compatibility defects
- Test: `tests/interface/web/` and relevant E2E suites

**Interfaces:**
- No new API contract.

- [ ] **Step 1: Run the complete Web test package**

Run: `.venv/bin/pytest tests/interface/web -q`

Expected: PASS.

- [ ] **Step 2: Run the relevant E2E and application regression tests**

Run: `.venv/bin/pytest tests/e2e tests/application/test_product_flow.py tests/application/test_closure_service.py -q`

Expected: PASS; ModelGraph, Revision, Gate, Repair, Controller, V&V, Concept Design, CAD, and Deliverables behavior remains unchanged.

- [ ] **Step 3: Run static checks**

Run: `.venv/bin/ruff check src tests/interface/web` and `.venv/bin/python -m compileall -q src`

Expected: both commands exit 0.

- [ ] **Step 4: Render the key pages at desktop and narrow widths**

Open `/ui/projects`, `/ui/projects/p1`, `/ui/projects/p1/engineering-flow`, `/ui/projects/p1/model`, `/ui/projects/p1/assurance`, and `/ui/projects/p1/history`; verify no horizontal overflow in the shell, the lifecycle rail remains readable, empty/blocked states are explicit, and all contextual links resolve.

- [ ] **Step 5: Commit final compatibility fixes**

```bash
git add src/rflp_lite/interface/web tests/interface/web
git commit -m "test: verify engineering workbench regression surface"
```
