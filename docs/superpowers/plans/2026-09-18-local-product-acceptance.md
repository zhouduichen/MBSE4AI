# Local Product Acceptance Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one local, offline acceptance path prove that document intake, RFLP/V&V generation, SysML round-trip, concept evaluation, CAD preview/review, and engineering delivery are connected by the same project and source requirements.

**Architecture:** Keep existing application services and ModelGraph as the source of truth. Extend the revision-bound deliverable composer with optional, audit-backed concept and detail-design projections; the acceptance test will call existing services in one project and use the deterministic runtime plus vendor-neutral CAD preview only.

**Tech Stack:** Python 3.11+, pytest, SQLiteModelRepository, VerticalRuleRuntime, existing concept-design services, existing CAD/Drawing/DesignRule ports, deterministic SysML v2 subset.

## Global Constraints

- Do not start a local model or connect to a remote model/CAD server.
- Keep existing RFLP/V&V and CAD review gates unchanged.
- Preserve the core deliverable member set for projects without concept/detail-design records.
- Keep concept and detail-design records audit-backed; do not introduce a second engineering database.
- A single acceptance run is sufficient; do not add repeated stability experiments.

---

### Task 1: Add audit-backed concept/detail-design deliverable projections

**Files:**
- Modify: `src/rflp_lite/application/deliverables.py`
- Test: `tests/application/test_deliverables.py`

**Interfaces:**
- Consumes: `ModelRepository.list_audit_events(project_id)` and existing `EngineeringDeliverableService.build/export_zip`.
- Produces: optional `concept_design` and `detail_design` artifacts with revision and snapshot metadata; optional ZIP members `concept-design.json` and `detail-design.json`.

- [x] **Step 1: Write the failing test**

Create a project, run the existing deterministic concept service and CAD preview workflow, then assert that `build()` exposes both optional artifacts and `export_zip()` includes both JSON members.

- [x] **Step 2: Run the focused test to verify it fails**

Run:

```bash
./.venv/bin/pytest -q tests/application/test_deliverables.py -k concept_detail
```

Expected: FAIL because the deliverable composer currently emits only the core ModelGraph projections.

- [x] **Step 3: Implement the minimal projection**

Read only audit events whose kinds start with `concept.record.` or `detail_design.record.`, retain their `record` payloads in event order, and add an artifact only when at least one record exists. Add deterministic artifact paths and include optional JSON members in the ZIP while leaving `REQUIRED_MEMBERS` unchanged.

- [x] **Step 4: Run the focused test to verify it passes**

Run:

```bash
./.venv/bin/pytest -q tests/application/test_deliverables.py -k concept_detail
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/rflp_lite/application/deliverables.py tests/application/test_deliverables.py
git commit -m "feat: include design projections in engineering package"
```

### Task 2: Add one local full-chain acceptance test

**Files:**
- Create: `tests/e2e/test_local_product_acceptance.py`

**Interfaces:**
- Consumes: `ProjectService.ingest`, `RequirementsUseCaseService`, `ModelGenerationService`, `ConceptDesignProjectService`, `CadWorkflowService`, `DesignReviewService`, `EngineeringDeliverableService`, and `sysml_to_graph`.
- Produces: one executable local acceptance proof covering 1.1–3.3 without a model server.

- [x] **Step 1: Write the acceptance test**

Use `tests/fixtures/requirements_use_case_acceptance.txt`, `VerticalRuleRuntime`, and one temporary project. Assert document-derived requirements, complete R→F→L→P→V&V coverage, SysML entity/relation round-trip, one editable ModelGraph patch, five concept candidates with three evaluations each, a CAD preview plan sourced to a real requirement, shared annotations, DFM/DFA review evidence, and the optional deliverable artifacts.

- [x] **Step 2: Run the acceptance test**

Run:

```bash
./.venv/bin/pytest -q tests/e2e/test_local_product_acceptance.py
```

Expected: PASS without `AI4MBSE_CAD_BACKEND` and without any SSH or model process.

- [x] **Step 3: Commit**

```bash
git add tests/e2e/test_local_product_acceptance.py
git commit -m "test: prove local end-to-end product chain"
```

### Task 3: Verify local delivery and repository state

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: local acceptance test and existing full test suite.
- Produces: documented local acceptance command and an auditable GitHub commit.

- [x] **Step 1: Run focused and full checks**

```bash
./.venv/bin/pytest -q tests/application/test_deliverables.py tests/e2e/test_local_product_acceptance.py
./.venv/bin/pytest -q
./.venv/bin/ruff check src tests scripts
git diff --check
```

- [x] **Step 2: Document the local-only acceptance command**

State that the acceptance path uses the offline deterministic runtime and preview CAD, and that the remote FreeCAD test remains opt-in and is not run in this phase.

- [x] **Step 3: Commit and push**

```bash
git add README.md docs/DEVELOPMENT_STATUS.md
git commit -m "docs: record local product acceptance path"
git push origin codex/web-audit-2026-08-18
```
