# Project Page and Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the v2 Web project pages render with the application UI, open existing workspaces without legacy-schema 500 errors, and provide a confirmed permanent project deletion flow.

**Architecture:** Keep the existing FastAPI resource API and application-service boundaries. The Web layer owns presentation and the confirmation/redirect behavior; `ProjectService` owns workspace path validation and deletion; SQLite migrations preserve incompatible legacy tables under `legacy_*` names before creating the v2 tables. Existing v2-compatible tables are reused so opening a legacy workspace is non-destructive to its historical data.

**Tech Stack:** Python 3.12, FastAPI, Jinja2 templates, SQLite, pytest, Ruff.

## Global Constraints

- Permanent deletion is limited to a project directory under the configured workspace root.
- The server accepts a project identifier, never an arbitrary filesystem path.
- The browser must require confirmation immediately before sending the DELETE request.
- Legacy tables are renamed and preserved; no legacy project data is silently overwritten.
- The existing `/ui/projects`, `/ui/projects/{project_id}/analysis`, `/ui/projects/{project_id}/model`, `/ui/projects/{project_id}/evidence`, and `/ui/settings` routes remain available.

---

### Task 1: Make the v2 Web shell and resource pages render consistently

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `src/rflp_lite/interface/web/templates/projects.html`
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/evidence-issues.html`
- Modify: `src/rflp_lite/interface/web/templates/settings.html`
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Test: `tests/interface/web/test_app.py`

**Interfaces:**
- Consumes: existing `/static/app.css`, `Jinja2Templates`, and the v2 service summaries.
- Produces: a shared `.app-shell` layout, active navigation context, and styled resource pages.

- [x] **Step 1: Confirm the failure mode**

Run:

```bash
curl -sS http://localhost:8000/ui/projects
```

Expected before the fix: the response is standalone HTML without a stylesheet link.

- [x] **Step 2: Add the shared shell and template inheritance**

`base.html` must emit the stylesheet link and wrap content in `.app-shell`, `.sidebar`, `.topbar`, `.main-column`, and `.content`. Each v2 page must begin with `{% extends "base.html" %}` and place content in `{% block content %}`. The page route contexts must include `active` so the sidebar can highlight the current page.

- [x] **Step 3: Run the Web test and asset checks**

Run:

```bash
./.venv/bin/python -m pytest tests/interface/web/test_app.py -q
curl -fsS http://localhost:8000/static/app.css >/dev/null
```

Expected: pytest passes and the CSS request returns HTTP 200.

- [x] **Step 4: Commit the rendering fix**

```bash
git add src/rflp_lite/interface/web/templates src/rflp_lite/interface/web/resource_pages.py tests/interface/web/test_app.py
git commit -m "fix: render v2 resource pages with shared web shell"
```

### Task 2: Preserve incompatible legacy SQLite tables during v2 bootstrap

**Files:**
- Modify: `src/rflp_lite/repository/migrations.py`
- Test: `tests/repository/test_sqlite_model_repository.py`

**Interfaces:**
- Consumes: an existing SQLite file that may contain legacy `relations`, `evidence`, or `audit_events` tables.
- Produces: v2-compatible tables and indexes while preserving incompatible tables as `legacy_relations`, `legacy_evidence`, or `legacy_audit_events`.

- [x] **Step 1: Write a failing migration compatibility test**

Add a test that creates a SQLite file with the legacy table definitions, then instantiates `SQLiteModelRepository`, calls `ensure_project("p1")`, and loads the graph. Assert that the v2 columns exist on `relations`, `evidence`, and `audit_events`, and that the original rows are still present in the corresponding `legacy_*` tables.

```python
def test_legacy_core_tables_are_preserved_and_replaced(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE relations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        INSERT INTO relations VALUES ('old-rel', '{}');
        CREATE TABLE evidence (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        INSERT INTO evidence VALUES ('old-evidence', '{}');
        CREATE TABLE audit_events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, payload TEXT NOT NULL);
        INSERT INTO audit_events(kind, payload) VALUES ('old', '{}');
        """
    )
    connection.close()

    repository = SQLiteModelRepository(path)
    repository.ensure_project("p1")
    assert {"project_id", "source_id", "target_id"} <= _columns(path, "relations")
    assert {"project_id", "claim", "excerpt"} <= _columns(path, "evidence")
    assert {"project_id", "kind", "payload"} <= _columns(path, "audit_events")
    assert _count(path, "legacy_relations") == 1
    assert _count(path, "legacy_evidence") == 1
    assert _count(path, "legacy_audit_events") == 1
```

The test helper may use a fresh `sqlite3.connect()` to inspect columns/counts; it must not modify the database.

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest tests/repository/test_sqlite_model_repository.py::test_legacy_core_tables_are_preserved_and_replaced -q
```

Expected: FAIL during schema bootstrap with a missing v2 column, reproducing the current 500 cause.

- [x] **Step 3: Implement idempotent compatibility checks**

Before `_apply_core_schema(connection)`, inspect the required columns for the three known conflicting tables. For each existing table whose columns do not contain the v2 contract, rename it to the first available `legacy_<name>`/`legacy_<name>_<n>` name. Then let the existing `CREATE TABLE IF NOT EXISTS` statements create the v2 table and indexes.

The helper must use only hard-coded table names from the migration module, must not accept a filesystem path or SQL fragment from a request, and must be safe to run a second time.

- [x] **Step 4: Run the migration test and repository suite**

Run:

```bash
./.venv/bin/python -m pytest tests/repository/test_sqlite_model_repository.py -q
```

Expected: all repository tests pass, including the new compatibility test.

- [x] **Step 5: Commit the compatibility migration**

```bash
git add src/rflp_lite/repository/migrations.py tests/repository/test_sqlite_model_repository.py
git commit -m "fix: preserve legacy sqlite tables during v2 migration"
```

### Task 3: Add permanent project deletion at the application and API boundaries

**Files:**
- Modify: `src/rflp_lite/application/project_service.py`
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/app.py`
- Create: `tests/application/test_project_service.py`
- Test: `tests/interface/web/test_resource_api.py`

**Interfaces:**
- Consumes: `ProjectService.workspace_root`, `managed_workspace()`, and existing `_error()` handling.
- Produces: `ProjectService.delete(project_id) -> dict[str, str]` and `DELETE /projects/{project_id}` with a stable JSON response.

- [x] **Step 1: Write failing service and API tests**

The service test must create a managed project containing `profile.json`, `.rflp/model.db`, and an input file, call `delete("p1")`, then assert the directory is gone. It must also assert an invalid path-like identifier raises `ContractViolation` and a missing project raises `NotFoundError`.

The API test must create a project through `POST /projects`, delete it through `DELETE /projects/p1`, assert `{"status": "ok", "project_id": "p1"}`, and assert a second delete returns a not-found response.

- [x] **Step 2: Run the tests to verify they fail**

```bash
./.venv/bin/python -m pytest tests/application/test_project_service.py tests/interface/web/test_resource_api.py -q
```

Expected: the service method and DELETE route are missing.

- [x] **Step 3: Implement guarded deletion and not-found mapping**

`ProjectService.delete()` must call `managed_workspace()`, reject symlink targets, require an existing directory, and remove only that resolved child directory with `shutil.rmtree()`. The API must expose `DELETE /projects/{project_id}` and return the stable success object. Map `NotFoundError` to HTTP 404 before the generic `ContractViolation` 422 handler, and use the same mapping in `_error()`.

- [x] **Step 4: Run the service/API tests**

```bash
./.venv/bin/python -m pytest tests/application/test_project_service.py tests/interface/web/test_resource_api.py -q
```

Expected: all tests pass.

- [x] **Step 5: Commit the deletion backend**

```bash
git add src/rflp_lite/application/project_service.py src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/app.py tests/application/test_project_service.py tests/interface/web/test_resource_api.py
git commit -m "feat: add guarded project deletion api"
```

### Task 4: Add the confirmed delete interaction and run end-to-end verification

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/projects.html`
- Test: `tests/interface/web/test_app.py`

**Interfaces:**
- Consumes: `DELETE /projects/{project_id}` from Task 3.
- Produces: one delete button per project, an immediate browser confirmation, error feedback, and list refresh after success.

- [x] **Step 1: Add a page-level interaction test**

Assert a rendered project list contains the project name, a `.danger` delete control, and the DELETE endpoint identifier. The test should not execute deletion against a real workspace.

- [x] **Step 2: Implement the browser interaction**

Each delete button must call `confirm()` with the exact project name and permanent-deletion warning before `fetch("/projects/<id>", {method: "DELETE"})`. On HTTP success, navigate to `/ui/projects`; on failure, show the server message beside the project card. Do not submit or transmit anything when confirmation is cancelled.

- [x] **Step 3: Run focused and complete verification**

```bash
./.venv/bin/python -m pytest tests/interface/web tests/application/test_project_service.py tests/repository/test_sqlite_model_repository.py -q
./.venv/bin/python scripts/verify_full.py
```

Expected: all tests, compile, architecture metrics, Ruff, and import-boundary checks pass.

- [x] **Step 4: Verify in the browser**

Open `http://localhost:8000/ui/projects`, confirm the styled shell is visible, open an existing project, confirm the analysis page no longer returns 500, and inspect the delete controls without confirming a real deletion. Use a temporary test project for the final delete click and confirm it disappears from the list.

- [x] **Step 5: Commit the Web interaction**

```bash
git add src/rflp_lite/interface/web/templates/projects.html tests/interface/web/test_app.py
git commit -m "feat: add confirmed project deletion control"
```
