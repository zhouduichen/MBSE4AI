# 中文工作台与分析侧栏实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI4MBSE 的产品界面统一为简体中文，并在分析页增加可点击的分析模块侧栏与主区域详情切换。

**Architecture:** 页面层新增统一中文显示映射和 `analysis_modules` 视图数据，模板用模块 ID 生成侧栏卡片与配对详情面板。前端只负责无刷新切换显示状态，API 字段、内部 ID 和业务服务保持不变。

**Tech Stack:** FastAPI、Jinja2、原生 JavaScript、现有 CSS、pytest、Ruff。

## Global Constraints

- 用户可见网页文案统一使用简体中文；API 字段、URL、实体 kind、任务 ID 和审计标识保持原值。
- 分析模块必须从当前 ModelGraph、issues、run ledger 读取真实数据，不能写死数量。
- 空数据使用中文空状态；运行和修复失败使用中文提示并保留机器可读结果。
- 页面继续监听 `127.0.0.1`，不新增外部依赖或登录系统。

---

### Task 1: 添加中文视图映射与分析模块数据

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Produces `analysis_modules: list[dict[str, object]]` in `build_analysis_view()`.
- Each module contains `id`, `title`, `description`, `count`, `status`, `entities` and `issues`.

- [ ] **Step 1: Write the failing test**

```python
def test_analysis_view_contains_chinese_module_cards(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    for title in ("利益相关方", "生命周期", "场景与用例", "需求分析", "功能分析", "逻辑/物理架构", "验证与确认"):
        assert title in page.text
    assert "analysis-sidebar" in page.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py::test_analysis_view_contains_chinese_module_cards`

Expected: FAIL because the analysis template has no Chinese module-card data.

- [ ] **Step 3: Write the minimal implementation**

Add page-layer maps and a helper with this contract:

```python
_ANALYSIS_MODULES = (
    ("stakeholders", "利益相关方", "参与者、关注点与利益关系", (EntityKind.STAKEHOLDER, EntityKind.CONCERN)),
    ("lifecycle", "生命周期", "阶段、转移与运行边界", (EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION)),
    ("scenarios", "场景与用例", "场景假设、用例、活动与运行场景", (EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE, EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY)),
    ("requirements", "需求分析", "需求、来源、证据与验收约束", (EntityKind.REQUIREMENT,)),
    ("functions", "功能分析", "功能、功能流与功能场景", (EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.FUNCTIONAL_SCENARIO)),
    ("architecture", "逻辑/物理架构", "逻辑组件、物理块、接口与状态", (EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK, EntityKind.INTERFACE, EntityKind.STATE)),
    ("verification", "验证与确认", "验证、确认、危险源与失效模式", (EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE, EntityKind.HAZARD, EntityKind.FAILURE_MODE)),
    ("evidence", "证据与问题", "证据记录、Gate 问题与修复入口", (EntityKind.EVIDENCE,)),
    ("runs", "运行与审计", "当前任务、运行台账、修复与封版", ()),
)
```

For each tuple, filter `graph.entities` by `kind`, convert each entity with `_plain(item.as_dict())`, set `count` to the entity count, set `status` to `"有记录"` or `"暂无记录"`, and attach matching issues for `evidence`. Add the resulting list to the returned view as `analysis_modules`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py::test_analysis_view_contains_chinese_module_cards`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/web/resource_pages.py tests/interface/web/test_analysis_workflow.py
git commit -m "feat: add Chinese analysis module view data"
```

### Task 2: 将网页文案和分析页布局改成中文侧栏

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `src/rflp_lite/interface/web/templates/projects.html`
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/evidence-issues.html`
- Modify: `src/rflp_lite/interface/web/templates/settings.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_analysis_workflow.py`
- Test: `tests/interface/web/test_model_trace.py`
- Test: `tests/interface/web/test_settings_runtime_status.py`

**Interfaces:**
- The analysis page renders one button per `analysis_modules` item with `data-module-id`.
- The matching detail panel uses `data-module-panel` and remains in the same page.

- [ ] **Step 1: Write the failing interaction assertions**

```python
def test_analysis_cards_switch_detail_panels_without_navigation(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert 'data-module-id="stakeholders"' in page.text
    assert 'data-module-panel="stakeholders"' in page.text
    assert "aria-selected" in page.text
    assert "切换模块" in page.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py::test_analysis_cards_switch_detail_panels_without_navigation`

Expected: FAIL because the template has no module cards or panel switch script.

- [ ] **Step 3: Write the minimal implementation**

Use this template interaction contract:

```html
<aside class="analysis-sidebar" aria-label="分析模块">
  <p class="sidebar-title">分析模块</p>
  {% for module in analysis_modules %}
  <button class="analysis-module-card{% if loop.first %} selected{% endif %}" type="button"
          data-module-id="{{ module.id }}" aria-selected="{{ 'true' if loop.first else 'false' }}">
    <span><strong>{{ module.title }}</strong><small>{{ module.description }}</small></span>
    <b>{{ module.count }}</b>
  </button>
  {% endfor %}
</aside>
<div class="analysis-detail" aria-live="polite">
  {% for module in analysis_modules %}
  <section class="panel analysis-module-panel" data-module-panel="{{ module.id }}"{% if not loop.first %} hidden{% endif %}>
    <div class="panel-head"><div><h2>{{ module.title }}</h2><p>{{ module.description }}</p></div><span class="count-badge">{{ module.count }} 条记录</span></div>
    {% if module.entities %}<div class="record-list">{% for entity in module.entities %}<article><span class="status-badge">{{ entity.status }}</span><div><strong>{{ entity.name }}</strong><p>{{ entity.kind }}</p><code>{{ entity.id }}</code></div></article>{% endfor %}</div>{% else %}<div class="mini-empty">暂无{{ module.title }}记录</div>{% endif %}
  </section>
  {% endfor %}
</div>
```

Add a small script that listens to `.analysis-module-card`, toggles `hidden` on `[data-module-panel]`, updates `aria-selected`, and never calls `fetch` or changes `location`. Translate all visible labels in the affected templates, including navigation, page headings, buttons, status text, table headings, error strings and empty states. Keep `project_id`, entity kind values, task IDs and API paths unchanged in attributes and scripts.

- [ ] **Step 4: Run the focused Web tests**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py tests/interface/web/test_model_trace.py tests/interface/web/test_settings_runtime_status.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/web/templates/base.html src/rflp_lite/interface/web/templates/projects.html src/rflp_lite/interface/web/templates/analysis.html src/rflp_lite/interface/web/templates/model.html src/rflp_lite/interface/web/templates/evidence-issues.html src/rflp_lite/interface/web/templates/settings.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_analysis_workflow.py tests/interface/web/test_model_trace.py tests/interface/web/test_settings_runtime_status.py
git commit -m "feat: localize Web workbench and add analysis sidebar"
```

### Task 3: 中文化 CLI、补齐回归测试并验证打包页面

**Files:**
- Modify: `src/rflp_lite/interface/cli_v2.py`
- Modify: `README.md`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- CLI JSON output remains machine-compatible; only command help and human-facing error fallback are translated.
- Wheel must include the translated Jinja templates and `static/app.css`.

- [ ] **Step 1: Add the failing localization checks**

```python
def test_analysis_page_uses_chinese_labels_for_runtime_and_gate(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert "当前修订" in page.text
    assert "活动模型" in page.text
    assert "全局 Gate" in page.text
    assert "Run full pipeline" not in page.text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py::test_analysis_page_uses_chinese_labels_for_runtime_and_gate`

Expected: FAIL because existing headings still contain English labels.

- [ ] **Step 3: Implement the remaining user-facing copy changes**

Translate CLI help strings and exception fallback text in `cli_v2.py`; update README startup examples and UI descriptions to identify the Chinese workbench. Do not translate JSON values such as `"status"`, `"completed"`, or phase IDs. Update the templates so status presentation uses page-layer Chinese labels, while CSS class names remain stable.

- [ ] **Step 4: Run all verification commands**

Run:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m ruff check src tests
./.venv/bin/python -m compileall -q src
git diff --check
uv build --out-dir /tmp/ai4mbse-wheel-20260909-cn
```

Expected: all tests and checks PASS; both wheel and source distribution are created; the wheel contains `analysis.html`, `model.html`, `settings.html` and `app.css`.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/cli_v2.py README.md tests/interface/web/test_analysis_workflow.py
git commit -m "feat: finish Chinese product interface"
```
