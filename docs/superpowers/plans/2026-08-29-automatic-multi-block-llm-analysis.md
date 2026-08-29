# 自动多分块 LLM 分析实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 用户提交一次需求后，系统自动用同一个 LLM 完成六个独立分析请求，页面等待全部终态后自动刷新，并修复来源 ID 抄写错误。

**Architecture:** 复用现有 JobService、SQLite JobRepository、lease、metadata 和 CAS。新增一个父分析 Job，内部创建六个可独立查询和重试的 Block Job；现有需求提交、重分析和单块重试路由转发到同一协调器。

**Tech Stack:** Python 3.12、FastAPI、Jinja2、SQLite、urllib、现有 ThreadBackgroundExecutor、pytest。

## Global Constraints

- 同一运行使用当前启用的一个 LLM 档案。
- 默认增量分析，只处理新增或变化来源区域。
- 单块失败不阻断其他块；父任务可为 completed 或 degraded。
- 本地 Ollama 默认并发数为 1。
- 页面等待并自动轮询；不保持最初 POST 的长连接。
- LLM 结果仍是候选结果，不绕过人工确认门禁。
- 不引入 Redis、Celery、外部消息队列或新运行时依赖。
- 非法来源 ID 不得直接写入 Workbench。
- 保留现有 reanalyze、retry-block 和旧 Job 查询兼容行为。

---

### Task 1: 修复来源 ID 语义校验

**Files:**

- Create: src/rflp_lite/application/intelligence/source_references.py
- Modify: src/rflp_lite/application/intelligence/block_schemas.py
- Modify: src/rflp_lite/application/intelligence/analysis_blocks.py
- Modify: src/rflp_lite/application/intelligence/enrichment_jobs.py
- Test: tests/application/intelligence/test_source_references.py
- Test: tests/application/intelligence/test_semantic_validator.py

**Interfaces:**

- Produce allowed_source_region_ids(state) -> tuple[str, ...].
- Produce schema_for(block_id, source_region_ids=()) -> dict[str, object], retaining the current schema when the allow-list is empty.
- Produce repair_source_region_ids(payload, allowed_ids) -> tuple[dict[str, object], dict[str, object] | None].

- [ ] Step 1: Write tests for the exact regression.

    Test that real ID region-306bc6c648e7 is accepted, model typo region-306bc6c6c8e7 is repaired when it is the only allowed ID, and an invalid ID is not guessed when two allowed IDs exist.

- [ ] Step 2: Run the focused tests and verify they fail.

    Run: ./.venv/bin/python -m pytest tests/application/intelligence/test_source_references.py -q
    Expected: FAIL because the guard and dynamic schema do not exist.

- [ ] Step 3: Implement the smallest shared guard.

    Deep-copy the block schema and add an enum containing the current batch IDs to every source_region_ids item schema. Add the allowed IDs to the block prompt. Before semantic validation, repair only the single-source case; for multiple sources return a repair-needed result instead of fuzzy matching. Preserve the original value, replacement, block ID and reason in the repair diagnostic.

- [ ] Step 4: Run focused tests and existing validation tests.

    Run: ./.venv/bin/python -m pytest tests/application/intelligence/test_source_references.py tests/application/intelligence/test_semantic_validator.py -q
    Expected: PASS.

- [ ] Step 5: Commit the isolated change.

    Run: git add src/rflp_lite/application/intelligence/source_references.py src/rflp_lite/application/intelligence/block_schemas.py src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/intelligence/enrichment_jobs.py tests/application/intelligence/test_source_references.py tests/application/intelligence/test_semantic_validator.py && git commit -m "fix: guard llm source region references"

### Task 2: Add parent and block Jobs

**Files:**

- Create: src/rflp_lite/application/intelligence/analysis_coordinator.py
- Modify: src/rflp_lite/application/intelligence/enrichment_jobs.py
- Modify: src/rflp_lite/application/jobs.py only if a small parent heartbeat helper is required
- Test: tests/application/intelligence/test_analysis_coordinator.py
- Test: tests/application/intelligence/test_enrichment_jobs.py

**Interfaces:**

- Create AnalysisCoordinator.submit(model, input_hash, mode, delta_region_ids, snapshot_revision, snapshot_content_revision, analysis_config_hash, idempotency_key=None) -> dict[str, object].
- Create AnalysisCoordinator.retry_failed(parent_job_id, model) -> dict[str, object].
- Create AnalysisCoordinator.submit_block(block_id: str, model: GenerativeModel | None, *, input_hash: str, mode: str, delta_region_ids: tuple[str, ...], snapshot_revision: int, snapshot_content_revision: int, analysis_config_hash: str, parent_job_id: str | None = None) -> dict[str, object].
- Keep EnrichmentJobRunner.run, submit, retry and retry_block as compatibility wrappers or adapt them to the coordinator without changing their public return shape.

- [ ] Step 1: Add failing coordinator tests.

    Use the existing fake model and temporary WebFacade setup. Assert one requirements.analysis parent Job, six requirements.analysis.block child Jobs, child payloads containing parent_job_id and block_id, and deterministic block order.

- [ ] Step 2: Run the new tests to verify the current implementation fails.

    Run: ./.venv/bin/python -m pytest tests/application/intelligence/test_analysis_coordinator.py -q
    Expected: FAIL because no parent/child coordinator exists.

- [ ] Step 3: Extract one-block execution from EnrichmentJobRunner.

    The block runner must build the current snapshot, call one model request, apply SourceReferenceGuard, run JSON/Schema/semantic validation, and commit through the existing CAS path. It must return a terminal block result without creating another parent Job.

- [ ] Step 4: Implement the coordinator with existing JobService.

    Persist the parent first. Run the six child Jobs in order using the existing local executor and a parent heartbeat while a child model request is active. Each child stores block_id, parent_job_id, elapsed time, failure stage, repair metadata and result status. Update the parent after each child; continue after failed or degraded children. Aggregate all child terminal states into completed, degraded, failed, interrupted or superseded.

- [ ] Step 5: Implement idempotency and retry behavior.

    Parent idempotency uses workspace, content revision, input hash, analysis mode and analysis config hash. Child idempotency adds block_id and batch index. retry_failed creates only new child Jobs for failed, degraded or interrupted blocks and preserves successful blocks.

- [ ] Step 6: Run Job tests.

    Run: ./.venv/bin/python -m pytest tests/application/intelligence/test_analysis_coordinator.py tests/application/intelligence/test_enrichment_jobs.py tests/application/intelligence/test_enrichment_lease.py -q
    Expected: PASS.

- [ ] Step 7: Commit the Job layer.

    Run: git add src/rflp_lite/application/intelligence/analysis_coordinator.py src/rflp_lite/application/intelligence/enrichment_jobs.py src/rflp_lite/application/jobs.py tests/application/intelligence/test_analysis_coordinator.py tests/application/intelligence/test_enrichment_jobs.py && git commit -m "feat: split requirements analysis into child jobs"

### Task 3: Wire requirements services and compatibility routes

**Files:**

- Modify: src/rflp_lite/application/use_cases/requirements_analysis.py
- Modify: src/rflp_lite/application/use_cases/reanalyze_requirements.py
- Modify: src/rflp_lite/application/web_facade.py
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/api_v1.py
- Test: tests/application/test_requirements_analysis_service.py
- Test: tests/interface/web/test_requirements_enrichment.py
- Test: tests/interface/web/test_api_v1.py

**Interfaces:**

- RequirementsAnalysisService.analyze continues to save the baseline first and returns the parent run ID.
- WebFacade.reanalyze_all_requirements, retry_requirement_enrichment and retry_requirement_enrichment_block delegate to AnalysisCoordinator.
- Add WebFacade.analysis_run(workspace_name, run_id) -> dict[str, object] | None.
- Add WebFacade.retry_failed_analysis(workspace_name, run_id) -> dict[str, object].

- [ ] Step 1: Extend service tests for the new parent run contract.

    Assert that submitting a new artifact saves accepted baseline data before scheduling, returns an enriching parent Job, and does not enqueue a second run for the same idempotency key.

- [ ] Step 2: Run focused service tests and verify the new assertions fail.

    Run: ./.venv/bin/python -m pytest tests/application/test_requirements_analysis_service.py tests/interface/web/test_requirements_enrichment.py -q
    Expected: FAIL until the service uses AnalysisCoordinator.

- [ ] Step 3: Replace direct EnrichmentJobRunner submission in the three use-case paths.

    Keep the existing input hashing, delta_region_ids, content revision and CAS checks. Change only the scheduling dependency to the coordinator and store parent run_id in auto_analysis.job_id.

- [ ] Step 4: Add the approved Web/API endpoints.

    Add Web and /api/v1 routes for analysis-runs, analysis-runs/{run_id}, analysis/blocks/{block_id}, and analysis-runs/{run_id}/retry-failed. Keep existing reanalyze and retry-block routes as forwarding aliases. Return parent state plus child block summaries, never API keys or raw provider payloads.

- [ ] Step 5: Run service and route tests.

    Run: ./.venv/bin/python -m pytest tests/application/test_requirements_analysis_service.py tests/interface/web/test_requirements_enrichment.py tests/interface/web/test_api_v1.py -q
    Expected: PASS.

- [ ] Step 6: Commit the application/API layer.

    Run: git add src/rflp_lite/application/use_cases/requirements_analysis.py src/rflp_lite/application/use_cases/reanalyze_requirements.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py tests/application/test_requirements_analysis_service.py tests/interface/web/test_requirements_enrichment.py tests/interface/web/test_api_v1.py && git commit -m "feat: expose automatic analysis run endpoints"

### Task 4: Make the requirements page wait and refresh automatically

**Files:**

- Modify: src/rflp_lite/interface/web/presenters.py
- Modify: src/rflp_lite/interface/web/templates/requirements-input.html
- Modify: src/rflp_lite/interface/web/routes.py only if the page context needs the run summary
- Test: tests/interface/web/test_pages.py
- Test: tests/interface/web/test_requirements_enrichment.py

**Interfaces:**

- analysis_blocks_context(state) returns stable block order, public status labels, elapsed time, retryability and diagnostic summaries.
- The page polls the parent run endpoint every 1–2 seconds and reloads only after every child reaches a terminal state.

- [ ] Step 1: Add page tests for waiting and automatic completion.

    Assert that an enriching state renders a waiting message and polling URL, a parent with running children renders progress, and a terminal parent renders the result page without requiring a manual refresh.

- [ ] Step 2: Run focused page tests and verify they fail.

    Run: ./.venv/bin/python -m pytest tests/interface/web/test_pages.py tests/interface/web/test_requirements_enrichment.py -q
    Expected: FAIL until the template and presenter expose parent progress.

- [ ] Step 3: Update the existing requirements page instead of adding a second page.

    Render six modules as queued/running/validating/completed/failed. Disable duplicate submit controls while a run is active. Poll the parent endpoint; update visible progress and navigate to the same requirements page when the parent reaches completed, degraded, failed, interrupted or superseded.

- [ ] Step 4: Add one “重试全部失败项” action.

    Show it only for a terminal degraded/failed/interrupted run. Keep single-block retry behind the existing advanced block details. The action starts one new parent run and returns to the waiting state.

- [ ] Step 5: Run page tests and build checks.

    Run: ./.venv/bin/python -m pytest tests/interface/web/test_pages.py tests/interface/web/test_requirements_enrichment.py -q
    Expected: PASS.

- [ ] Step 6: Commit the UI behavior.

    Run: git add src/rflp_lite/interface/web/presenters.py src/rflp_lite/interface/web/templates/requirements-input.html tests/interface/web/test_pages.py tests/interface/web/test_requirements_enrichment.py && git commit -m "feat: wait for analysis and refresh results"

### Task 5: End-to-end regression and verification

**Files:**

- Modify: tests/e2e/test_cross_workspace_and_partial_failure.py if the parent/child contract needs an end-to-end assertion

- [ ] Step 1: Add one end-to-end fake-model scenario.

    Submit one requirement, wait for the parent Job, assert six child Jobs ran, one injected failure did not block the other five, the parent became degraded, and retry-failed did not rerun successful blocks.

- [ ] Step 2: Add the source-ID regression to the end-to-end path.

    Return region-306bc6c6c8e7 for the single input region region-306bc6c648e7 and assert the committed result uses only the real ID and records source_region_repaired.

- [ ] Step 3: Run the complete verification suite.

    Run: ./.venv/bin/python -m pytest -q
    Run: ./.venv/bin/python scripts/verify_import_contracts.py
    Run: ./.venv/bin/python scripts/verify_schema.py
    Run: ./.venv/bin/python scripts/verify_ruff.py
    Run: ./.venv/bin/python scripts/verify_pyright.py
    Run: ./.venv/bin/python scripts/verify_full.py
    Expected: all checks pass; the optional real Ollama smoke test runs only when explicitly enabled.

- [ ] Step 4: Inspect the final diff and commit only task files.

    Run: git diff --check && git status --short
    Confirm unrelated existing user changes remain unstaged, then commit with:
    git add tests/e2e/test_cross_workspace_and_partial_failure.py && git commit -m "test: verify automatic multi-block analysis"
