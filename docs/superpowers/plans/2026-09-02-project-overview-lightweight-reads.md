# Project Overview Lightweight Reads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ] syntax) for tracking.

**Goal:** Make GET / render all managed projects from lightweight SQLite summaries and load each project's full requirements only when its card is expanded.

**Architecture:** Add a single-row workbench_summary table maintained atomically by SQLiteRepository.save_workbench(). The project-management page reads only workspace metadata and this summary; a separate HTMX detail endpoint loads one full Workbench on demand and returns the existing project-card body markup. Legacy Workbenches without a summary remain usable and never get parsed by the overview request.

**Tech Stack:** Python 3.11+, SQLite, FastAPI, Jinja2, HTMX, pytest.

## Global Constraints

- Do not parse workbench.payload from the project-management overview request.
- Do not backfill legacy Workbench summaries during SQLite migration.
- Keep project cards collapsed by default and preserve existing project/requirement links.
- Keep Workbench and its summary in the same SQLite transaction.
- Preserve unrelated user changes in the dirty worktree.
- Do not modify or delete existing workspace data, including workspaces/public-real-v1.

---

### Task 1: Add atomic lightweight Workbench summaries

**Files:**
- Modify: src/rflp_lite/adapters/persistence/migrations.py
- Modify: src/rflp_lite/adapters/sqlite_repository.py
- Modify: src/rflp_lite/ports/repositories.py
- Test: tests/adapters/test_sqlite_repository.py (create if absent)

**Interfaces:**
- Produce SQLiteRepository.load_workbench_summary() -> dict[str, object] | None.
- Expose the same method on WorkbenchRepositoryPort.
- A summary contains revision, content_revision, requirement_count, accepted_count, model_state, and updated_at.

- [ ] Write failing repository tests that save empty, draft, and formal Workbench states and assert summary counts/status; also assert a legacy Workbench row without a summary returns None.
- [ ] Run .venv/bin/python -m pytest tests/adapters/test_sqlite_repository.py -q and confirm the new method/tests fail.
- [ ] Add migration version 6 creating workbench_summary with columns id, revision, content_revision, requirement_count, accepted_count, model_state, and updated_at. Do not backfill.
- [ ] In save_workbench(), after the Workbench row write succeeds, compute summary values from the already parsed payload and upsert id=current before the existing transaction exits. Use model state formal when rflp is present and draft is absent, draft when draft is present, otherwise 未生成.
- [ ] Implement load_workbench_summary() with a SELECT from workbench_summary only; it must return None when absent and never select workbench.payload.
- [ ] Add the protocol method and run the focused repository tests until they pass.
- [ ] Commit with: git add src/rflp_lite/adapters/persistence/migrations.py src/rflp_lite/adapters/sqlite_repository.py src/rflp_lite/ports/repositories.py tests/adapters/test_sqlite_repository.py && git commit -m "feat: persist lightweight workbench summaries"

### Task 2: Make project summaries payload-free

**Files:**
- Modify: src/rflp_lite/application/web_facade.py
- Test: tests/application/test_web_facade.py
- Test: tests/interface/web/test_pages.py

**Interfaces:**
- Keep project_summaries() keys workspace, requirements, requirement_count, accepted_count, model_state, and latest_run for template compatibility; overview values for requirements and latest_run are empty/None.
- Add project_details(workspace_name: str) -> dict[str, object] that loads the complete requirements state exactly once and returns formatted card requirements.

- [ ] Add failing tests that make facade.requirements() and facade.runs() raise, request /, and assert status 200; add a legacy Workbench-without-summary case that also returns 200.
- [ ] Run the focused page tests and confirm the current project_summaries() fails these isolation tests.
- [ ] Implement a repository-backed summary read for each workspace. A project with no Workbench uses zero counts and 未生成. A Workbench with no summary uses None counts and 摘要待读取. Do not call requirements(), requirement_overview(), runs(), or any payload-loading method.
- [ ] Implement project_details() using exactly one requirements() call. Format each current claim as id, subject, predicate, object, status, and the existing Chinese status label. Return an empty tuple when no Workbench exists.
- [ ] Run tests/interface/web/test_pages.py and tests/application/test_web_facade.py and confirm they pass.

### Task 3: Lazy-load project card details in the Web UI

**Files:**
- Modify: src/rflp_lite/interface/web/routes.py
- Modify: src/rflp_lite/interface/web/templates/project-management.html
- Create: src/rflp_lite/interface/web/templates/_project-card-details.html
- Test: tests/interface/web/test_pages.py

**Interfaces:**
- Add GET /w/{workspace_name}/project/details returning an HTML fragment.
- The overview must not contain current requirement text.
- The detail response must contain current requirement text and the existing card actions.

- [ ] Add a failing test asserting GET / has no submitted requirement text, GET /w/demo/project/details has it, and the card has hx-get with a toggle-once trigger.
- [ ] Run the focused test and confirm it fails because the overview currently renders requirement rows and the detail route is absent.
- [ ] Move the existing project card body markup into _project-card-details.html.
- [ ] Replace each overview card body with a loading placeholder and HTMX attributes:
  hx-get="/w/{{ project.workspace.name }}/project/details"
  hx-trigger="toggle once"
  hx-target="#project-details-{{ project.workspace.name }}"
  hx-swap="innerHTML"
- [ ] Add the detail route, call project_details(), and render the fragment. Catch the typed application errors used by existing project routes so a detail failure does not break GET /.
- [ ] Run the project-management and project-page tests and confirm they pass.

### Task 4: Verify legacy large-project behavior and regression

**Files:**
- Modify: tests/interface/web/test_pages.py only if an additional regression fixture is needed.

- [ ] Run .venv/bin/python -m pytest tests/interface/web -q.
- [ ] Use a TestClient against the default application to request / and verify 200 without parsing requirements(); do not write to workspaces/public-real-v1.
- [ ] Run .venv/bin/python -m pytest -q.
- [ ] Run git diff --check and inspect git status --short; do not stage unrelated user files.
- [ ] Commit remaining intended files with: git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/project-management.html src/rflp_lite/interface/web/templates/_project-card-details.html tests/application/test_web_facade.py tests/interface/web/test_pages.py && git commit -m "fix: lazy load project overview details"

