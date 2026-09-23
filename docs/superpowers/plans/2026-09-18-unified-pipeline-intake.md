# Unified Pipeline Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the five-stage generator and explicit 23-task pipeline share one automatic text/document-to-ModelGraph intake boundary.

**Architecture:** Add an application-level input preparation service that owns the existing RequirementsUseCaseService invocation and compatibility fallback. Inject it into generation and analysis services; keep CLI/Web as thin input transport layers. Preserve CAS, draft idempotency, provider capability checks, and offline-only verification.

**Tech Stack:** Python 3.11+, existing SQLite ModelRepository, pytest, FastAPI resource API, CLI v2, offline RuleRuntime.

## Global Constraints

- Do not start a local model or connect to a remote model/CAD server.
- Keep `ModelGraph` and CAS as the only write path.
- Keep the standalone human-review Intake API unchanged.
- Preserve stage-only injected runtime compatibility.
- Verify with isolated `RFLP_CONFIG_DIR` and `AI4MBSE_CAD_BACKEND=preview`.

---

### Task 1: Prove direct document-to-pipeline execution

**Files:**
- Modify: `tests/e2e/test_legacy_pipeline.py`
- Modify: `tests/interface/web/test_analysis_workflow.py`

- [x] Add tests that ingest the existing requirements fixture and call the pipeline without `requirements_input(...).ensure_*` or standalone draft/apply. Assert Use Case, Operational Scenario, Activity, 23 completed tasks, complete traceability, and a structured intake audit event.
- [x] Run the focused tests and verify they fail because the pipeline currently bypasses structured intake.

### Task 2: Centralize input preparation

**Files:**
- Create: `src/rflp_lite/application/input_preparation.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Modify: `src/rflp_lite/application/analysis_service.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Test: `tests/application/test_input_preparation.py`

- [x] Implement `InputPreparationService.prepare(project_id, requirement_text=None, document_ids=())` using the selected runtime model and metadata, with the stage-only compatibility fallback and the existing intake audit payload.
- [x] Replace the duplicated generation-side intake code with this service.
- [x] Add `AnalysisService.prepare_input(...)` and make pipeline callers use it before `run_pipeline`.
- [x] Cover offline fallback, capability selection, and empty-input behavior while preserving the existing draft idempotency contract.

### Task 3: Route CLI/Web through the shared service

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/cli_v2.py`
- Modify: `tests/interface/web/test_analysis_workflow.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

- [x] Pass pipeline text/document IDs through the application service and remove boundary-level direct `RequirementInputService` calls for that path.
- [x] Add CLI `analyze run --input` document parsing via the project ingest route or a documented `project ingest` + `analyze run` flow without a second manual compilation step.
- [x] Document that both `generate` and explicit `pipeline` consume the same input boundary.

### Task 4: Verify and push

- [x] Run focused tests, isolated full pytest, compileall, ruff, architecture metrics, import contracts, and `git diff --check`.
- [x] Commit and push the implementation and documents to `codex/web-audit-2026-08-18`.
