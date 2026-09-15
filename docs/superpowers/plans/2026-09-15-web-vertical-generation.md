# Web 纵向模型生成工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Web 的完整五阶段生成按钮改为立即返回 Run、可轮询阶段进度并在完成后回到同一份可编辑 ModelGraph 的用户主流程。

**Architecture:** 保留现有同步 `/projects/{id}/analysis` 和 CLI，新增 `/projects/{id}/analysis/runs` 作为 Web 五阶段入口。请求线程只负责输入校验和创建持久化 Run，受限线程池调用既有 `ModelGenerationService.generate`；Run 的五个 vertical Step 是唯一进度真源，GET Run 只增加高层 `progress` 投影。浏览器轮询结束后重新加载现有 Analysis/ModelGraph 投影，不复制或重建模型结果。

**Tech Stack:** Python 3.11+, FastAPI, `concurrent.futures.ThreadPoolExecutor`, SQLite repository/RLock, existing `ModelGenerationService`, vanilla JavaScript, pytest, ruff。

## Global Constraints

- ModelGraph 是模型唯一真源；异步层不得绕过 Runtime → Compiler → Validator → CAS。
- 旧同步 API、CLI、23-task pipeline 和现有五阶段生成语义保持兼容。
- UI 首屏只显示 Requirements → Functional → Logical → Physical → V&V 阶段，不把 TaskSpec、Patch、CAS 或原始 LLM 响应作为用户主流程。
- 远程 SSH/Tailscale LLM 是唯一真实 Provider 验收来源；不得启动或调用本机模型，不得自动回退到 `127.0.0.1`。
- 后台异常必须写入有界 failed Run；不得把部分模型或远程失败宣称为完整成功。
- 每个实现任务都必须先有针对性测试，再修改最小范围代码。

---

### Task 1: 提取可复用的 Generation Run 准备边界

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py:201-240, 1135-1190`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Produces `ModelGenerationService.prepare_generation(project_id, *, requirement_text=None, document_ids=(), run_id=None, force_new=False) -> str`。
- `prepare_generation` 调用现有输入检查和 `_ensure_run`，返回已持久化的有效 Run ID；它不调用 LLM。
- `generate` 复用该方法，不重复创建 Run。

- [ ] **Step 1: Write the failing test**

在 `tests/application/test_model_generation.py` 增加：

```python
def test_prepare_generation_creates_persisted_run_without_executing_runtime(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")

    run_id = generation.prepare_generation(
        "robot",
        requirement_text="系统应支持人工接管",
        run_id="web-run-prepared",
    )

    run = services.repository("robot").load_run("robot", run_id)
    assert run_id == "web-run-prepared"
    assert run is not None
    assert run.status == "running"
    assert [step.task_id for step in run.steps] == [
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ]
    assert services.model("robot").graph("robot").revision == 1
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/test_model_generation.py::test_prepare_generation_creates_persisted_run_without_executing_runtime
```

Expected: FAIL because `prepare_generation` is not defined。

- [ ] **Step 3: Implement the preparation method and reuse it from `generate`**

在 `ModelGenerationService` 中加入：

```python
def prepare_generation(
    self,
    project_id: str,
    *,
    requirement_text: str | None = None,
    document_ids: tuple[str, ...] = (),
    run_id: str | None = None,
    force_new: bool = False,
) -> str:
    request = GenerateModelRequest(
        project_id,
        requirement_text,
        tuple(document_ids),
        run_id,
        force_new,
    )
    self._ensure_input(request)
    graph = self.repository.load_graph(project_id)
    effective_run_id = run_id or f"generation-{uuid4().hex[:16]}"
    self._ensure_run(effective_run_id, project_id, graph)
    return effective_run_id
```

将 `generate` 开头构造 `GenerateModelRequest`、调用 `_ensure_input`、加载 graph 和 `_ensure_run` 的代码替换为：

```python
effective_run_id = self.prepare_generation(
    project_id,
    requirement_text=requirement_text,
    document_ids=document_ids,
    run_id=run_id,
    force_new=force_new,
)
```

保留后续五阶段循环和所有现有 `force_new` 参数，不改变它们的结果语义。

- [ ] **Step 4: Run the focused test and existing generation tests**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/test_model_generation.py::test_prepare_generation_creates_persisted_run_without_executing_runtime tests/application/test_model_generation.py
```

Expected: PASS。

- [ ] **Step 5: Commit the application boundary**

```bash
git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py
git commit -m "feat: expose generation run preparation"
```

### Task 2: Add the Web asynchronous Run endpoint and progress projection

**Files:**
- Modify: `src/rflp_lite/interface/web/app.py`
- Modify: `src/rflp_lite/interface/web/resource_api.py:680-705`
- Test: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- `POST /projects/{project_id}/analysis/runs` accepts the full-generation request and returns HTTP 202 with `run_id` and `progress_url`。
- `GET /projects/{project_id}/runs/{run_id}` preserves `asdict(run)` and adds `progress` with `status`, `current_stage`, `current_stage_label`, `completed_stages`, `total_stages`, and five `stages` entries。
- The worker calls `generation.generate(..., run_id=run_id, force_new=True)` and on unexpected exception calls `repository.update_run(run_id, "failed", (bounded_message,))`。

- [ ] **Step 1: Write the failing API tests**

在 `tests/interface/web/test_vertical_generation_api.py` 增加慢速运行时：

```python
from threading import Event
import time


class BlockingVerticalRuntime(VerticalRuleRuntime):
    def __init__(self):
        self.started = Event()
        self.release = Event()

    def execute(self, request):
        self.started.set()
        assert self.release.wait(5)
        return super().execute(request)


def test_async_generation_returns_run_before_model_generation_finishes(tmp_path: Path):
    app = create_app(tmp_path / "workspaces")
    runtime = BlockingVerticalRuntime()
    app.state.container.v2._runtime_override = runtime
    client = TestClient(app)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    accepted = client.post(
        "/projects/p1/analysis/runs",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    )

    assert accepted.status_code == 202
    run = accepted.json()["run"]
    assert run["status"] == "running"
    assert run["progress_url"] == f"/projects/p1/runs/{run['run_id']}"
    assert runtime.started.wait(2)
    progress = client.get(run["progress_url"]).json()
    assert progress["status"] == "ok"
    assert progress["run"]["progress"]["total_stages"] == 5
    assert progress["run"]["progress"]["current_stage"] == "requirements"

    runtime.release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        completed = client.get(run["progress_url"]).json()["run"]
        if completed["status"] == "completed":
            break
        time.sleep(0.02)
    assert completed["status"] == "completed"
    assert completed["progress"]["completed_stages"] == 5
    assert client.get("/projects/p1/model").json()["revision"] >= 1
```

同时增加 `test_async_generation_rejects_pipeline_mode_before_creating_run`，发送 `{"mode": "pipeline"}`，断言 422 且 `list_runs("p1") == ()`。

- [ ] **Step 2: Run the new tests and verify they fail**

```bash
./.venv/bin/python -m pytest -q tests/interface/web/test_vertical_generation_api.py::test_async_generation_returns_run_before_model_generation_finishes tests/interface/web/test_vertical_generation_api.py::test_async_generation_rejects_pipeline_mode_before_creating_run
```

Expected: FAIL with 404 because the async endpoint does not exist。

- [ ] **Step 3: Implement the executor and bounded progress projection**

在 `create_app` 中创建：

```python
from concurrent.futures import ThreadPoolExecutor

app.state.analysis_executor = ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="ai4mbse-generation",
)
```

注册 shutdown handler 使用 `shutdown(wait=False, cancel_futures=True)`。

在 `resource_api.py` 添加阶段常量和投影函数；每个 Step 通过 `task_id.removeprefix("vertical.")` 映射到中文阶段。状态规则为：当前 `running` step 为 running；之前 completed 的为 completed；之后为 queued；Run 进入终态时未完成的阶段使用 Run 状态。投影不得包含原始响应或不受限异常堆栈。

添加 worker：

```python
def _run_generation_job(services, project_id, run_id, requirement_text, document_ids, profile_id):
    try:
        services.generation(project_id, profile_id=profile_id).generate(
            project_id,
            requirement_text=requirement_text,
            document_ids=document_ids,
            run_id=run_id,
            force_new=True,
        )
    except Exception as exc:
        services.repository(project_id).update_run(
            run_id,
            "failed",
            (f"async_generation_{type(exc).__name__}: {str(exc)[:240]}",),
        )
```

添加 endpoint：解析 payload、只允许 `generate`/`vertical`，先应用 `goal`，复用现有输入边界检查，调用 `prepare_generation` 创建 `web-run-{uuid}`，提交 worker，并返回 202。不要在 endpoint 中调用 `deliverables.build` 或任何 LLM。

在既有 `get_run` 返回值中加入：

```python
payload = asdict(run)
payload["progress"] = _run_progress(run)
return {"status": "ok", "run": payload}
```

- [ ] **Step 4: Run API tests and focused Web regression**

```bash
./.venv/bin/python -m pytest -q tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_assurance_view.py
```

Expected: PASS。

- [ ] **Step 5: Commit the async endpoint**

```bash
git add src/rflp_lite/interface/web/app.py src/rflp_lite/interface/web/resource_api.py tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: add asynchronous web generation runs"
```

### Task 3: Connect the Analysis workbench to high-level polling

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/analysis.html:315-340`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Complete-generation submit calls `/projects/{id}/analysis/runs`。
- Single-phase debug buttons continue calling `/projects/{id}/analysis` synchronously。
- Browser polling reads the returned `progress_url` and only presents stage labels, counts and terminal messages。

- [ ] **Step 1: Write the failing page assertion**

在 `tests/interface/web/test_analysis_workflow.py` 增加：

```python
def test_analysis_page_uses_async_full_generation_workflow(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert "/analysis/runs" in page.text
    assert "当前阶段" in page.text
    assert "vertical.requirements" not in page.text
```

- [ ] **Step 2: Run the page test and verify it fails**

```bash
./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py::test_analysis_page_uses_async_full_generation_workflow
```

Expected: FAIL because the template posts to the synchronous `/analysis` path and has no high-level progress copy。

- [ ] **Step 3: Replace only the full-generation browser call**

在 `analysis.html` 的 `runAnalysis` 中保留 `phase` 分支；当 `mode === "generate"` 时：

```javascript
const endpoint = mode === "generate"
  ? `/projects/${encodeURIComponent(projectId)}/analysis/runs`
  : `/projects/${encodeURIComponent(projectId)}/analysis`;
const response = await fetch(endpoint, {
  method: "POST",
  headers: {"content-type": "application/json"},
  body: JSON.stringify(body),
});
const payload = await response.json();
if (mode !== "generate" || response.status !== 202) {
  output.textContent = JSON.stringify(payload, null, 2);
  if (payload.status === "ok") window.setTimeout(() => window.location.reload(), 300);
  return;
}
const progressUrl = payload.run.progress_url;
for (let attempt = 0; attempt < 900; attempt += 1) {
  const progressResponse = await fetch(progressUrl);
  const progressPayload = await progressResponse.json();
  if (!progressResponse.ok || progressPayload.status !== "ok") throw new Error(progressPayload.message || "读取生成进度失败");
  const progress = progressPayload.run.progress;
  const current = progress.current_stage_label || "准备输入";
  output.textContent = `当前阶段：${current}\n已完成 ${progress.completed_stages}/${progress.total_stages} 个阶段`;
  if (["completed", "failed", "blocked", "degraded", "cancelled"].includes(progress.status)) {
    if (progress.status === "completed") window.setTimeout(() => window.location.reload(), 300);
    else output.classList.add("warning");
    break;
  }
  await new Promise((resolve) => window.setTimeout(resolve, 1000));
}
```

轮询超时显示“运行仍在后台，请打开运行记录查看”，不提交新请求。按钮和 `force_run` 在轮询期间保持禁用。

- [ ] **Step 4: Run Web regression and lint**

```bash
./.venv/bin/python -m pytest -q tests/interface/web/test_analysis_workflow.py tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_assurance_view.py
./.venv/bin/ruff check src tests
```

Expected: PASS。

- [ ] **Step 5: Commit the workbench integration**

```bash
git add src/rflp_lite/interface/web/templates/analysis.html tests/interface/web/test_analysis_workflow.py
git commit -m "feat: show asynchronous generation progress"
```

### Task 4: Document and verify the complete product slice

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: all existing tests and repository gates

**Interfaces:**
- Documentation names the Web async endpoint, high-level stage progress, and remote-only live LLM test rule。
- No document claims live Provider success while `Jiayu-intern` vLLM is not API-ready。

- [ ] **Step 1: Update product documentation**

在 README Web/验收段落加入：Web 完整生成通过 `/analysis/runs` 异步提交并轮询 `/runs/{run_id}`，完成后回到同一 ModelGraph revision；单阶段调试仍为同步入口。开发状态新增对应验收行，并记录 `Jiayu-intern` 端口转发方式。

- [ ] **Step 2: Run all repository gates in an isolated test configuration**

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-test-config-20260915 ./.venv/bin/python -m pytest -q
RFLP_CONFIG_DIR=/tmp/ai4mbse-test-config-20260915 ./.venv/bin/python -m compileall -q src tests scripts
RFLP_CONFIG_DIR=/tmp/ai4mbse-test-config-20260915 ./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
git diff --check
```

Expected: all tests and contracts pass; architecture metrics remain within the existing budget。

- [ ] **Step 3: Execute one remote-only smoke test when the server is ready**

先用 SSH 只读确认：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 -o ConnectionAttempts=1 Jiayu-intern \
  'curl -fsS --max-time 10 http://127.0.0.1:8000/v1/models'
```

服务就绪后建立 `-L 18000:127.0.0.1:8000` 隧道，在临时 `RFLP_CONFIG_DIR` 注册 `http://127.0.0.1:18000/v1`、模型 `qwen3.5-controller` 的 Profile，并只执行一次 `CASE-04 --path vertical --repeats 1`。若远端 API 未就绪，只记录状态，不启动本机模型、不替换为本机端点。

- [ ] **Step 4: Commit and push the complete slice**

```bash
git add README.md docs/DEVELOPMENT_STATUS.md
git commit -m "docs: document asynchronous vertical generation"
git push origin HEAD
git status --short --branch
```
