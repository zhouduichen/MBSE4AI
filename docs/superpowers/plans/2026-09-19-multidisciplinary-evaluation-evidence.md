# Multidisciplinary Evaluation Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the offline 2.2 multidisciplinary evaluation chain auditable by persisting approval/validity evidence and candidate-level optimizer feedback without promoting development evidence to formal evidence.

**Architecture:** Keep `DisciplineEvaluation` as the stable cross-adapter record and use its existing `validity` key/value payload for execution-time evidence. Add a deterministic summary to `ConceptRunResult`; the existing ConceptStore, Web/API serialization, and engineering deliverable projection then carry the same evidence without a second source of truth.

**Tech Stack:** Python 3.12, frozen domain dataclasses, SQLite audit records, FastAPI/Jinja templates, pytest.

## Global Constraints

- Do not run a server, local model, remote model, SSH, FreeCAD, CFD, or FEA experiment.
- Keep built-in analytical evaluators marked `development`; only a complete approved profile may produce `formal`.
- Preserve existing routes and fields; all new response fields are additive.
- Keep deterministic hashes, cache behavior, and ModelGraph revision semantics unchanged.

---

### Task 1: Persist evaluation evidence and candidate summary

**Files:**
- Modify: `src/rflp_lite/application/discipline_batch.py`
- Modify: `src/rflp_lite/application/concept_design_service.py`
- Test: `tests/application/test_discipline_batch.py`
- Test: `tests/application/test_concept_project_service.py`

**Interfaces:**
- `evaluate_candidates(...)` continues returning `EvaluationBatch`; each successful or cached `DisciplineEvaluation.validity` records input parameters, validity-domain status, and approval evidence metadata.
- `ConceptRunResult.evaluation_summary` is an additive mapping containing candidate status, failed disciplines, formal status, optimizer front IDs, iteration feedback, and stop reason.

- [x] **Step 1: Add regression tests** for validity evidence on a built-in evaluation and for the concept run summary covering candidate/evaluation counts and Pareto feedback.
- [x] **Step 2: Run the focused tests** and confirm the new assertions pass after the implementation.
- [x] **Step 3: Implement deterministic evidence projection** in `discipline_batch.py`, including normalized input values, declared validity domain, `validity_status` (`within_domain`, `outside_domain`, or `not_declared`), validation dataset identifiers, error metrics, acceptance limits, and the existing approval diagnostics. Do not change the formal decision rule.
- [x] **Step 4: Add `evaluation_summary`** to `ConceptRunResult`, compute it from the final candidate/evaluation set and `OptimizationRun`, and make old persisted records default to an empty summary during `concept_run_from_payload()`.
- [x] **Step 5: Run the focused application tests** and confirm they pass.

### Task 2: Expose the evidence in Web and engineering deliverables

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/concept-design.html`
- Modify: `tests/interface/web/test_concept_design.py`
- Modify: `tests/application/test_deliverables.py`
- Modify: `tests/e2e/test_local_product_acceptance.py`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

**Interfaces:**
- Existing concept-design API response retains all fields and adds `evaluation_summary` plus populated evaluation `validity`.
- Existing `concept-design.json` artifact carries the same serialized run records through the existing audit projection.

- [x] **Step 1: Add API/page assertions** for evidence status, validity-domain status, candidate summary, and optimizer feedback.
- [x] **Step 2: Update the page rendering** to show the evidence state and concise approval/validity diagnostics while preserving the existing detailed JSON behavior.
- [x] **Step 3: Document that 2.2 now exports auditable analytical evidence and still distinguishes development from formal approval.**
- [x] **Step 4: Run focused Web/deliverable tests.**

### Task 3: Full offline verification and delivery

**Files:**
- No additional source files.

- [x] **Step 1: Run `scripts/verify_full.py` with an isolated config and `AI4MBSE_CAD_BACKEND=preview`.**
- [x] **Step 2: Run `git diff --check` and inspect the final diff.**
- [ ] **Step 3: Commit and push the implementation and plan to `codex/web-audit-2026-08-18`.**
