# Automatic Document-to-Model Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing structured requirements/use-case intake to the default generation entry point so text and imported Word/PDF documents produce one traceable MBSE model run.

**Architecture:** Keep `ModelGraph` and the existing CAS compiler as the only write path. `ModelGenerationService` will invoke `RequirementsUseCaseService` before the existing five vertical stages when new input is present, passing the already-selected runtime model when configured and using the deterministic intake fallback otherwise. No new repository or model server is introduced.

**Tech Stack:** Python 3.11+, existing SQLite repository, `RequirementsUseCaseService`, `ModelGenerationService`, `VerticalRuleRuntime`, pytest, existing document adapters.

## Global Constraints

- Do not start a local model or connect to a remote model/CAD server.
- Keep candidate/review statuses and CAS validation unchanged.
- Preserve idempotent existing-project generation and the standalone intake API.
- Keep DOCX/PDF parsing behind the existing optional document adapter boundary.
- Verify with the isolated local configuration and offline CAD preview.

---

### Task 1: Add automatic structured intake to generation

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py`
- Test: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: `RequirementsUseCaseService(repository, project_id, model, profile_id, provider_id, model_id).create_draft()` and `.apply_draft()`.
- Produces: an audit-backed intake event followed by the existing five-stage generation result.

- [x] **Step 1: Write the failing test**

Add a test that calls `services.generation("robot").generate("robot", requirement_text="操作员应在 2 秒内接收告警；系统应支持人工接管")` with an empty graph and asserts that the graph contains a `USE_CASE`, `OPERATIONAL_SCENARIO`, and `ACTIVITY`, the intake audit event exists, and R→F→L→P→V&V is complete.

- [x] **Step 2: Run the focused test to verify it fails**

Run:

```bash
./.venv/bin/pytest -q tests/e2e/test_vertical_model_generation.py -k automatic_structured_intake
```

Expected: FAIL because generation currently creates raw Requirements through `RequirementInputService` and does not compile the use-case intake records.

- [x] **Step 3: Implement the minimal integration**

In `ModelGenerationService._ensure_input`, detect explicit text/document input. If the request has new input, instantiate `RequirementsUseCaseService` with `getattr(self.runtime, "model", None)` and runtime metadata, create the draft from `text` or selected/all document IDs, apply it, and record `model_generation.input_intake` with draft/status/revision metadata. If no new input exists, retain the current existing-graph path. Do not call a model when `self.runtime` has no model.

- [x] **Step 4: Run focused tests**

```bash
./.venv/bin/pytest -q tests/e2e/test_vertical_model_generation.py -k automatic_structured_intake
./.venv/bin/pytest -q tests/application/test_requirements_use_case.py tests/e2e/test_vertical_model_generation.py
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/rflp_lite/application/model_generation.py tests/e2e/test_vertical_model_generation.py
git commit -m "feat: auto-intake requirements before model generation"
```

### Task 2: Prove document-format input and preserve delivery evidence

**Files:**
- Modify: `tests/adapters/test_document_intelligence.py`
- Modify: `tests/e2e/test_local_product_acceptance.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Consumes: `LocalDocumentParser`, `ProjectService.ingest`, and the automatic generation path from Task 1.
- Produces: a local acceptance proof that document regions, intake entities, RFLP/V&V, SysML, and design deliverables remain in one project.

- [x] **Step 1: Write format and end-to-end assertions**

Add a minimal in-memory DOCX fixture using `zipfile` and WordprocessingML, assert page-aware regions, and extend the local acceptance test to generate from an ingested document without calling the standalone draft/apply API. Keep PDF parsing covered through the existing optional dependency test boundary rather than downloading or starting OCR/model services.

- [x] **Step 2: Run focused acceptance tests**

```bash
./.venv/bin/pytest -q tests/adapters/test_document_intelligence.py tests/e2e/test_local_product_acceptance.py
```

Expected: PASS with no network connections.

- [x] **Step 3: Document the one-request path**

Update the product capability/status text to state that `/analysis` and `analyze generate` automatically compile document/text intake before RFLP generation, while the standalone intake API remains the human-review entry point.

- [x] **Step 4: Commit**

```bash
git add tests/adapters/test_document_intelligence.py tests/e2e/test_local_product_acceptance.py README.md docs/DEVELOPMENT_STATUS.md
git commit -m "test: verify document to model generation path"
```

### Task 3: Run the local-only verification gate and push

**Files:**
- Verify: `src/rflp_lite/application/model_generation.py`
- Verify: `tests/e2e/test_local_product_acceptance.py`

- [x] **Step 1: Run local-only checks**

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python -m pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
git diff --check
```

Expected: all local tests pass; remote FreeCAD remains skipped and no model endpoint is contacted.

- [x] **Step 2: Commit and push**

```bash
git add docs/superpowers/specs/2026-09-18-automatic-document-to-model-design.md docs/superpowers/plans/2026-09-18-automatic-document-to-model.md
git commit -m "docs: define automatic document to model intake"
git push origin codex/web-audit-2026-08-18
```
