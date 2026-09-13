# Existing Model Seed Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow any non-empty active ModelGraph, including a partial imported SysML model, to enter the existing five-stage analysis path.

**Architecture:** Define “analysis input” from the ModelGraph itself: an active entity is sufficient, while deprecated-only graphs remain empty. Reuse the same predicate in the project service, generation service, and Web presentation so UI and API agree; retain the current stage, CAS, traceability, and warning behavior for incomplete seeds.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, typed `ModelGraph`, SQLite repository, pytest.

## Global Constraints

- Empty projects still require a requirement or readable document input.
- Explicit requirement text and readable document regions retain their current priority and behavior.
- Deprecated entities do not qualify as analysis input.
- Partial-model generation must expose missing layers and traceability as warnings or review state.
- No input check may create a Revision or bypass Runtime validation/CAS.
- Existing SysML import conflict protection and full-model behavior remain unchanged.

---

### Task 1: Make active ModelGraph content a shared input predicate

**Files:**
- Modify: `src/rflp_lite/domain/model.py:31-45`
- Modify: `src/rflp_lite/application/project_service.py:117-128`
- Modify: `src/rflp_lite/application/model_generation.py:843-855`
- Test: `tests/application/test_project_service.py`
- Test: `tests/interface/web/test_resource_api.py`

**Interfaces:**
- Consumes: `ModelGraph.entities`, `EntityStatus.DEPRECATED`, `ProjectService.has_analysis_input`, and the existing `/projects/{project_id}/analysis` endpoint.
- Produces: `ModelGraph.has_active_entities -> bool`; project and generation input gates use it before falling back to document evidence.

- [ ] **Step 1: Write failing application and API tests**

```python
def test_active_partial_model_counts_as_analysis_input(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")
    service = _service(root)
    repository = service.repository("p1")
    graph = repository.load_graph("p1")
    entity = make_entity(
        EntityKind.FUNCTION,
        "已有配送功能",
        {"behavior": "完成配送"},
        status=EntityStatus.ACCEPTED,
        producer=Producer.IMPORT,
        confidence=1.0,
    )
    repository.append_patch(
        "p1",
        Patch.create("p1", "test.import", (AddEntity(entity),), "导入部分模型", graph.revision),
        graph.revision,
    )

    assert service.has_analysis_input("p1") is True


def test_deprecated_only_model_is_not_analysis_input(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    create_managed_workspace(root, "p1")
    service = _service(root)
    repository = service.repository("p1")
    graph = repository.load_graph("p1")
    entity = make_entity(EntityKind.FUNCTION, "废弃功能", status=EntityStatus.DEPRECATED)
    repository.append_patch(
        "p1",
        Patch.create("p1", "test.import", (AddEntity(entity),), "导入废弃模型", graph.revision),
        graph.revision,
    )

    assert service.has_analysis_input("p1") is False
```

Add the required imports from `rflp_lite.domain.entities` and `rflp_lite.domain.model` to the test module. Add an API test that uploads a SysML file containing only one Function to a fresh project and posts `{"mode": "generate"}` without requirement text; it must receive HTTP 200 and a `run` payload rather than the existing `InputRequired` error.

- [ ] **Step 2: Run the focused tests and verify the current gate fails**

Run: `./.venv/bin/pytest tests/application/test_project_service.py::test_active_partial_model_counts_as_analysis_input tests/application/test_project_service.py::test_deprecated_only_model_is_not_analysis_input tests/interface/web/test_resource_api.py -q`

Expected: the new active-model application test fails because `ModelGraph` has no active-entity predicate, and the partial-model API test returns 422 before generation.

- [ ] **Step 3: Add the domain predicate and reuse it in both application gates**

```python
# src/rflp_lite/domain/model.py
@property
def has_active_entities(self) -> bool:
    return any(item.meta.status is not EntityStatus.DEPRECATED for item in self.entities)
```

Update `ProjectService.has_analysis_input` to return `True` when `graph.has_active_entities` is true, then retain its document fallback. Update `ModelGenerationService._ensure_input` so that after explicit text/document extraction, an existing active graph returns without raising `InputRequired`; only an empty graph with no readable document raises the current error.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `./.venv/bin/pytest tests/application/test_project_service.py tests/interface/web/test_resource_api.py -q`

Expected: PASS, including empty-project rejection, document input, natural-language generation, and partial-model generation.

- [ ] **Step 5: Commit the input-gate change**

```bash
git add src/rflp_lite/domain/model.py src/rflp_lite/application/project_service.py src/rflp_lite/application/model_generation.py tests/application/test_project_service.py tests/interface/web/test_resource_api.py
git commit -m "feat: accept active model graphs as analysis input"
```

### Task 2: Make the Web state reflect imported partial models

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/analysis.html:25,66-68`
- Modify: `tests/interface/web/test_analysis_workflow.py`
- Test: `tests/interface/web/test_sysml_intake.py`

**Interfaces:**
- Consumes: `ProjectService.has_analysis_input` from `build_analysis_view` and `/projects/{project_id}/sysml/import/upload`.
- Produces: enabled Web generation controls after a partial SysML import, with copy that names importing a model as a valid input.

- [ ] **Step 1: Write the failing Web assertion**

```python
def test_analysis_page_enables_generation_after_partial_sysml_import(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "source"}).status_code == 200
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    source = graph_to_sysml(ModelGraph("source", (make_entity(EntityKind.FUNCTION, "已有配送功能"),), (), 0))
    imported = client.post(
        "/projects/p1/sysml/import/upload",
        files={"file": ("partial.sysml", source, "text/plain")},
    )
    assert imported.status_code == 200

    page = client.get("/ui/projects/p1/analysis")

    assert page.status_code == 200
    assert 'data-mode="generate" disabled' not in page.text
    assert "导入模型也可以作为分析输入" in page.text
```

Add the necessary `ModelGraph`, `EntityKind`, `make_entity`, and `graph_to_sysml` imports to the test module.

- [ ] **Step 2: Run the page test and verify it fails**

Run: `./.venv/bin/pytest tests/interface/web/test_analysis_workflow.py::test_analysis_page_enables_generation_after_partial_sysml_import -q`

Expected: FAIL because the current disabled title/copy only describes requirement and document inputs.

- [ ] **Step 3: Update the input copy and disabled hint**

Change the intake description to mention “提交需求、上传文档或导入已有模型”. Change the disabled generation and phase-button title to `请先提交需求、上传文档或导入已有模型`. Add the visible hint `导入模型也可以作为分析输入` near the SysML upload control; do not expose Task/Patch/CAS internals.

- [ ] **Step 4: Run all Web input and generation tests**

Run: `./.venv/bin/pytest tests/interface/web/test_analysis_workflow.py tests/interface/web/test_sysml_intake.py tests/interface/web/test_vertical_generation_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the Web state change**

```bash
git add src/rflp_lite/interface/web/templates/analysis.html tests/interface/web/test_analysis_workflow.py tests/interface/web/test_sysml_intake.py
git commit -m "feat: enable analysis from partial model imports"
```

### Task 3: Complete regression verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/plans/2026-09-13-existing-model-seed-continuation.md`

**Interfaces:**
- Consumes: the active-model input predicate and Web behavior from Tasks 1–2.
- Produces: documented partial-model continuation semantics and a verified pushed branch.

- [ ] **Step 1: Document the accepted input semantics**

Add that any active existing ModelGraph, including a partial imported SysML model, can enter Analysis; state that missing layers remain visible as warnings/review findings.

- [ ] **Step 2: Mark this plan complete and scan it for placeholders**

Change every completed checkbox to `[x]`. Run:

```bash
rg -n "TODO|TBD|FIXME|Similar to Task|add appropriate" docs/superpowers/plans/2026-09-13-existing-model-seed-continuation.md
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

Expected: every command exits 0; no architecture budget regresses.

- [ ] **Step 4: Commit and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/plans/2026-09-13-existing-model-seed-continuation.md
git commit -m "docs: record partial model continuation flow"
git push origin codex/web-audit-2026-08-18
```
