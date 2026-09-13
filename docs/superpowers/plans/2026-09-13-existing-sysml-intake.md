# Existing SysML Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make existing SysML subset models uploadable from the Web workbench and usable by the same editable ModelGraph generation flow.

**Architecture:** Add one multipart adapter endpoint that reuses the existing SysML parser and CAS append logic. Add one dedicated upload control to the Analysis page and prove import, conflict protection, edit, and unified ZIP export in API/UI tests.

**Tech Stack:** FastAPI, `UploadFile`, existing `sysml_to_graph`, SQLite ModelRepository, Jinja2, browser `fetch`/`FormData`, pytest.

## Global Constraints

- The upload field name is exactly `file`.
- The endpoint is exactly `/projects/{project_id}/sysml/import/upload`.
- Only the existing deterministic SysML v2 subset is accepted.
- Conflicting entity IDs must fail before repository mutation.
- Existing raw-body SysML import remains backward-compatible.
- The UI must not expose TaskSpec, Patch, CAS, or validator internals.

---

### Task 1: Add the multipart SysML upload endpoint

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py:1000-1030`
- Test: `tests/interface/web/test_sysml_intake.py`

**Interfaces:**
- Consumes: multipart `file`, `sysml_to_graph`, `repository.load_graph`, and existing `AddEntity`/`Relate` CAS append path.
- Produces: `POST /projects/{project_id}/sysml/import/upload` returning `status`, `revision`, `entity_count`, and `relation_count`.

- [x] **Step 1: Write failing endpoint tests**

```python
def test_sysml_upload_imports_model_and_reports_counts(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    source = "package AI4MBSE_Model {\n  // @revision: 0\n}\n"
    response = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("model.sysml", source, "text/plain")},
    )
    assert response.status_code == 422

def test_sysml_upload_conflict_does_not_mutate_revision(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    exported = client.post("/projects/p1/export", json={"format": "sysml"})
    before = client.get("/projects/p1/model").json()["revision"]
    response = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("model.sysml", exported.text, "text/plain")},
    )
    assert response.status_code == 422
    assert client.get("/projects/p1/model").json()["revision"] == before
```

- [x] **Step 2: Run the tests and verify the route is absent**

Run: `./.venv/bin/pytest tests/interface/web/test_sysml_intake.py -q`

Expected: FAIL because the upload route does not exist.

- [x] **Step 3: Implement the upload route**

Read the multipart form, require a readable `file`, decode UTF-8, parse with
`sysml_to_graph`, reject `existing_ids & imported_ids`, build the same
`sysml.import` Patch used by the raw route, and append it with the current
revision. Catch `UnicodeDecodeError` in the existing error tuple. Return the
same response fields as the raw importer.

- [x] **Step 4: Run focused and regression SysML tests**

Run: `./.venv/bin/pytest tests/interface/web/test_sysml_intake.py tests/interface/web/test_resource_api.py tests/interface/web/test_vertical_generation_api.py -q`

Expected: PASS, including raw-body import and existing export behavior.

- [x] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/web/resource_api.py tests/interface/web/test_sysml_intake.py
git commit -m "feat: accept uploaded SysML models"
```

### Task 2: Add the Web intake control

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/analysis.html:20-42`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Consumes: the new upload endpoint and `FormData` with field `file`.
- Produces: visible `.sysml` file input, “导入已有 SysML 模型” action, and reload-on-success behavior.

- [x] **Step 1: Write the failing page assertion**

```python
def test_analysis_page_exposes_existing_sysml_upload(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    page = client.get("/ui/projects/p1/analysis")
    assert page.status_code == 200
    assert "已有 SysML 模型" in page.text
    assert ".sysml" in page.text
    assert "/sysml/import/upload" in page.text
```

- [x] **Step 2: Run the page test and verify it fails**

Run: `./.venv/bin/pytest tests/interface/web/test_analysis_workflow.py::test_analysis_page_exposes_existing_sysml_upload -q`

Expected: FAIL because the Analysis page has no SysML control.

- [x] **Step 3: Add the control and browser handler**

Add a separate form with `<input accept=".sysml" type="file">`, a submit
button, and a handler that appends the selected file under `file` to
`/projects/${projectId}/sysml/import/upload`. Reuse `showIntakeResult`; reload
after an `ok` response.

- [x] **Step 4: Run all Analysis page tests**

Run: `./.venv/bin/pytest tests/interface/web/test_analysis_workflow.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/web/templates/analysis.html tests/interface/web/test_analysis_workflow.py
git commit -m "feat: add SysML model intake to analysis workbench"
```

### Task 3: Prove imported models remain part of the product loop

**Files:**
- Modify: `tests/interface/web/test_sysml_intake.py`
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: upload import, existing CAS edit, `/projects/{id}/deliverables/download`, and SysML round-trip.
- Produces: evidence for import → edit → export and user documentation of existing model intake.

- [x] **Step 1: Add the integrated flow test**

```python
def test_imported_model_can_be_edited_and_exported(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    exported = client.post("/projects/p1/export", json={"format": "sysml"})
    assert client.post("/projects", json={"id": "p2"}).status_code == 200
    imported = client.post(
        "/projects/p2/sysml/import/upload",
        files={"file": ("existing.sysml", exported.text, "text/plain")},
    )
    assert imported.status_code == 200
    model = client.get("/projects/p2/model").json()
    entity = next(item for item in model["entities"] if item["kind"] == "function")
    edited = client.patch(
        f"/projects/p2/entities/{entity['id']}",
        json={"expected_revision": model["revision"], "field_patch": {"name": "人工编辑功能"}},
    )
    assert edited.status_code == 200
    bundle = client.get("/projects/p2/deliverables/download")
    assert bundle.status_code == 200
    assert bundle.headers["content-type"].startswith("application/zip")
```

- [ ] **Step 2: Run the integrated flow test**

Run: `./.venv/bin/pytest tests/interface/web/test_sysml_intake.py::test_imported_model_can_be_edited_and_exported -q`

Expected: PASS.

- [x] **Step 3: Update product documentation**

Add existing `.sysml` model upload to the README, current architecture
resource table, and development status. State that import uses the same
ModelGraph source of truth and preserves conflict protection.

- [ ] **Step 4: Run complete verification**

Run:

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 5: Commit and push**

```bash
git add tests/interface/web/test_sysml_intake.py README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md
git commit -m "test: prove existing SysML intake loop"
git push origin codex/web-audit-2026-08-18
```
