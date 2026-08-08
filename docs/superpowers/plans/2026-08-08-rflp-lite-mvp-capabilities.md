# RFLP Lite MVP Capabilities Implementation Plan

> **For agentic workers:** Execute this plan inline, task-by-task, with a test checkpoint after each task.

**Goal:** Turn the remaining local capability placeholders into small, validated, executable paths that can later be replaced by external adapters.

**Architecture:** Keep application services independent from transport and storage. Scenario execution and jobs are deterministic local services; profile, exchange, tracking, API, and plugin features wrap existing facades and repositories. Unconfigured external services remain explicit non-success states.

**Tech Stack:** Python 3.12, dataclasses, existing SQLite repository, FastAPI/Starlette routes, pytest, JSON fixtures.

## Global Constraints

- No new mandatory third-party runtime dependency.
- Every result is structured and deterministic except generated timestamps.
- No arbitrary code execution for scenario steps or plugins.
- Preserve the current CLI, Web UI, tests, and untracked user documents.
- Do not mark an external capability available unless a local executable path exists.

### Task 1: Deterministic scenario execution

**Files:**
- Create: `src/rflp_lite/application/scenario_execution.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements.html`
- Create: `tests/application/test_scenario_execution.py`
- Modify: `tests/interface/web/test_pages.py`

**Interface:** `execute_scenario(state, scenario_id, *, run_id=None) -> dict` returns `status`, `scenario_id`, `run_id`, `events`, `assertions`, and `evidence`; it consumes only the stored structured scenario and never evaluates step text as code.

- [ ] Add tests for a passing scenario, an injected fault, and unknown scenario ID.
- [ ] Implement deterministic step/fault events, expected-outcome assertions, stable result hash, and explicit failed status.
- [ ] Add facade, JSON endpoint, and a Web action/result section.
- [ ] Run focused tests and then the full suite.

### Task 2: Persistent local job status

**Files:**
- Create: `src/rflp_lite/application/jobs.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Create: `tests/application/test_jobs.py`

**Interface:** `JobService.submit(kind, payload, runner) -> dict` and `JobService.get(job_id) -> dict | None`; synchronous execution is recorded as `queued`, `running`, then `succeeded` or `failed`.

- [ ] Test lifecycle, failure retention, and unknown job.
- [ ] Implement a JSON-backed repository under the workspace state directory with atomic writes.
- [ ] Expose job status JSON and wrap scenario execution through it.
- [ ] Run focused tests.

### Task 3: Profile / Pack editor and local run export

**Files:**
- Create: `src/rflp_lite/application/profile_packs.py`
- Modify: `src/rflp_lite/governance/profile.py`
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Create: `tests/application/test_profile_packs.py`

**Interface:** `validate_profile_payload(payload) -> dict`, `save_profile(workspace, payload) -> dict`, and `export_run_record(record) -> dict` reuse existing schema and run-manifest conventions.

- [ ] Test valid profile, invalid profile, and export shape.
- [ ] Implement schema-backed save/load/export without changing solver semantics.
- [ ] Add CLI JSON commands and a minimal Web JSON endpoint.
- [ ] Run focused tests and profile schema validation.

### Task 4: RFLP SysML-lite interchange

**Files:**
- Create: `src/rflp_lite/application/interchange.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Create: `tests/application/test_interchange.py`

**Interface:** `export_rflp(model) -> dict` and `import_rflp(payload) -> dict` preserve element IDs, layers, names, kinds, and relations; malformed payloads fail with domain validation errors.

- [ ] Test round-trip and malformed input.
- [ ] Implement a versioned JSON interchange envelope named `sysml-lite/rflp`.
- [ ] Add import/export JSON endpoints.
- [ ] Run focused tests.

### Task 5: Versioned local JSON API

**Files:**
- Create: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/app.py`
- Create: `tests/interface/web/test_api_v1.py`

**Interface:** `/api/v1/workspaces/{workspace}/requirements`, `/scenarios`, `/scenarios/{id}/execute`, and `/jobs/{id}` return structured JSON and reuse the facade.

- [ ] Test reads, scenario execution, and validation errors through the ASGI app.
- [ ] Implement only local workspace-scoped endpoints; no auth claim is made.
- [ ] Run API tests and full suite.

### Task 6: Local plugin registry and capability truthfulness

**Files:**
- Create: `src/rflp_lite/application/plugins.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Create: `tests/application/test_plugins.py`

**Interface:** `register_plugin(name, handler)`, `list_plugins()`, and `invoke_plugin(name, payload)` allow only registered in-process handlers with structured results.

- [ ] Test registration, discovery, unknown plugin, and exception result.
- [ ] Implement a small registry with built-in scenario runner metadata only.
- [ ] Mark local MVP capabilities available and leave external-only capabilities explicitly not configured.
- [ ] Run the full verification set and inspect the final diff.
