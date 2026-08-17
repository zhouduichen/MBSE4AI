# 增量 LLM 分析与可靠输出实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让本地 4B 模型以小块、可校验、可重试的方式补充需求分析，提交后先返回已接受的规则/领域包结果，避免一次 JSON 不完整导致整页无结果。

**Architecture:** 保留 `GenerationRequest`/`OpenAICompatibleModel` 作为模型适配边界，新增分析块目录和局部合并器。需求提交先执行确定性 `baseline_ready` 阶段并保存 workbench，再通过本地单进程后台 worker 执行独立分析块；每块成功、失败或降级都写入持久化 job 和 workbench 诊断。Web 端轮询已有 job JSON 端点展示部分结果和失败块。

**Tech Stack:** Python 3.11+, urllib, Ollama native `/api/chat`, OpenAI-compatible JSON Schema, FastAPI/Jinja2, JSON workbench state, pytest。

## Global Constraints

- 用户明确输入、规则结果和领域包种子提交即为 `accepted`；不因 LLM 失败进入空白或阻塞状态。
- Ollama 本地模型默认使用 `think: false`，并以每块预算限制 `num_predict`。
- 每个块只生成有限数量的项；块失败只影响该块，不清空已完成块。
- 每块最多一次短 JSON 修复；修复失败必须进入 `degraded`，不能把空数组标记为成功。
- 不新增第三方任务队列；本轮使用本地单进程 worker 和现有 `.rflp/jobs.json`。
- 同一输入、包组合、块版本和模型的重复请求必须幂等，不得重复添加候选。
- 4B、截断 JSON、空响应、非法来源引用和 Ollama 错误必须有自动化测试。

---

### Task 1: 把默认接受与规则基线从 LLM 成功条件中解耦

**Files:**
- Modify: `src/rflp_lite/application/requirements_workbench.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Test: `tests/application/test_requirements_workbench.py`
- Modify: `tests/interface/web/test_auto_requirements.py`

**Interfaces:**
- Consumes: existing `analyze_artifact`, `merge_artifact`, `confirm_requirements`, `sync_review_queue`。
- Produces: `accept_initial_workbench(state) -> dict[str, object]` and `auto_analysis.status == "baseline_ready"` before any LLM call.

- [ ] **Step 1: Write failing tests**

```python
def test_new_submission_is_accepted_without_llm():
    state = initialize_review_state(analyze_artifact("requirements.txt", "系统应支持备份。".encode()))
    assert all(item["status"] == "accepted" for item in state["claims"])
    assert all(item["status"] == "accepted" for item in state["structured_requirements"])
    assert state["review_queue"] == []

def test_llm_failure_keeps_baseline_visible():
    facade = build_test_facade(model=FailingModel())
    state = facade.analyze_requirements("demo", "requirements.txt", b"系统应支持备份。")
    assert state["auto_analysis"]["status"] in {"baseline_ready", "degraded"}
    assert state["claims"]
```

The test module must provide `build_test_facade(model)` with an isolated temporary
workspace and an injected model; `FailingModel` raises the same adapter failure
used by the production runner. This keeps the assertion independent of a live
Ollama process.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/test_requirements_workbench.py tests/interface/web/test_auto_requirements.py`

Expected: FAIL because initial candidates currently enter `review_queue` and analysis status depends on LLM completion.

- [ ] **Step 3: Implement baseline acceptance**

Make `initialize_review_state` and the new-artifact branch of `merge_artifact` call `confirm_requirements` for rule/explicit/pack items before creating `change_set`. Keep user-edited and explicit implicit-constraint suggestion routes reviewable.

- [ ] **Step 4: Save before model analysis**

Refactor `WebFacade.analyze_requirements` into `_save_baseline_requirements` followed by `_enqueue_enrichment`; it must return after SQLite workbench persistence and never wait for `complete_json`.

- [ ] **Step 5: Run focused tests and verify pass**

Run: `./.venv/bin/python -m pytest -q tests/application/test_requirements_workbench.py tests/interface/web/test_auto_requirements.py`

Expected: PASS; the existing tests that assert `waiting_for_llm` are updated to assert `baseline_ready` plus a job record.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/requirements_workbench.py src/rflp_lite/application/web_facade.py tests/application/test_requirements_workbench.py tests/interface/web/test_auto_requirements.py
git commit -m "feat: return accepted requirement baseline before llm"
```

### Task 2: Define bounded analysis blocks and schemas

**Files:**
- Create: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/intelligence/project_analysis.py`
- Test: `tests/application/intelligence/test_analysis_blocks.py`
- Modify: `tests/application/intelligence/test_project_analysis.py`

**Interfaces:**
- Consumes: composed pack guidance from the domain-pack plan and current workbench state.
- Produces:
  - `AnalysisBlock(id, max_items, max_tokens, response_schema)`;
  - `build_analysis_blocks(state, composed_pack) -> tuple[AnalysisBlock, ...]`;
  - `build_block_request(state, block, composed_pack) -> GenerationRequest`;
  - `merge_block_result(state, block_id, response) -> dict[str, object]`.

- [ ] **Step 1: Write bounded block tests**

```python
def test_build_blocks_has_bounded_output_contract():
    blocks = build_analysis_blocks(make_workbench_fixture(), make_composed_pack_fixture())
    assert [item.id for item in blocks] == [
        "system_scope", "stakeholders", "concerns_needs",
        "requirements", "scenarios", "architecture",
    ]
    assert all(item.max_items > 0 and item.max_tokens <= 1600 for item in blocks)

def test_block_request_contains_only_block_scope():
    request = build_block_request(
        make_workbench_fixture(), make_stakeholder_block(), make_composed_pack_fixture()
    )
    assert request.max_tokens == 1200
    assert "stakeholders" in request.user_payload["task"]
    assert "architecture" not in request.user_payload["task"]
```

The test module provides the three small fixtures named above. They return a
minimal valid workbench, the catalog's `stakeholders` block, and a composed pack
with one source pack per required guidance field.

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/intelligence/test_analysis_blocks.py tests/application/intelligence/test_project_analysis.py`

Expected: FAIL because the block catalog and block-specific request builders do not exist.

- [ ] **Step 3: Implement the block catalog**

Create explicit blocks with these budgets: `system_scope=500`, `stakeholders=1200`, `concerns_needs=1400`, `requirements=1600`, `scenarios=1400`, and `architecture=1600`. Put `max_items` in the block object and make every response schema require an object envelope with an `items` array and `diagnostics` array.

- [ ] **Step 4: Implement block-specific payloads**

Include only source regions, accepted current requirements, relevant pack slices, and the block task. Do not send the full response schema or all pack content to every block. Include `input_hash`, `pack_hashes`, `block_id`, and `limits` in the payload.

- [ ] **Step 5: Implement deterministic merge**

Use the existing stable ID strategy with `(workspace, input_hash, block_id, raw_id, label)`. Merge only `producer=llm` items belonging to the current input hash; preserve rule, domain-pack, manual, and prior accepted items. Reject relationships pointing to IDs not present in the merged graph.

- [ ] **Step 6: Run focused tests and verify pass**

Run: `./.venv/bin/python -m pytest -q tests/application/intelligence/test_analysis_blocks.py tests/application/intelligence/test_project_analysis.py`

Expected: PASS, including stable hashes and no cross-block duplicate IDs.

- [ ] **Step 7: Commit**

```bash
git add src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/intelligence/project_analysis.py tests/application/intelligence/test_analysis_blocks.py tests/application/intelligence/test_project_analysis.py
git commit -m "feat: add bounded requirement analysis blocks"
```

### Task 3: Harden local structured JSON completion

**Files:**
- Modify: `src/rflp_lite/adapters/llm_client.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Modify: `src/rflp_lite/ports/generative_model.py`
- Test: `tests/adapters/test_llm_client.py`
- Modify: `tests/adapters/test_openai_compatible_model.py`

**Interfaces:**
- Consumes: `AnalysisBlock.max_tokens` and local profile `local_max_tokens`.
- Produces: validated `GenerationResponse` with `repaired`, `duration_ms`, `status`, and provider diagnostics without changing existing callers.

- [ ] **Step 1: Add failure fixtures**

Test native Ollama responses for valid object JSON, fenced JSON, empty content, truncated JSON, schema-invalid JSON, and a response with `thinking` content separated from `message.content`.

- [ ] **Step 2: Run adapter tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/adapters/test_llm_client.py tests/adapters/test_openai_compatible_model.py`

Expected: FAIL on the new empty/truncated/schema-invalid behavior.

- [ ] **Step 3: Apply per-call local limits**

In `chat_completion`, keep native Ollama `think: false`, pass the block’s `max_tokens` as `options.num_predict`, and pass the supplied JSON schema as `format`. Never raise the global local cap above the request’s block budget.

- [ ] **Step 4: Add strict parse and one short repair**

Reject empty content before JSON extraction. For a repair, send only the original block envelope, the invalid response, and a message such as `只修复 JSON 结构，最多返回 N 项，不要解释；缺失内容返回空数组` instead of resending the full project context. If repair fails, raise `AdapterFailure` with a stable diagnostic code.

- [ ] **Step 5: Run adapter tests and verify pass**

Run: `./.venv/bin/python -m pytest -q tests/adapters/test_llm_client.py tests/adapters/test_openai_compatible_model.py`

Expected: PASS; truncated and empty responses produce a handled adapter failure, never a false success.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/adapters/llm_client.py src/rflp_lite/adapters/openai_compatible_model.py src/rflp_lite/ports/generative_model.py tests/adapters/test_llm_client.py tests/adapters/test_openai_compatible_model.py
git commit -m "feat: harden structured local llm output"
```

### Task 4: Add durable per-block enrichment jobs

**Files:**
- Modify: `src/rflp_lite/application/jobs.py`
- Create: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Test: `tests/application/test_jobs.py`
- Test: `tests/application/intelligence/test_enrichment_jobs.py`

**Interfaces:**
- Consumes: baseline workbench, bounded block functions, `LLMProfileService.active_config`.
- Produces:
  - `submit_requirement_enrichment(workspace_name, input_hash) -> dict[str, object]`;
  - `EnrichmentJobRunner.run(workspace_path, model, *, input_hash=None) -> dict[str, object]`;
  - `EnrichmentJobRunner.retry(workspace_path, job_id, model) -> dict[str, object]`;
  - per-block status records in `.rflp/jobs.json`;
  - idempotent merge into SQLite workbench.

- [ ] **Step 1: Write job lifecycle tests**

```python
def test_enrichment_job_persists_each_block_status(tmp_path, fake_model):
    runner = EnrichmentJobRunner(tmp_path)
    job = runner.run(fake_model)
    assert job["status"] == "degraded"
    assert job["blocks"]["stakeholders"] == "succeeded"
    assert job["blocks"]["requirements"] == "failed"
    assert job["blocks"]["scenarios"] == "degraded"

def test_retry_does_not_duplicate_successful_block(tmp_path, fake_model):
    runner = EnrichmentJobRunner(tmp_path)
    first = runner.run(fake_model)
    second = runner.retry(first["id"], fake_model)
    assert second["merged_item_ids"] == sorted(set(second["merged_item_ids"]))
```

`fake_model` is a deterministic test double whose response map marks
`stakeholders` successful, `requirements` failed, and `scenarios` degraded; it
also records each `(block_id, input_hash)` call so retry assertions can verify
that successful blocks are skipped.

- [ ] **Step 2: Run job tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/test_jobs.py tests/application/intelligence/test_enrichment_jobs.py`

Expected: FAIL because jobs currently execute one synchronous runner and have no block state.

- [ ] **Step 3: Extend the job record**

Add `blocks`, `model`, `pack_ids`, `input_hash`, `started_at`, `updated_at`, and `retryable` fields. Keep atomic JSON replacement. Add a per-path lock so the worker and Web reader never write the same job record concurrently.

- [ ] **Step 4: Implement the local worker**

Use a single `ThreadPoolExecutor(max_workers=1)` owned by `EnrichmentJobRunner`. Each block opens its own `SQLiteRepository`, loads the current workbench, verifies the input hash, calls `complete_json`, validates/merges, saves a revision, and updates its job state. A failed block does not raise out of the entire job.

- [ ] **Step 5: Implement retry and restart recovery**

On service startup, jobs with `status=running` become `status=retryable` if their block records have no terminal success; completed block IDs are skipped. `EnrichmentJobRunner.retry` creates no duplicate block record and reuses the same idempotency key.

- [ ] **Step 6: Run job tests and verify pass**

Run: `./.venv/bin/python -m pytest -q tests/application/test_jobs.py tests/application/intelligence/test_enrichment_jobs.py`

Expected: PASS, including failure isolation and restart-safe retry.

- [ ] **Step 7: Commit**

```bash
git add src/rflp_lite/application/jobs.py src/rflp_lite/application/intelligence/enrichment_jobs.py src/rflp_lite/application/web_facade.py tests/application/test_jobs.py tests/application/intelligence/test_enrichment_jobs.py
git commit -m "feat: run requirement llm enrichment in durable block jobs"
```

### Task 5: Wire the Web flow to baseline-first analysis

**Files:**
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_auto_requirements.py`
- Test: `tests/interface/web/test_requirements_enrichment.py`

**Interfaces:**
- Consumes: baseline status and enrichment job API from Tasks 1 and 4.
- Produces: immediate redirect after submit, job ID in workbench state, JSON status endpoint, visible partial results and retry action.

- [ ] **Step 1: Add route tests**

Assert that `POST /w/{workspace}/requirements/analyze` returns `303` without waiting for LLM, the redirected page contains accepted rule requirements, and `/w/{workspace}/jobs/{job_id}.json` reports block statuses.

- [ ] **Step 2: Run route tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_auto_requirements.py tests/interface/web/test_requirements_enrichment.py`

Expected: FAIL because the analyze route currently waits for `_auto_complete_requirements`.

- [ ] **Step 3: Wire the route and API**

Store `auto_analysis={"status":"baseline_ready","job_id": job_id, "blocks": ...}` before redirect. Keep the existing job JSON route and add `POST /api/v1/workspaces/{workspace}/requirements/enrichment/{job_id}/retry` for failed blocks.

- [ ] **Step 4: Add progressive UI status**

Render `baseline_ready`, `enriching`, `completed`, and `degraded` as distinct states. Add a small polling script that fetches the job JSON every 2 seconds while a job is active; update block labels and stop polling on a terminal status. The page must show links to requirements, stakeholders, scenarios, and graph even when enrichment fails.

- [ ] **Step 5: Run route and template tests**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_auto_requirements.py tests/interface/web/test_requirements_enrichment.py tests/interface/web/test_pages.py`

Expected: PASS with the existing page navigation and status classes intact.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/templates/requirements-input.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_auto_requirements.py tests/interface/web/test_requirements_enrichment.py
git commit -m "feat: show baseline and incremental llm enrichment status"
```

### Task 6: Verify end-to-end behavior with the 4B model and failure fixtures

**Files:**
- Create: `tests/fixtures/llm/truncated-project-analysis.json`
- Create: `tests/fixtures/llm/empty-project-analysis.json`
- Modify: `tests/e2e/test_intelligent_discovery.py`
- Create: `tests/e2e/test_incremental_requirements.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: composed packs, baseline-first flow, enrichment jobs, and strict adapter behavior from Tasks 1–5.
- Produces: regression coverage and documented local 4B setup.

- [ ] **Step 1: Add deterministic fake-model fixtures**

Use one valid block response, one truncated response, and one empty response. The fake model must record `(block_id, max_tokens, input_hash)` so tests can assert that only failed blocks retry.

- [ ] **Step 2: Add end-to-end assertions**

Assert that a two-line requirements submission immediately contains accepted claims, a failed requirements block leaves stakeholders and scenarios visible, retry changes only that block, and a completed 4B run contains no duplicate IDs.

- [ ] **Step 3: Run the focused end-to-end tests**

Run: `./.venv/bin/python -m pytest -q tests/e2e/test_incremental_requirements.py tests/e2e/test_intelligent_discovery.py`

Expected: PASS without requiring a live Ollama service.

- [ ] **Step 4: Run a live 4B smoke test**

Add this opt-in test to `tests/e2e/test_incremental_requirements.py`:

```python
@pytest.mark.live
def test_live_qwen35_4b_enrichment(tmp_path):
    if not ollama_has_model("qwen3.5:4b"):
        pytest.skip("qwen3.5:4b is not installed")
    result = run_live_enrichment(tmp_path, model="qwen3.5:4b")
    assert result["status"] in {"completed", "degraded"}
    assert result["model"] == "qwen3.5:4b"
```

The test helpers use the real local profile and a temporary workspace; they do
not call a remote provider.

Run:

```bash
ollama list
./.venv/bin/python -m pytest -q tests/e2e/test_incremental_requirements.py -k live --maxfail=1
```

Expected: the live test is skipped when `qwen3.5:4b` is absent and otherwise records each block’s duration, model ID, and final `completed` or `degraded` status.

- [ ] **Step 5: Update documentation**

Document that submit returns the accepted baseline immediately, model enrichment is incremental, and a failed block can be retried without re-running successful blocks. Include the `qwen3.5:4b` profile name and the 4B/9B tradeoff without claiming formal engineering validity.

- [ ] **Step 6: Run the full relevant suite**

Run: `./.venv/bin/python -m pytest -q tests/application tests/adapters tests/interface/web tests/e2e`

Expected: PASS; existing discovery and local Web behavior remain compatible.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/llm tests/e2e/test_intelligent_discovery.py tests/e2e/test_incremental_requirements.py README.md
git commit -m "test: verify incremental llm analysis with local 4b"
```
