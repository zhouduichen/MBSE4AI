# MBSE Review Page Reopen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MBSE 草稿重新生成和逐项审核完整集成到 RFLP 图页面。

**Architecture:** 复用现有 `POST /w/{workspace_name}/requirements/mbse` 路由，不新增后端接口或数据表。模板根据元素状态渲染可操作按钮或明确的已处理状态文案，页面测试通过 TestClient 验证端到端行为。

**Tech Stack:** FastAPI、Jinja2、pytest、现有 SQLite 工作台存储。

## Global Constraints

- 不新增数据库表或修改 MBSE 数据结构。
- 不改变确认规则、导出格式和 RFLP 正式模型生成规则。
- 不引入前端框架或额外运行时依赖。

---

### Task 1: 集成 MBSE 页面入口和状态文案

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/requirements-graph.html` MBSE review section

**Interfaces:**
- Consumes: existing `POST /w/{{ workspace.name }}/requirements/mbse` route and `state.mbse` model.
- Produces: page-level “重新生成 MBSE 草稿” form; status-aware review controls.

- [x] **Step 1: Add a regenerate form when an MBSE model exists**

Render a `POST` form to `/w/{{ workspace.name }}/requirements/mbse` in the MBSE panel, with button text `重新生成 MBSE 草稿` and a browser confirmation prompt explaining that the current review version will be replaced.

- [x] **Step 2: Make review button labels state-aware**

Use `item.status` in the existing loop:

```jinja2
{% if item.status == 'accepted' %}
<button class="button compact" type="submit" disabled>已接受</button>
{% else %}
<button class="button compact" type="submit">接受</button>
{% endif %}
```

Apply the equivalent `已驳回`/`驳回` rendering for rejected items and preserve the existing form actions.

- [x] **Step 3: Run the template-focused page tests**

Run: `.venv/bin/pytest -q tests/interface/web/test_pages.py -k 'mbse or formal_pages'`

Expected: existing tests pass; any new assertion from Task 2 fails until added.

### Task 2: Add regression coverage for the integrated workflow

**Files:**
- Modify: `tests/interface/web/test_pages.py` near the existing requirements graph tests

**Interfaces:**
- Consumes: TestClient routes for workbench generation, MBSE generation, review, and confirmation.
- Produces: regression test proving the UI exposes regeneration and accurate state labels.

- [x] **Step 1: Create a reviewed workbench fixture through existing HTTP routes**

Use `client.post("/workspaces", data={"name": "demo"})`, submit `管理员必须恢复历史版本。`, accept the generated traceable claim, and generate the formal RFLP model before opening `/w/demo/requirements/graph`.

- [x] **Step 2: Assert the initial MBSE review page exposes the integrated controls**

Post to `/w/demo/requirements/mbse`, fetch the graph page, and assert `重新生成 MBSE 草稿` and `接受` are present while `已接受` is absent.

- [x] **Step 3: Assert the confirmed state has explicit labels**

Accept one element and confirm the MBSE model through the existing routes, fetch the graph page, and assert `已确认` and `已接受` are present. Assert the enabled `接受` control is not rendered for that accepted element.

- [x] **Step 4: Run focused and full validation**

Run:

```bash
.venv/bin/pytest -q tests/interface/web/test_pages.py tests/application/test_mbse_modeling.py
.venv/bin/lint-imports
.venv/bin/pytest -q
git diff --check
```

Expected: all tests pass, import contracts remain intact, and no whitespace errors are reported.

- [ ] **Step 5: Commit the implementation**

```bash
git add src/rflp_lite/interface/web/templates/requirements-graph.html tests/interface/web/test_pages.py docs/superpowers/plans/2026-08-10-mbse-review-page-reopen-plan.md
git commit -m "fix: integrate MBSE review controls in graph page"
```
