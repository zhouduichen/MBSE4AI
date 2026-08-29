# RFLP-Lite Job 与 CAS Bug Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 durable Job、enrichment、Retry 和 Workbench 并发写入中的一致性缺陷，并用回归测试锁定行为。

**Architecture:** 在 Job repository 增加原子 claim/retry-claim 和 lease-owned update；JobService 负责 Worker 执行上下文，SQLite adapter 负责条件更新与 metadata JSON 持久化。所有从已读取 Workbench 推导出的写入使用读取时 revision/content_revision 做 CAS，enrichment 普通异常统一收敛到 Job 与 Workbench 终态。

**Tech Stack:** Python 3、SQLite、pytest、FastAPI application facade、Ruff、Pyright、`scripts/verify_full.py`。

## Global Constraints

- 保留现有 `JobService.submit/submit_async/update/heartbeat/retry` 方法名和 `completed` API 兼容映射。
- SQLite schema 从当前版本 3 可升级；metadata 默认 `{}`。
- 不引入外部队列、第三方依赖或跨工作区共享状态。
- 不重置、删除或覆盖现有未提交文件和附件。
- 每个行为修复必须有回归测试；最终运行完整验证脚本。

---

### Task 1: 扩展 Job contract 与 SQLite schema

**Files:**
- Modify: `src/rflp_lite/ports/jobs.py`
- Modify: `src/rflp_lite/adapters/persistence/migrations.py`
- Modify: `src/rflp_lite/adapters/sqlite_job_repository.py`
- Test: `tests/adapters/test_sqlite_job_repository.py`

**Interfaces:**
- Produce `JobRepositoryPort.claim(job_id: str) -> dict[str, object] | None`。
- Produce `JobRepositoryPort.retry_claim(job_id: str) -> dict[str, object] | None`。
- Extend `update` with optional `expected_lease_id: str | None = None` while accepting existing two-argument calls。
- Preserve all existing record fields and expose persisted metadata at the top level plus `metadata`.

- [ ] **Step 1: Write failing repository tests**

```python
def test_claim_is_single_winner(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")
    queued = repository.submit("demo", {})
    first = repository.claim(str(queued["id"]))
    second = repository.claim(str(queued["id"]))
    assert first is not None
    assert second is None
    assert first["status"] == "running"
    repository.close()


def test_owned_update_rejects_old_lease_after_recovery(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db", lease_seconds=1)
    queued = repository.submit("demo", {})
    running = repository.claim(str(queued["id"]))
    assert running is not None
    repository.recover_startup(float(running["lease_expires_at"]) + 1)
    assert repository.update(str(queued["id"]), {"status": "succeeded"}, expected_lease_id=str(running["lease_id"])) is None
    assert repository.get(str(queued["id"]))["status"] == "interrupted"
    repository.close()


def test_job_metadata_round_trips(tmp_path: Path) -> None:
    repository = SQLiteJobRepository(tmp_path / "model.db")
    queued = repository.submit("demo", {})
    updated = repository.update(str(queued["id"]), {"retryable": True, "active_block": "requirements", "source_total": 3, "batch_index": 1})
    assert updated["retryable"] is True
    assert updated["active_block"] == "requirements"
    assert updated["metadata"]["source_total"] == 3
    repository.close()
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./.venv/bin/pytest tests/adapters/test_sqlite_job_repository.py -q`

Expected: FAIL because schema metadata and atomic claim methods do not exist.

- [ ] **Step 3: Add migration version 4 and repository primitives**

Add `metadata TEXT NOT NULL DEFAULT '{}'` to a new migration, decode it in `_record`, merge declared runtime fields into metadata in `update`, and implement claim with:

```sql
UPDATE jobs
SET status = 'running', attempt = attempt + 1, lease_id = ?,
    lease_expires_at = ?, heartbeat_at = ?, updated_at = ?
WHERE id = ? AND status = 'queued'
```

Implement `retry_claim` with the same transaction and `WHERE status IN ('failed', 'degraded', 'interrupted')`. Implement `expected_lease_id` by adding `AND status = 'running' AND lease_id = ?` to the job update and return `None` when `rowcount != 1`. Clear lease fields during startup recovery.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `./.venv/bin/pytest tests/adapters/test_sqlite_job_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Run migration compatibility tests**

Run: `./.venv/bin/pytest tests/application/test_jobs_migration.py tests/adapters/test_sqlite_job_repository.py -q`

Expected: PASS with old legacy imports unchanged.

### Task 2: Make JobService execution and retry single-owner

**Files:**
- Modify: `src/rflp_lite/application/jobs.py`
- Modify: `src/rflp_lite/ports/jobs.py`
- Test: `tests/application/test_jobs.py`
- Test: `tests/application/test_jobs_recovery.py`

**Interfaces:**
- `JobService.update(job_id, patch)` remains public and delegates normally outside Worker execution.
- Worker execution sets a private thread-local `(job_id, lease_id)` context; `update` automatically forwards `expected_lease_id` for that Job.
- `JobService.retry` atomically claims the retry before calling the runner.

- [ ] **Step 1: Add failing concurrency and contract tests**

```python
def test_concurrent_async_idempotent_submit_runs_once(tmp_path: Path) -> None:
    service = JobService(tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls = {"count": 0}
    lock = threading.Lock()

    def runner():
        with lock:
            calls["count"] += 1
        started.set()
        release.wait(2)
        return {"status": "succeeded"}

    results = []
    threads = [threading.Thread(target=lambda: results.append(service.submit_async("demo", {"idempotency_key": "same"}, runner))) for _ in range(2)]
    for thread in threads: thread.start()
    assert started.wait(2)
    release.set()
    for thread in threads: thread.join(3)
    assert calls["count"] == 1
    assert len({item["id"] for item in results}) == 1


def test_concurrent_retry_runs_once(tmp_path: Path) -> None:
    service = JobService(tmp_path)
    with pytest.raises(RuntimeError):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(RuntimeError("first")))
    job_id = str(service.list()[0]["id"])
    entered = threading.Event()
    release = threading.Event()
    calls = {"count": 0}
    lock = threading.Lock()

    def runner():
        with lock:
            calls["count"] += 1
        entered.set()
        release.wait(2)
        return {"status": "succeeded"}

    results, errors = [], []
    def retry():
        try: results.append(service.retry(job_id, runner))
        except ValueError as exc: errors.append(str(exc))
    threads = [threading.Thread(target=retry) for _ in range(2)]
    for thread in threads: thread.start()
    assert entered.wait(2)
    release.set()
    for thread in threads: thread.join(3)
    assert calls["count"] == 1
    assert len(errors) == 1


def test_retry_rejects_non_object_result(tmp_path: Path) -> None:
    service = JobService(tmp_path)
    with pytest.raises(RuntimeError):
        service.submit("demo", {}, lambda: (_ for _ in ()).throw(RuntimeError("first")))
    job_id = str(service.list()[0]["id"])
    result = service.retry(job_id, lambda: ["invalid"])
    assert result["status"] == "failed"
    assert result["error"]["type"] == "TypeError"
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/test_jobs.py tests/application/test_jobs_recovery.py -q`

Expected: the new concurrency and non-object retry tests fail.

- [ ] **Step 3: Implement claim-aware submit, Worker context, and retry**

In `submit_async`, submit the record, call `repository.claim(job_id)`, and schedule only when claim succeeds. In the Worker, keep the claimed lease in thread-local storage, clear it in `finally`, and make terminal/error updates conditional on that lease. In `retry`, call `retry_claim` before runner execution, return a `ValueError` for a lost claim, and validate `result` as a dict before choosing the final status.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `./.venv/bin/pytest tests/application/test_jobs.py tests/application/test_jobs_recovery.py -q`

Expected: PASS.

### Task 3: Close enrichment error and retry boundaries

**Files:**
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/application/use_cases/requirements_analysis.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Test: `tests/application/intelligence/test_enrichment_jobs.py`
- Test: `tests/application/test_requirements_analysis_service.py`

**Interfaces:**
- Enrichment block errors of type `Exception` become failed/degraded diagnostics and terminal aggregate state.
- Retry accepts only `requirements.enrichment` Jobs in `failed/degraded/interrupted` state.
- Process-level `KeyboardInterrupt` and `SystemExit` are not converted into business failure.

- [ ] **Step 1: Add failing enrichment tests**

```python
def test_unclassified_model_error_finalizes_workbench(tmp_path: Path) -> None:
    class RuntimeErrorModel:
        model_id = "runtime-error"
        def complete_json(self, request):
            raise RuntimeError("provider socket broke")

    runner = _runner(tmp_path)
    queued = runner.submit(RuntimeErrorModel(), input_hash=runner._input_hash(runner._load_state()))
    job = _wait(runner, str(queued["id"]))
    state = runner._load_state()
    assert job["status"] in {"failed", "degraded"}
    assert state["auto_analysis"]["status"] in {"failed", "degraded"}


def test_retry_rejects_completed_and_wrong_kind_jobs(tmp_path: Path) -> None:
    for job_id, kind in (("completed-job", "requirements.enrichment"), ("scenario-job", "scenario.execute")):
        service, workspace, _repository, _runner = _service(
            tmp_path,
            job_result={"id": "new-job", "status": "queued", "blocks": {}},
            previous={"id": job_id, "kind": kind, "status": "succeeded"},
        )
        with pytest.raises(ContractViolation):
            service.retry(workspace, job_id)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/intelligence/test_enrichment_jobs.py tests/application/test_requirements_analysis_service.py -q`

Expected: the new error-finalization and retry-boundary tests fail.

- [ ] **Step 3: Implement exception finalization and retry validation**

Add a final `except Exception` block beside the existing block-specific catches, record `llm_block_failed` diagnostics, and let the normal terminal aggregation persist `auto_analysis`. Wrap pre-loop enrichment failures in the submit execution closure with a best-effort Workbench terminal update. Validate `kind` and status in both `RequirementsAnalysisService.retry/retry_block` and `EnrichmentJobRunner.retry/retry_block` before creating a new Job.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `./.venv/bin/pytest tests/application/intelligence/test_enrichment_jobs.py tests/application/test_requirements_analysis_service.py -q`

Expected: PASS.

### Task 4: Apply CAS to all stale-state Workbench writes

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/application/use_cases/requirements_analysis.py`
- Modify: `src/rflp_lite/application/use_cases/project_analysis.py`
- Modify: `src/rflp_lite/interface/cli.py`
- Test: `tests/application/test_web_facade.py`
- Test: `tests/application/test_project_analysis_service.py`
- Test: `tests/application/test_requirements_analysis_service.py`
- Test: `tests/application/workbench/test_concurrency.py`

**Interfaces:**
- Every write derived from a loaded state passes that state’s expected revision and content revision.
- CAS conflicts propagate as `ConcurrentModificationError`; no stale fallback save is allowed.

- [ ] **Step 1: Add a failing WebFacade TOCTOU test**

```python
def test_save_requirements_rejects_state_stale_before_cas_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "model.db"
    first = SQLiteRepository(database)
    first.save_workbench(empty_workbench(), expected_revision=0, expected_content_revision=0)
    stale_state = first.load_workbench()
    concurrent_state = {**stale_state, "label": "concurrent"}
    first.save_workbench(concurrent_state, expected_revision=1, expected_content_revision=0)
    stale_state["label"] = "stale"
    dummy = _facade_with_repository_hook(database, stale_state)
    with pytest.raises(ConcurrentModificationError):
        WebFacade._save_requirements(dummy, "demo", stale_state, "requirements.edited")
    first.close()
```

- [ ] **Step 2: Run the focused concurrency tests and verify the new test fails**

Run: `./.venv/bin/pytest tests/application/test_web_facade.py tests/application/test_project_analysis_service.py tests/application/workbench/test_concurrency.py -q`

Expected: the TOCTOU test fails because `_save_requirements` re-reads the latest revision.

- [ ] **Step 3: Replace late snapshot baselines with loaded-state revisions**

Use `state.get("revision", 0)` and `state.get("content_revision", state.get("revision", 0))` as expected values in `_save_requirements`, including the baseline branch. Capture the original state revisions in `_save_initial` and `ProjectAnalysisService.analyze`. Apply the same expected values to WebFacade baseline/verify/test and CLI Workbench writes, including scope/migration writes.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `./.venv/bin/pytest tests/application/test_web_facade.py tests/application/test_project_analysis_service.py tests/application/test_requirements_analysis_service.py tests/application/workbench/test_concurrency.py -q`

Expected: PASS, with concurrent stale saves rejected.

### Task 5: Full regression and quality gates

**Files:**
- Modify only files required by Tasks 1-4.
- Test: existing repository, application, interface, and e2e suites.

- [ ] **Step 1: Run targeted regression suites**

Run: `./.venv/bin/pytest tests/adapters/test_sqlite_job_repository.py tests/application/test_jobs.py tests/application/test_jobs_recovery.py tests/application/intelligence/test_enrichment_jobs.py tests/application/test_requirements_analysis_service.py tests/application/test_web_facade.py tests/application/workbench/test_concurrency.py -q`

Expected: PASS.

- [ ] **Step 2: Run static and architecture gates**

Run: `./.venv/bin/python scripts/architecture_metrics.py && ./.venv/bin/python -m lint_imports src && ./.venv/bin/ruff check src tests && ./.venv/bin/pyright`

Expected: no lint-imports broken edges, Ruff clean, Pyright has no errors.

- [ ] **Step 3: Run the complete verifier and build**

Run: `RFLP_VERIFY_TIMEOUT_SECONDS=180 ./.venv/bin/python scripts/verify_full.py`

Expected: all tests, schema checks, static checks, and build pass.

- [ ] **Step 4: Review final diff and preserve unrelated changes**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; existing unrelated modifications and untracked attachments remain untouched.
