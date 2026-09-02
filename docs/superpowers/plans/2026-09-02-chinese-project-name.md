# 中文项目名与可编辑创建框 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持中文项目名，并让“开始项目”页的项目名输入框可以直接点击、聚焦和提交。

**Architecture:** 后端工作区名称校验改为 Unicode 安全字符规则，允许中文、字母、数字、点、下划线和短横线，继续禁止路径分隔符、控制字符和危险的首字符。前端移除只允许 ASCII 的浏览器校验，使用文本类型、中文占位提示、最大长度和自动聚焦；现有目录、路由和项目创建流程保持不变。

**Tech Stack:** Python 3.12、FastAPI、Jinja2、pytest。

## Global Constraints

- 项目名长度为 1 至 64 个字符。
- 项目名允许中文、Unicode 字母、数字、点、下划线和短横线。
- 项目名不得包含空格、斜杠、反斜杠或控制字符，且首字符不能是点、下划线或短横线。
- 已有英文项目名继续可用，重复项目不得覆盖已有目录。
- 不增加显示名与路径别名双字段，不把中文项目名自动转换成拼音。
- 只修改项目名相关源代码和测试，保留现有 OCR、测试和资料文件改动。

---

## Task 1: 先补中文创建和可编辑输入测试

**Files:**
- Modify: `tests/application/test_workspaces.py`
- Modify: `tests/interface/web/test_pages.py`

**Interfaces:**
- `create_managed_workspace(root: Path, name: str) -> WorkspaceRef` 接受中文名称。
- `POST /workspaces` 接受中文表单值并返回 `303` 到对应工作区路径。

- [ ] **Step 1: Add failing application test**

Append to `tests/application/test_workspaces.py`:

```python

def test_managed_workspace_accepts_chinese_name(tmp_path: Path) -> None:
    created = create_managed_workspace(tmp_path / "workspaces", "中文测试项目")

    assert created.name == "中文测试项目"
    assert created.path.is_dir()
    assert list_managed_workspaces(tmp_path / "workspaces")[0].name == "中文测试项目"
```

- [ ] **Step 2: Add failing Web tests**

Append to `tests/interface/web/test_pages.py`:

```python

def test_project_name_input_is_editable_and_accepts_chinese(client: TestClient) -> None:
    page = client.get("/")

    assert page.status_code == 200
    assert 'id="project-name"' in page.text
    assert 'type="text"' in page.text
    assert 'autofocus' in page.text
    assert 'placeholder="例如：小型飞行汽车项目"' in page.text
    assert 'pattern="[A-Za-z0-9]' not in page.text
    assert 'readonly' not in page.text
    assert 'disabled' not in page.text

    created = client.post(
        "/workspaces", data={"name": "中文测试项目"}, follow_redirects=False
    )

    assert created.status_code == 303
    assert created.headers["location"] == "/w/中文测试项目"
```

- [ ] **Step 3: Run the focused tests and verify they fail**

Run:

```bash
.venv/bin/pytest -q tests/application/test_workspaces.py tests/interface/web/test_pages.py -k "chinese_name or project_name_input"
```

Expected: FAIL because the backend ASCII regular expression rejects `中文测试项目` and the current input has no stable ID, autofocus, or Chinese placeholder.

## Task 2: Implement Unicode-safe validation and a focusable input

**Files:**
- Modify: `src/rflp_lite/application/workspaces.py:14`
- Modify: `src/rflp_lite/interface/web/templates/project-management.html:39`

**Interfaces:**
- `_WORKSPACE_NAME` remains an internal compiled regular expression used by `managed_workspace`.
- The HTML form continues to submit `name` to `POST /workspaces`.

- [ ] **Step 1: Replace the ASCII-only backend rule**

In `src/rflp_lite/application/workspaces.py`, replace the current regular expression:

```python
_WORKSPACE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
```

with:

```python
_WORKSPACE_NAME = re.compile(r"[^\W_][\w.-]{0,63}\Z", re.UNICODE)
```

This accepts Unicode word characters such as Chinese characters while rejecting whitespace, slashes, backslashes, control characters, and a leading dot or underscore. Keep `managed_workspace` path containment checks unchanged.

- [ ] **Step 2: Make the input explicitly editable and Chinese-friendly**

Replace the form line in `src/rflp_lite/interface/web/templates/project-management.html` with:

```html
<section class="panel create-project-panel" id="create-project"><div class="panel-head"><div><h2>创建项目</h2></div></div><form method="post" action="/workspaces" class="inline-form"><label for="project-name">项目名称<input id="project-name" type="text" name="name" value="" placeholder="例如：小型飞行汽车项目" maxlength="64" autocomplete="off" autofocus required></label><button class="button primary" type="submit">创建并开始</button></form></section>
```

Do not add `readonly`, `disabled`, or an ASCII-only `pattern`.

- [ ] **Step 3: Run focused tests and verify they pass**

Run:

```bash
.venv/bin/pytest -q tests/application/test_workspaces.py tests/interface/web/test_pages.py -k "chinese_name or project_name_input"
```

Expected: PASS for the Chinese workspace creation and editable form tests.

- [ ] **Step 4: Run related regression tests**

Run:

```bash
.venv/bin/pytest -q tests/application/test_workspaces.py tests/application/test_web_facade.py tests/interface/web/test_app.py tests/interface/web/test_pages.py
```

Expected: PASS with existing English project creation, project listing, redirects, and page behavior unchanged.

- [ ] **Step 5: Check the final diff and commit**

Run:

```bash
git diff --check
git status --short
git add src/rflp_lite/application/workspaces.py src/rflp_lite/interface/web/templates/project-management.html tests/application/test_workspaces.py tests/interface/web/test_pages.py
git commit -m "feat: allow Chinese project names"
```

Expected: only the four project-name source/test files are included in this commit; existing user-owned OCR and artifact files remain unstaged.
