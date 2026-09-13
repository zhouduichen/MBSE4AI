# Unified Engineering Deliverable Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose one deterministic, revision-bound package containing the editable ModelGraph exchange and all user-facing MBSE engineering outputs.

**Architecture:** Add one application service that loads a single ModelGraph and composes existing pure projections plus two report projections. Expose the service through read-only JSON and ZIP endpoints, then add a compact download panel to the existing model workbench. Keep ModelGraph as the only source of truth and keep the existing SysML import/export contracts unchanged.

**Tech Stack:** Python 3 standard library (`json`, `zipfile`, `io`), FastAPI, Jinja2, pytest, existing ModelGraph/projection/SysML components.

## Global Constraints

- The package format is exactly `ai4mbse.engineering-deliverable.v1`.
- Every package artifact is derived from one loaded graph revision and exposes the same `project_id`, `revision`, and `snapshot_hash`.
- Incomplete evidence remains an explicit report gap; the service must not invent a PASS or SATISFIED result.
- ZIP generation uses only the Python standard library and stable UTF-8 member content.
- Existing `/projects/{project_id}/export` and `/projects/{project_id}/sysml/import` behavior remains backward-compatible.
- The UI must not expose TaskSpec, Patch, CAS, validator, or provider internals.

---

### Task 1: Build the deterministic deliverable service

**Files:**
- Create: `src/rflp_lite/application/deliverables.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Test: `tests/application/test_deliverables.py`

**Interfaces:**
- Consumes: `ModelService.graph`, `ModelService.issues`, `build_requirements_view`, `build_rflp_view`, `build_traceability_view`, `build_assurance_view`, and `graph_to_sysml`.
- Produces: `EngineeringDeliverableService.build(project_id) -> Mapping[str, object]` and `EngineeringDeliverableService.export_zip(project_id) -> tuple[bytes, str]`; `V2Services.deliverables(project_id) -> EngineeringDeliverableService`.

- [ ] **Step 1: Write failing service tests**

Add a complete graph fixture using the existing entity/relation helpers and test:

```python
def test_build_contains_all_required_artifacts(tmp_path):
    services = _services_with_complete_graph(tmp_path)
    package = services.deliverables("p1").build("p1")
    assert package["format"] == "ai4mbse.engineering-deliverable.v1"
    assert set(package["artifacts"]) == {
        "model", "sysml", "requirements", "rflp", "traceability",
        "vv_plan", "architecture_report",
    }
    assert package["revision"] == package["artifacts"]["traceability"]["content"]["revision"]
    assert package["snapshot_hash"] == package["artifacts"]["rflp"]["content"]["snapshot_hash"]

def test_incomplete_graph_is_reported_as_gap(tmp_path):
    services = _services_with_requirement_only(tmp_path)
    report = services.deliverables("p1").build("p1")["artifacts"]["vv_plan"]["content"]
    assert report["rows"][0]["status"] == "MISSING_VERIFICATION"
    assert report["rows"][0]["missing"]

def test_zip_is_stable_and_sysml_round_trips(tmp_path):
    services = _services_with_complete_graph(tmp_path)
    first = services.deliverables("p1").export_zip("p1")[0]
    second = services.deliverables("p1").export_zip("p1")[0]
    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert set(archive.namelist()) == set(REQUIRED_MEMBERS)
        restored = sysml_to_graph(archive.read("model.sysml").decode(), "p1")
    graph = services.model("p1").graph("p1")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {(item.source_id, item.predicate, item.target_id) for item in restored.relations} == {
        (item.source_id, item.predicate, item.target_id) for item in graph.relations
    }
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/test_deliverables.py -q`

Expected: FAIL because `V2Services.deliverables` and the service module do not exist.

- [ ] **Step 3: Implement the service and report projections**

Implement these private helpers in `deliverables.py`:

```python
REQUIRED_MEMBERS = (
    "manifest.json", "model.json", "model.sysml", "requirements.json",
    "rflp.json", "traceability.json", "vv-plan.json", "vv-plan.md",
    "architecture-report.json", "architecture-report.md",
)

def _artifact(name: str, format_id: str, content: object, project_id: str, revision: int, snapshot_hash: str) -> dict[str, object]:
    return {"format": format_id, "project_id": project_id, "revision": revision, "snapshot_hash": snapshot_hash, "content": content}

def _vv_plan(assurance: Mapping[str, object]) -> dict[str, object]:
    rows = []
    for row in assurance["verification_validation"]:
        missing = []
        if row["case_type"] == "verification" and row["status"] == "MISSING_VERIFICATION":
            missing.append("verification")
        if row["case_type"] == "validation" and row["status"] == "MISSING_VALIDATION":
            missing.append("validation")
        rows.append({**dict(row), "missing": missing})
    return {"rows": rows, "gates": assurance["gates"], "metrics": assurance["gates"][-1]["coverage_summary"] if assurance["gates"] else {}}

def _architecture_report(graph: ModelGraph, rflp: Mapping[str, object], traceability: Mapping[str, object], assurance: Mapping[str, object]) -> dict[str, object]:
    counts = {kind.value: sum(entity.kind is kind for entity in graph.entities) for kind in EntityKind}
    valid_edges = sum(bool(edge["valid_for_trace"]) for edge in rflp["edges"])
    invalid_edges = len(rflp["edges"]) - valid_edges
    gate_passed = all(bool(gate["passed"]) for gate in assurance["gates"])
    status = "PASS" if gate_passed else "BLOCKED" if any(gate["blocking_issues"] for gate in assurance["gates"]) else "DEGRADED"
    return {"status": status, "entity_counts": counts, "traceability_metrics": dict(traceability["metrics"]), "valid_trace_edge_count": valid_edges, "invalid_trace_edge_count": invalid_edges, "allocation_count": sum(relation.predicate.value == "allocatedTo" for relation in graph.relations), "gates": assurance["gates"], "gaps": list(rflp["gaps"])}
```

The public `build` must first load `graph`, `issues`, and all projections,
then add the shared header to each structured content object. Serialize the
model as `{"project_id", "revision", "snapshot_hash", "entities", "relations"}`.
Render Markdown from the structured V&V and architecture rows in stable ID
order. `export_zip` must write the exact ten member names with a fixed ZIP
timestamp `(1980, 1, 1, 0, 0, 0)` and `ZIP_STORED` compression.

- [ ] **Step 4: Wire the service into `V2Services`**

Import `EngineeringDeliverableService` and add:

```python
def deliverables(self, project_id: str) -> EngineeringDeliverableService:
    return EngineeringDeliverableService(self.model(project_id))
```

- [ ] **Step 5: Run the focused tests**

Run: `./.venv/bin/pytest tests/application/test_deliverables.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/deliverables.py src/rflp_lite/bootstrap/v2.py tests/application/test_deliverables.py
git commit -m "feat: build unified engineering deliverables"
```

### Task 2: Expose JSON and ZIP delivery endpoints

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py:964`
- Test: `tests/interface/web/test_deliverables_api.py`

**Interfaces:**
- Consumes: `request.app.state.container.v2.deliverables(project_id)`.
- Produces: `GET /projects/{project_id}/deliverables` returning `{"status": "ok", "deliverable": package}` and `GET /projects/{project_id}/deliverables/download` returning `application/zip` with `Content-Disposition: attachment; filename="{project_id}-engineering-deliverables.zip"`.

- [ ] **Step 1: Write failing API tests**

```python
def test_deliverables_api_returns_single_revision_package(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    response = client.get("/projects/p1/deliverables")
    assert response.status_code == 200
    package = response.json()["deliverable"]
    assert package["format"] == "ai4mbse.engineering-deliverable.v1"
    assert package["revision"] == package["artifacts"]["model"]["content"]["revision"]

def test_deliverables_download_is_zip(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    response = client.get("/projects/p1/deliverables/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    assert response.headers["content-disposition"] == 'attachment; filename="p1-engineering-deliverables.zip"'
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "architecture-report.md" in archive.namelist()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./.venv/bin/pytest tests/interface/web/test_deliverables_api.py -q`

Expected: FAIL with HTTP 404 for both routes.

- [ ] **Step 3: Add the endpoints**

Add the two routes before the existing generic export route. Catch the same
`ContractViolation`, `RflpError`, `OSError`, and `ValueError` tuple already
used by the neighboring read-only endpoints. Return `_error(exc)` on error.

- [ ] **Step 4: Run focused API tests and regression export tests**

Run: `./.venv/bin/pytest tests/interface/web/test_deliverables_api.py tests/interface/web/test_resource_api.py -q`

Expected: PASS, including the pre-existing SysML export test.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/web/resource_api.py tests/interface/web/test_deliverables_api.py
git commit -m "feat: expose engineering deliverable endpoints"
```

### Task 3: Add the user-facing delivery panel

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/model.html`
- Modify: `src/rflp_lite/interface/web/resource_pages.py:1080-1085`
- Test: `tests/interface/web/test_model_workbench.py`

**Interfaces:**
- Consumes: `trace.revision`, `workbench.revision`, and the two read-only delivery URLs.
- Produces: a visible `导出完整交付包` action, a `查看交付包` link, and a displayed source revision/hash.

- [ ] **Step 1: Write the failing page assertion**

```python
def test_model_page_exposes_complete_delivery_panel(tmp_path):
    client, _ = _client_with_fixture(tmp_path)
    page = client.get("/ui/projects/p1/model")
    assert page.status_code == 200
    assert "导出完整交付包" in page.text
    assert "/projects/p1/deliverables/download" in page.text
    assert "snapshot" in page.text.lower()
```

- [ ] **Step 2: Run the page test to verify it fails**

Run: `./.venv/bin/pytest tests/interface/web/test_model_workbench.py::test_model_page_exposes_complete_delivery_panel -q`

Expected: FAIL because the model page has only individual format buttons.

- [ ] **Step 3: Add the compact delivery panel**

Add a server-rendered panel after the existing export panel. Use plain links
for JSON inspection and ZIP download so the browser does not need a new
client-side state flow. Pass `graph.snapshot_hash` as `snapshot_hash` from
`model_page`; do not add a second graph load in the template.

- [ ] **Step 4: Run page and full Web tests**

Run: `./.venv/bin/pytest tests/interface/web -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/interface/web/templates/model.html src/rflp_lite/interface/web/resource_pages.py tests/interface/web/test_model_workbench.py
git commit -m "feat: add complete delivery panel to model workbench"
```

### Task 4: Prove the 23-task end-to-end deliverable path

**Files:**
- Modify: `tests/e2e/test_campus_delivery_robot.py`
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: existing seeded campus fixture, four analysis phases, closure, and `EngineeringDeliverableService`.
- Produces: a regression proof that the complete fixture has R→F→L→P→V&V coverage and emits every required deliverable.

- [ ] **Step 1: Add the end-to-end assertions**

Extend the existing closure test with:

```python
package = services.deliverables("campus").build("campus")
assert package["revision"] == services.model("campus").graph("campus").revision
assert package["artifacts"]["traceability"]["content"]["metrics"]["complete_count"] == 5
assert package["artifacts"]["architecture_report"]["content"]["status"] == "PASS"
assert all(row["status"] == "PASS" for row in package["artifacts"]["vv_plan"]["content"]["rows"])
```

- [ ] **Step 2: Run the focused end-to-end test**

Run: `./.venv/bin/pytest tests/e2e/test_campus_delivery_robot.py::test_campus_fixture_runs_all_phases_and_closure -q`

Expected: PASS and all 23 catalog tasks remain represented by the four phase runs plus closure.

- [ ] **Step 3: Update product documentation**

Document the user flow and stable ZIP member names in README and current
architecture/status docs. State that reports are projections of ModelGraph
and that incomplete evidence remains visible as a gap.

- [ ] **Step 4: Run complete verification**

Run:

```bash
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests scripts
./.venv/bin/python -m importlinter
git diff --check
```

Expected: every command exits 0; no template files are passed to Ruff.

- [ ] **Step 5: Commit and push**

```bash
git add tests/e2e/test_campus_delivery_robot.py README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md
git commit -m "test: prove end-to-end engineering deliverables"
git push origin codex/web-audit-2026-08-18
```

