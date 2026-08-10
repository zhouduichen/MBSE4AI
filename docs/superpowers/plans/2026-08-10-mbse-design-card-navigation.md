# MBSE 设计图模块卡片入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MBSE 设计图页面的四个文本入口改成有图标、说明、状态和整块点击区域的模块卡片。

**Architecture:** 保留现有四个 URL 和 `diagram_view` 状态，只替换 `mbse-diagrams.html` 的导航标记，并在 `app.css` 中新增局部卡片样式。测试通过页面响应断言卡片数量、文案、链接和 active 状态，后端及 SVG 代码不变。

**Tech Stack:** Jinja2 模板、现有 `app.css`、FastAPI `TestClient`、pytest。

## Global Constraints

- 只修改设计图页面模板、局部 CSS 和页面测试。
- 不新增图片、JavaScript、第三方依赖或全局状态。
- 保留 `/requirements/mbse`、`/requirements/mbse?view=...` 和 `/requirements/mbse/sequence` 原有链接。
- 桌面端四列，宽度不足时两列，再不足时一列。
- 卡片必须支持 hover、focus-visible 和 active 状态，并使用现有绿色强调色。

---

### Task 1: Lock the card navigation contract with a page test

**Files:**
- Modify: `tests/interface/web/test_pages.py`

**Interfaces:**
- Consumes: existing `client` fixture and `GET /w/{workspace}/requirements/mbse` route.
- Produces: assertions for four `.diagram-module-card` anchors, their labels/descriptions, preserved hrefs, and active state.

- [ ] **Step 1: Write the failing page test**

Add this test to `tests/interface/web/test_pages.py`:

```python
def test_mbse_design_page_uses_clickable_module_cards(client: TestClient) -> None:
    client.post("/workspaces", data={"name": "demo"})

    page = client.get("/w/demo/requirements/mbse?view=activity")

    assert page.status_code == 200
    assert page.text.count("diagram-module-card") == 4
    assert 'href="/w/demo/requirements/mbse?view=all"' in page.text
    assert 'href="/w/demo/requirements/mbse?view=use_case"' in page.text
    assert 'href="/w/demo/requirements/mbse?view=activity"' in page.text
    assert 'href="/w/demo/requirements/mbse/sequence"' in page.text
    assert "参与者与系统目标" in page.text
    assert "动作与控制流" in page.text
    assert "生命线与消息方向" in page.text
    assert 'class="diagram-module-card active"' in page.text
```

- [ ] **Step 2: Run the focused test and verify it fails**

```bash
.venv/bin/pytest tests/interface/web/test_pages.py::test_mbse_design_page_uses_clickable_module_cards -q
```

Expected: FAIL because the current template still emits `.diagram-tabs` links and does not emit `.diagram-module-card`.

### Task 2: Replace text tabs with isolated module cards

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/mbse-diagrams.html:9-16`
- Modify: `src/rflp_lite/interface/web/static/app.css` (append local `.diagram-card-*` rules)

**Interfaces:**
- Consumes: existing `diagram_view` template value and current four route URLs.
- Produces: four full-card `<a>` elements with `diagram-module-card`, `active`, `aria-current`, icon, type label, description, and arrow affordance.

- [ ] **Step 1: Replace the navigation markup**

Replace the current `diagram-tabs` block with:

```jinja2
  <div class="diagram-card-grid" aria-label="设计图类型">
    <a class="diagram-module-card {% if diagram_view == 'all' %}active{% endif %}" href="/w/{{ workspace.name }}/requirements/mbse?view=all" {% if diagram_view == 'all' %}aria-current="page"{% endif %}>
      <div class="diagram-card-top"><span class="diagram-card-icon" aria-hidden="true">Σ</span><span class="diagram-card-type">MODEL</span></div>
      <strong>总览</strong><span>查看全部 MBSE 语义视图</span><span class="diagram-card-arrow" aria-hidden="true">→</span>
    </a>
    <a class="diagram-module-card {% if diagram_view == 'use_case' %}active{% endif %}" href="/w/{{ workspace.name }}/requirements/mbse?view=use_case" {% if diagram_view == 'use_case' %}aria-current="page"{% endif %}>
      <div class="diagram-card-top"><span class="diagram-card-icon" aria-hidden="true">UC</span><span class="diagram-card-type">GOAL</span></div>
      <strong>用例图</strong><span>参与者与系统目标</span><span class="diagram-card-arrow" aria-hidden="true">→</span>
    </a>
    <a class="diagram-module-card {% if diagram_view == 'activity' %}active{% endif %}" href="/w/{{ workspace.name }}/requirements/mbse?view=activity" {% if diagram_view == 'activity' %}aria-current="page"{% endif %}>
      <div class="diagram-card-top"><span class="diagram-card-icon" aria-hidden="true">AC</span><span class="diagram-card-type">FLOW</span></div>
      <strong>活动图</strong><span>动作与控制流</span><span class="diagram-card-arrow" aria-hidden="true">→</span>
    </a>
    <a class="diagram-module-card {% if diagram_view == 'sequence' %}active{% endif %}" href="/w/{{ workspace.name }}/requirements/mbse/sequence" {% if diagram_view == 'sequence' %}aria-current="page"{% endif %}>
      <div class="diagram-card-top"><span class="diagram-card-icon" aria-hidden="true">↔</span><span class="diagram-card-type">INTERACTION</span></div>
      <strong>顺序图</strong><span>生命线与消息方向</span><span class="diagram-card-arrow" aria-hidden="true">→</span>
    </a>
  </div>
```

- [ ] **Step 2: Add only local card styles**

Append these rules to `src/rflp_lite/interface/web/static/app.css`:

```css
.diagram-card-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.diagram-module-card { position: relative; min-height: 142px; display: flex; flex-direction: column; gap: 7px; padding: 15px; border: 1px solid var(--color-line); border-radius: 12px; color: var(--color-text); background: linear-gradient(145deg, var(--color-panel-2), var(--color-panel)); transition: border-color .16s ease, background .16s ease, transform .16s ease; }
.diagram-module-card:hover, .diagram-module-card:focus-visible { border-color: rgba(112,225,188,.48); background: linear-gradient(145deg, rgba(112,225,188,.12), var(--color-panel)); transform: translateY(-1px); }
.diagram-module-card.active { border-color: rgba(112,225,188,.72); box-shadow: inset 0 0 0 1px rgba(112,225,188,.16), 0 10px 28px rgba(0,0,0,.12); }
.diagram-card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.diagram-card-icon { display: grid; place-items: center; width: 32px; height: 32px; border: 1px solid rgba(112,225,188,.28); border-radius: 8px; color: var(--color-accent); background: rgba(112,225,188,.08); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; font-weight: 800; }
.diagram-card-type { color: #668078; font-size: 8px; font-weight: 800; letter-spacing: .12em; }
.diagram-module-card strong { margin-top: 4px; font-size: 15px; }
.diagram-module-card > span:not(.diagram-card-arrow) { color: var(--color-muted); font-size: 10px; line-height: 1.45; }
.diagram-card-arrow { position: absolute; right: 15px; bottom: 13px; color: var(--color-accent); font-size: 16px; }
@media (max-width: 1050px) { .diagram-card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .diagram-card-grid { grid-template-columns: 1fr; } }
```

### Task 3: Run focused and full verification

**Files:**
- Test: `tests/interface/web/test_pages.py`
- Verify: `src/rflp_lite/interface/web/templates/mbse-diagrams.html`, `src/rflp_lite/interface/web/static/app.css`

**Interfaces:**
- Consumes: the four-card template and local CSS from Task 2.
- Produces: passing page regression and unchanged application behavior.

- [ ] **Step 1: Run the focused page tests**

```bash
.venv/bin/pytest tests/interface/web/test_pages.py -q
```

Expected: PASS, including the new card-navigation assertion.

- [ ] **Step 2: Check formatting and architecture**

```bash
git diff --check
.venv/bin/lint-imports
```

Expected: no whitespace errors; 3 architecture contracts kept, 0 broken.

- [ ] **Step 3: Run the full test suite**

```bash
.venv/bin/pytest -q
```

Expected: PASS with only the existing FastAPI TestClient deprecation warning.

- [ ] **Step 4: Commit the focused UI change**

```bash
git add src/rflp_lite/interface/web/templates/mbse-diagrams.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_pages.py
git commit -m "feat: present MBSE diagram views as cards"
```
