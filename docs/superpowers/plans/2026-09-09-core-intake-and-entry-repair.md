# Core Intake and Entry Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a usable AI4MBSE path from project selection to requirement intake, document ingestion, guarded analysis, model export, and runtime configuration.

**Architecture:** Keep FastAPI resource routes as the application boundary and add a small ProjectService intake method that creates a user-owned Requirement through the existing Patch/CAS repository. Multipart uploads use the existing document parser and remain scoped to the selected project. The analysis API performs a read-only input gate before constructing a WorkflowRunner, while the UI uses the existing fetch-based interaction style.

**Tech Stack:** Python 3.11+, FastAPI, Starlette multipart, Jinja2, SQLite repository, pytest/TestClient, existing static CSS/vanilla JavaScript.

## Global Constraints

- Preserve existing user workspaces and do not delete or migrate existing data.
- Keep the local-only default bind (`127.0.0.1`) and do not add external services.
- Keep ModelGraph as the only model truth; all requirement writes use a Patch and expected revision.
- Keep API keys out of HTML and JSON responses.
- Existing CLI, domain, repository, architecture, and import-boundary tests must remain green.

---

### Task 1: Add input-aware project service primitives

**Files:**
- Modify: `src/rflp_lite/application/project_service.py`
- Modify: `src/rflp_lite/domain/errors.py`
- Test: `tests/application/test_project_service.py`

**Interfaces:**
- Produces `ProjectService.add_requirement(project_id: str, text: str) -> dict[str, object]`.
- Produces `ProjectService.has_analysis_input(project_id: str) -> bool`.
- Produces `ProjectService.ingest_uploaded(project_id: str, filename: str, content: bytes) -> dict[str, object]`.

- [x] **Step 1: Write failing service tests**

Add tests proving a non-empty text creates one candidate/user Requirement and increments the revision; blank text raises `ContractViolation`; a fresh project has no analysis input; and a parsed uploaded TXT is persisted under the project `inputs/` directory with source regions.

- [x] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/test_project_service.py -q`

Expected: FAIL because the three new methods are absent.

- [x] **Step 3: Implement the service methods**

Use `make_entity(EntityKind.REQUIREMENT, clean_text, payload={"statement": clean_text, "source": "user_input", "requires_human_review": True}, status=EntityStatus.CANDIDATE, producer=Producer.USER, confidence=1.0, revision=graph.revision)` and append an `AddEntity` Patch with `graph.revision`. For uploads, validate the parser-supported suffix, write bytes to `self.path(project_id) / "inputs" / safe_name`, then call the parser and persist document/source regions using the same mapping as `ingest`. `has_analysis_input` returns true for a non-deprecated Requirement produced by USER or IMPORT, or when the repository exposes at least one saved document.

- [x] **Step 4: Run focused tests and verify pass**

Run: `.venv/bin/python -m pytest tests/application/test_project_service.py -q`

Expected: PASS.

- [x] **Step 5: Commit the isolated service change**

```bash
git add src/rflp_lite/application/project_service.py src/rflp_lite/domain/errors.py tests/application/test_project_service.py
git commit -m "feat: add project requirement and document intake primitives"
```

### Task 2: Expose intake routes and guard analysis

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/app.py`
- Test: `tests/interface/web/test_resource_api.py`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Adds `POST /projects/{project_id}/requirements` with JSON `{text}`.
- Extends `POST /projects/{project_id}/documents` to accept multipart `file` while preserving JSON `{path}`.
- Adds `InputRequired` as a 422 error payload for analysis with no input.
- Adds `GET /` redirecting to `/ui/projects`.

- [x] **Step 1: Write failing API tests**

Cover root redirect, requirement submission, multipart TXT upload, and a blank-project pipeline/phase request that returns 422 with `error == "InputRequired"` and leaves revision 0.

- [x] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/interface/web/test_resource_api.py tests/interface/web/test_analysis_workflow.py -q`

Expected: FAIL on missing route, missing upload handling, and unguarded empty analysis.

- [x] **Step 3: Implement routes and guard**

Use `UploadFile`/`File` only for the multipart branch and avoid writing arbitrary client paths. Add a small `InputRequired(RflpError)` class, register it through the existing exception mapping, and check `services.projects.has_analysis_input(project_id)` before `_invoke_pipeline`/`_call_run`.

- [x] **Step 4: Run focused tests and verify pass**

Run the same focused pytest command; expected PASS.

- [x] **Step 5: Commit API changes**

```bash
git add src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/app.py tests/interface/web/test_resource_api.py tests/interface/web/test_analysis_workflow.py
git commit -m "feat: expose requirement intake and guard empty analysis"
```

### Task 3: Add visible intake UI and repair project navigation

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Modify: `src/rflp_lite/interface/web/templates/projects.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_app.py`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Analysis page exposes a requirement textarea, submit button, file input, and intake status area.
- Project list remains the first page and `/` reaches it.

- [x] **Step 1: Write failing page tests**

Assert the analysis HTML contains the requirement textarea, upload input, submit handlers, and the empty-input explanation. Assert project page links to the analysis route.

- [x] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/interface/web/test_app.py tests/interface/web/test_analysis_workflow.py -q`

- [x] **Step 3: Implement the intake panel**

Add a panel above lifecycle controls with a labelled textarea and `accept=".txt,.md,.markdown,.docx,.pdf"` file input. Submit text as JSON to `/projects/{id}/requirements`; submit files as `FormData` to `/projects/{id}/documents`; show success/error JSON in a visible status element and reload after success.

- [x] **Step 4: Run focused tests and verify pass**

Run the focused pytest command and verify PASS.

- [x] **Step 5: Commit UI changes**

```bash
git add src/rflp_lite/interface/web/templates/analysis.html src/rflp_lite/interface/web/templates/projects.html src/rflp_lite/interface/web/static/app.css tests/interface/web/test_app.py tests/interface/web/test_analysis_workflow.py
git commit -m "feat: add visible requirement and document intake UI"
```

### Task 4: Expose model exports and runtime configuration controls

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/templates/settings.html`
- Modify: `src/rflp_lite/application/settings_service.py`
- Test: `tests/interface/web/test_resource_api.py`
- Test: `tests/interface/web/test_settings_runtime_status.py`

**Interfaces:**
- Web export accepts `json`, `dot`, `svg`, and `sysml`.
- Settings page can save a profile and activate an existing profile without exposing credentials.

- [x] **Step 1: Write failing export/settings tests**

Assert Web `sysml` export returns 200 with a SysML-lite package; assert settings HTML contains save and activate controls; assert profile save/activate responses omit `api_key`.

- [x] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/python -m pytest tests/interface/web/test_resource_api.py tests/interface/web/test_settings_runtime_status.py -q`

- [x] **Step 3: Implement shared SysML-lite rendering and controls**

Move the CLI serializer into a small application/render helper used by both CLI and API. Add model-page links/forms that call export and use the browser download response. Add settings form fields for id, label, kind, base URL, model, timeout, optional key, and an activate button for each saved profile; rely on `SettingsService` public methods and never render the key.

- [x] **Step 4: Run focused tests and verify pass**

Run the focused pytest command and verify PASS.

- [x] **Step 5: Commit export/settings changes**

```bash
git add src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/templates/model.html src/rflp_lite/interface/web/templates/settings.html src/rflp_lite/application/settings_service.py tests/interface/web/test_resource_api.py tests/interface/web/test_settings_runtime_status.py
git commit -m "feat: expose model exports and runtime profile controls"
```

### Task 5: Full verification and local browser acceptance

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md` if capability wording needs correction.
- Test: existing suite plus new tests from Tasks 1–4.

- [x] **Step 1: Run the complete verification suite**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src
.venv/bin/ruff check src tests
.venv/bin/lint-imports
.venv/bin/python scripts/architecture_metrics.py
```

Expected: all commands exit 0.

- [x] **Step 2: Exercise the live local UI**

Open `/`, create a temporary project, confirm the intake panel exists, submit a test requirement, upload a TXT, confirm the requirement/evidence counts change, run analysis, open model exports, and inspect settings. Do not delete existing user projects.

- [x] **Step 3: Remove or quarantine dead legacy template links**

Ensure no active template links to `/w/*/requirements/*`; either remove unused legacy templates from package data or mark them as non-shipped. Add a route smoke assertion for the active pages.

- [x] **Step 4: Update status documentation and commit verification**

```bash
git add docs/DEVELOPMENT_STATUS.md tests docs/superpowers/specs docs/superpowers/plans
git commit -m "test: verify core intake and entry repair"
```
