# Controller 自动迭代闭环实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Methodology/Controller/定向重分析之上，增加一个有界的安全迭代入口，让系统能够自动推进可执行工程动作并在需要用户决策时暂停。

**Architecture:** `ModelGenerationService.iterate_controller` 每轮从 Repository 读取最新 ModelGraph，调用确定性的 Methodology/Controller 选取一个动作，并只自动执行 `reanalyze` 或成功的 `collect_evidence`。每次执行复用现有 CAS、Run、Patch、LLM Compiler 和 Validator；迭代结果汇总每轮 revision、Traceability、findings 和停止原因。Web 只增加一个入口，Trade Study 仍由用户通过现有单动作 API 选择。

**Tech Stack:** Python 3.11+, existing `ModelGenerationService`, `SystemsEngineeringController`, `MethodologyEngine`, FastAPI Resource API, Jinja/vanilla JavaScript, pytest.

## Global Constraints

- `max_iterations` 必须是 1 到 8 的整数，应用层拒绝范围外的值。
- 只自动执行 `reanalyze` 和 Tool Layer 成功的 `collect_evidence`。
- `trade_study` 返回 `awaiting_decision`，`collect_input` 返回 `awaiting_input`，证据工具等待返回 `awaiting_evidence`。
- 定向重分析明确失败返回 `failed`；相同 action 在相同 revision 重复出现或 revision 不增长返回 `no_progress`。
- 不修改或删除 `locked`、`user_modified` 实体，不绕过 CAS、PatchPolicy、Compiler、Validator 或 Review。
- 每个局部重分析继续使用既有 Run/Step/Patch/Revision；新增 iteration 只写审计事件，不新增持久化状态机。
- 旧 `/projects/{project_id}/controller/execute` 和已有五阶段生成行为保持兼容。

---

### Task 1: Implement the bounded controller iteration service

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py` near `controller_plan` and `execute_controller_action`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: `SystemsEngineeringController.plan`, `ModelGenerationService.execute_controller_action`, `build_traceability_summary`, current Repository revision.
- Produces: `ModelGenerationService.iterate_controller(project_id, *, max_iterations=3, expected_revision=None) -> Mapping[str, object]` with `iteration_id`, `execution_status`, `start_revision`, `revision`, `iterations`, `traceability`, `methodology`, and `controller`.

- [ ] **Step 1: Write service tests for terminal states and progress guards**

Add these imports to `tests/application/test_model_generation.py`:

```python
from rflp_lite.methodology.controller import ControllerAction, ControllerPlan
```

Add tests that use the real application service and a small controller stub where a loop guard is required:

```python
def test_controller_iteration_finishes_without_actions(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").iterate_controller("robot")

    assert result["execution_status"] == "completed"
    assert result["iterations"] == []
    assert result["start_revision"] == result["revision"] == 0


def test_controller_iteration_stops_at_trade_study_without_mutating_graph(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generated = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    graph = services.model("robot").graph("robot")
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    services.review("robot").edit_entity(
        "robot", requirement.id,
        payload={"constraints": {"max_power_w": 50}},
        expected_revision=graph.revision,
    )
    graph = services.model("robot").graph("robot")
    services.review("robot").edit_entity(
        "robot", physical.id,
        payload={"power_w": 80},
        expected_revision=graph.revision,
    )
    before = services.model("robot").graph("robot").revision

    result = services.generation("robot").iterate_controller("robot", max_iterations=3)

    assert result["execution_status"] == "awaiting_decision"
    assert result["revision"] == before
    assert result["iterations"] == []
    assert result["controller"]["next_action"]["kind"] == "trade_study"
    assert generated.revision < before


def test_controller_iteration_reports_no_progress_for_repeated_action(tmp_path: Path, monkeypatch):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generation = services.generation("robot")
    action = ControllerAction(
        "controller-action-test", "reanalyze", "functional_interaction", "functional", "P1",
        ("function-1",), "补足功能流"
    )
    plan = ControllerPlan("needs_action", "推进模型", ("functional_flow_missing",), (action,))
    monkeypatch.setattr(generation.controller, "plan", lambda graph, report=None, max_actions=8: plan)
    monkeypatch.setattr(
        generation,
        "execute_controller_action",
        lambda project_id, **kwargs: {
            "execution_status": "completed",
            "action": action.as_dict(),
            "reanalysis": {"execution_status": "completed", "revision": 0},
        },
    )

    result = generation.iterate_controller("robot", max_iterations=3)

    assert result["execution_status"] == "no_progress"
    assert len(result["iterations"]) == 1
    assert result["iterations"][0]["revision_before"] == result["iterations"][0]["revision_after"] == 0
```

- [ ] **Step 2: Run the service tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/test_model_generation.py -q -k controller_iteration`

Expected: FAIL because `ModelGenerationService` has no `iterate_controller` method.

- [ ] **Step 3: Implement the bounded iteration method**

Insert this method after `controller_plan` and before `execute_controller_action`:

```python
    def iterate_controller(
        self,
        project_id: str,
        *,
        max_iterations: int = 3,
        expected_revision: int | None = None,
    ) -> Mapping[str, object]:
        steps_limit = int(max_iterations)
        if not 1 <= steps_limit <= 8:
            raise ContractViolation("max_iterations must be between 1 and 8")
        initial_graph = self.repository.load_graph(project_id)
        if expected_revision is not None and int(expected_revision) != initial_graph.revision:
            raise ConflictError(
                f"stale controller iteration: expected {expected_revision}, current {initial_graph.revision}"
            )
        iteration_id = f"controller-iteration-{uuid4().hex[:16]}"
        start_revision = initial_graph.revision
        records: list[dict[str, object]] = []
        seen: set[tuple[str, int]] = set()
        terminal_status = "max_iterations"
        self._audit(project_id, "controller.iteration.started", {
            "iteration_id": iteration_id,
            "start_revision": start_revision,
            "max_iterations": steps_limit,
        })
        for sequence in range(1, steps_limit + 1):
            before_graph = self.repository.load_graph(project_id)
            before_report = self.methodology_engine.analyze(before_graph)
            before_plan = self.controller.plan(before_graph, before_report)
            action = before_plan.next_action
            if action is None:
                terminal_status = "completed"
                break
            fingerprint = (action.id, before_graph.revision)
            if fingerprint in seen:
                terminal_status = "no_progress"
                break
            seen.add(fingerprint)
            if action.kind == "trade_study":
                terminal_status = "awaiting_decision"
                break
            if action.kind == "collect_input":
                terminal_status = "awaiting_input"
                break
            if action.kind not in {"reanalyze", "collect_evidence"}:
                terminal_status = "failed"
                break
            execution = self.execute_controller_action(
                project_id,
                action_id=action.id,
                expected_revision=before_graph.revision,
            )
            after_graph = self.repository.load_graph(project_id)
            after_report = self.methodology_engine.analyze(after_graph)
            nested = execution.get("reanalysis", {})
            nested_status = str(nested.get("execution_status", "completed")) if isinstance(nested, Mapping) else "completed"
            record = {
                "sequence": sequence,
                "action": action.as_dict(),
                "execution_status": execution.get("execution_status", "completed"),
                "revision_before": before_graph.revision,
                "revision_after": after_graph.revision,
                "traceability_before": build_traceability_summary(before_graph).as_dict(),
                "traceability_after": build_traceability_summary(after_graph).as_dict(),
                "finding_codes_before": [item.code for item in before_report.findings],
                "finding_codes_after": [item.code for item in after_report.findings],
                "result": execution,
            }
            records.append(record)
            self._audit(project_id, "controller.iteration.step", {
                "iteration_id": iteration_id,
                **{key: value for key, value in record.items() if key != "result"},
            })
            if execution.get("execution_status") == "awaiting_evidence":
                terminal_status = "awaiting_evidence"
                break
            if nested_status == "failed":
                terminal_status = "failed"
                break
            if after_graph.revision <= before_graph.revision:
                terminal_status = "no_progress"
                break
        final_graph = self.repository.load_graph(project_id)
        final_report = self.methodology_engine.analyze(final_graph)
        final_controller = self.controller.plan(final_graph, final_report)
        payload = {
            "iteration_id": iteration_id,
            "project_id": project_id,
            "execution_status": terminal_status,
            "start_revision": start_revision,
            "revision": final_graph.revision,
            "iterations": records,
            "traceability": build_traceability_summary(final_graph).as_dict(),
            "methodology": final_report.as_dict(),
            "controller": final_controller.as_dict(),
        }
        self._audit(project_id, f"controller.iteration.{terminal_status}", {
            "iteration_id": iteration_id,
            "start_revision": start_revision,
            "revision": final_graph.revision,
            "iteration_count": len(records),
        })
        return payload
```

The `collect_evidence` branch must preserve the existing tool result inside `result`; only a `completed` tool action with a successful nested reanalysis can proceed to another loop iteration. The existing `execute_controller_action` implementation remains unchanged.

- [ ] **Step 4: Run the service tests and the existing Controller tests**

Run: `./.venv/bin/pytest tests/application/test_model_generation.py tests/methodology/test_controller.py -q`

Expected: PASS, including the existing single-action and trade-study behavior.

- [ ] **Step 5: Commit the service iteration**

```bash
git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py
git commit -m "feat: add bounded controller iteration"
```

### Task 2: Expose Controller iteration through the Resource API

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py` after `/controller/execute`
- Test: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: JSON `{ "max_iterations": 3, "expected_revision": 14 }`.
- Produces: `{ "status": "ok", "controller": <iterate_controller result> }`, with the same error handling and HTTP status mapping as `/controller/execute`.

- [ ] **Step 1: Write API tests**

Add:

```python
def test_controller_iteration_endpoint_returns_waiting_decision(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    model = client.get("/projects/p1/model").json()
    requirement_id = next(item["id"] for item in model["entities"] if item["kind"] == "requirement")
    physical_id = next(item["id"] for item in model["entities"] if item["kind"] == "physical_block")
    edited = client.post(
        f"/projects/p1/entities/{requirement_id}/edit",
        json={"expected_revision": generated["revision"], "payload": {"constraints": {"max_power_w": 50}}},
    )
    edited_physical = client.post(
        f"/projects/p1/entities/{physical_id}/edit",
        json={"expected_revision": edited.json()["revision"]["sequence"], "payload": {"power_w": 80}},
    )
    revision = edited_physical.json()["revision"]["sequence"]

    response = client.post(
        "/projects/p1/controller/iterate",
        json={"max_iterations": 3, "expected_revision": revision},
    )

    assert response.status_code == 200
    payload = response.json()["controller"]
    assert payload["execution_status"] == "awaiting_decision"
    assert payload["revision"] == revision


def test_controller_iteration_endpoint_rejects_stale_revision(tmp_path: Path):
    client = _client(tmp_path)
    assert client.post("/projects", json={"id": "p1"}).status_code == 200

    response = client.post(
        "/projects/p1/controller/iterate",
        json={"max_iterations": 3, "expected_revision": 9},
    )

    assert response.status_code == 409
```

- [ ] **Step 2: Run the API tests and verify the new route fails**

Run: `./.venv/bin/pytest tests/interface/web/test_vertical_generation_api.py -q -k controller_iteration`

Expected: FAIL because the route is not registered.

- [ ] **Step 3: Add the API route**

Add this route after the existing `/projects/{project_id}/controller/execute` handler:

```python
@resource_api.post("/projects/{project_id}/controller/iterate")
async def iterate_controller(request: Request, project_id: str):
    try:
        payload = await _json_object(request)
        max_iterations = int(payload.get("max_iterations", 3))
        result = _services(request).generation(project_id).iterate_controller(
            project_id,
            max_iterations=max_iterations,
            expected_revision=_expected_revision(payload),
        )
        return {"status": "ok", "controller": result}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
```

- [ ] **Step 4: Run the API tests**

Run: `./.venv/bin/pytest tests/interface/web/test_vertical_generation_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the API route**

```bash
git add src/rflp_lite/interface/web/resource_api.py tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: expose controller iteration endpoint"
```

### Task 3: Add the safe-iteration action to the Analysis workbench

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Modify: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: current `current_revision` and `/controller/iterate` response.
- Produces: a visible `自动推进安全动作` control and a result block showing iteration status; Trade Study buttons continue using `/controller/execute`.

- [ ] **Step 1: Add a template assertion**

Extend `test_analysis_page_exposes_default_generation_action`:

```python
    assert "自动推进安全动作" in page.text
    assert "/controller/iterate" in page.text
```

- [ ] **Step 2: Add the UI control and JavaScript handler**

In the Controller panel header, place this button before the status badge:

```html
<button class="button compact primary" id="controller-iterate" type="button">自动推进安全动作</button>
```

Add this listener before the existing `.controller-execute` listener:

```javascript
  document.getElementById("controller-iterate")?.addEventListener("click", async () => {
    const output = document.getElementById("controller-result");
    output.hidden = false;
    output.textContent = "Controller 正在自动推进安全动作…";
    try {
      const response = await fetch(`/projects/${encodeURIComponent(projectId)}/controller/iterate`, {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({max_iterations: 3, expected_revision: {{ current_revision|tojson }}}),
      });
      const payload = await response.json();
      output.textContent = JSON.stringify(payload, null, 2);
      output.classList.toggle("warning", payload.status !== "ok");
      if (payload.status === "ok" && payload.controller && payload.controller.revision !== {{ current_revision|tojson }}) {
        window.setTimeout(() => window.location.reload(), 300);
      }
    } catch (error) {
      output.textContent = "请求失败：" + error;
      output.classList.add("warning");
    }
  });
```

- [ ] **Step 3: Run the page/API regression tests**

Run: `./.venv/bin/pytest tests/interface/web/test_vertical_generation_api.py -q`

Expected: PASS, including the pre-existing Trade Study buttons and generation page assertions.

- [ ] **Step 4: Commit the workbench control**

```bash
git add src/rflp_lite/interface/web/templates/analysis.html tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: add controller iteration to analysis workbench"
```

### Task 4: Document, verify, and push the complete iteration slice

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/plans/2026-09-13-controller-iteration-loop.md`

**Interfaces:**
- Consumes: the service/API/UI behavior from Tasks 1–3.
- Produces: documentation that distinguishes automatic safe iteration from user-decided Trade Study and a clean pushed branch.

- [ ] **Step 1: Document the iteration loop**

Add to the product documentation that Controller can automatically execute bounded safe actions, reports each revision/traceability change, and pauses for Trade Study or missing user input/evidence. State that LLM content still flows through the existing structured stage runtime.

- [ ] **Step 2: Mark this plan complete and scan it**

Change implementation checkboxes to `[x]`. Run:

```bash
rg -n 'TODO|TBD|FIXME|Similar to Task|add appropriate' docs/superpowers/plans/2026-09-13-controller-iteration-loop.md | rg -v 'rg -n'
```

Expected: no output.

- [ ] **Step 3: Run complete verification**

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

Expected: every command exits 0; iteration audit events, API route and UI text are covered by tests.

- [ ] **Step 4: Commit and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/README.md docs/superpowers/plans/2026-09-13-controller-iteration-loop.md
git commit -m "docs: record controller iteration loop"
git push origin codex/web-audit-2026-08-18
```
