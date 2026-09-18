# Unified Engineering Product Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose one application-level flow that turns natural-language or document requirements into a revision-bound R→F→L→P→V&V model, with optional concept-design and natural-language CAD handoffs, without auto-approving engineering changes.

**Architecture:** Compose existing generation, concept, CAD, and deliverable services behind a thin `EngineeringProductFlowService`. The service owns orchestration and status translation only; existing domain contracts, persistence, approval gates, and deterministic offline adapters remain unchanged.

**Tech Stack:** Python 3, dataclasses, existing SQLite repositories, Starlette/FastAPI-compatible web layer, pytest, Ruff, repository architecture verifier.

## Global Constraints

- Do not start a local server or run a local/remote LLM.
- Keep tests offline and deterministic with `TestClient`, `VerticalRuleRuntime`, preview CAD, and temporary config/workspaces.
- Do not auto-approve, execute, or apply concept/CAD changes.
- Preserve unrelated working-tree changes and existing public contracts.

## Task 1: Implement the application product-flow orchestrator

- [x] Create `src/rflp_lite/application/product_flow.py`.
- [x] Add an immutable `ProductFlowResult` with `status`, `generation`, `concept`, `cad`, `deliverable`, `revision`, and `snapshot_hash`, plus `as_dict()` using existing primitive conversion helpers.
- [x] Add `EngineeringProductFlowService.run(project_id, *, requirement_text=None, document_ids=(), include_concept=False, optimize_concept=True, cad_intent_text=None)`.
- [x] Delegate generation to the existing five-stage service; build a deliverable snapshot after generation and after any accepted draft/plan records are persisted.
- [x] Translate concept `InputRequired` to `needs_input` with the suggestion payload; translate CAD draft clarification to `needs_clarification`; translate a ready CAD plan to `needs_approval` without executing it.
- [x] Add `tests/application/test_product_flow.py` covering RFLP-only completion, concept input, CAD clarification, CAD approval, and revision/snapshot binding.
- [x] Run the focused application tests with isolated `RFLP_CONFIG_DIR` and preview CAD backend.

## Task 2: Expose the flow through composition root and API

- [x] Add `V2Services.product_flow()` in `src/rflp_lite/bootstrap/v2.py`, composing existing project-scoped services.
- [x] Add `POST /projects/{project_id}/engineering-flow` in `src/rflp_lite/interface/web/resource_api.py` with explicit input parsing and the existing error mapping.
- [x] Add `tests/interface/web/test_product_flow_api.py` for document-backed completion, `needs_input`, `needs_clarification`, and `needs_approval` responses.
- [x] Keep API responses JSON-safe and avoid exposing provider internals.

## Task 3: Prove document-to-product and deliverable binding

- [x] Extend `tests/e2e/test_local_product_acceptance.py` with a focused product-flow acceptance test proving document ingestion, complete RFLP generation, traceability source/evidence links, and exported deliverable revision/hash consistency.
- [x] Reuse the existing document intelligence tests/fixtures for DOCX/PDF source-region behavior; only add coverage where it closes a product-flow gap.
- [x] Verify SysML export/re-import remains part of the acceptance path through the existing local product acceptance suite.

## Task 4: Update product documentation and verify the repository

- [x] Update `README.md` with the one-entry product flow, status semantics, offline test command, and explicit approval boundary.
- [x] Run focused tests, the local product acceptance tests, Ruff, import-linter, and `scripts/verify_full.py` with isolated config and preview CAD.
- [x] Review the diff for scope, commit the implementation, and push the resulting commit to the configured GitHub remote only after verification passes.

## Completion evidence

- A single offline API/application call can produce a complete R→F→L→P→V&V graph and a revision-bound deliverable.
- Optional concept/CAD stages return actionable intermediate states instead of silently mutating engineering artifacts.
- Document evidence, traceability, SysML round-trip, and deliverable hash/revision are covered by tests.
- Repository architecture and full offline verification pass.

## Follow-up slice: carry explicit CAD structure selection through the product flow

- [x] Extend `EngineeringProductFlowService.run` with `selected_structure_option_id: str = ""` and pass it to `CadWorkflowService.create_plan` only when the caller explicitly supplies it.
- [x] Extend `POST /projects/{project_id}/engineering-flow` to accept the same field; preserve the existing clarification/approval states and unknown-option error behavior.
- [x] Add application/API coverage proving `bracket-gusseted-plate` produces `add_rib` operations and an omitted selection does not choose a structure implicitly.
- [x] Update the design contract and README example, run the isolated focused tests and full offline verification, then commit and push.
