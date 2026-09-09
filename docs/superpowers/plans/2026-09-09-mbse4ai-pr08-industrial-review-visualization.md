# PR08 Industrial MBSE Review & Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or **superpowers:executing-plans** to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the PR08 industrial review layer so engineers can inspect, modify, trace, and audit generated MBSE results through deterministic projections and guarded application commands.

**Architecture:** Add pure typed projections under `src/rflp_lite/application/projections/`, add review commands beside existing application services, expose resource API routes, and render pages/SVG from projection output. Keep ModelGraph immutable and route all writes through Patch/CAS/revision/audit.

**Tech Stack:** Python 3.12, dataclasses, FastAPI, Jinja2, SQLite repository, pytest, Ruff, compileall, lint-imports.

## Global Constraints

- Preserve all user-owned uncommitted benchmark files and do not edit benchmark scores.
- Do not add a second ModelGraph or direct SQLite writes from routes/templates.
- Reuse `trace_rules.py`, `coverage_matrix.py`, `gates.py`, and existing workflow services.
- Keep projections pure, deterministic, and LLM-free.
- Commit each numbered slice separately where possible and run focused tests before moving on.

## Task 1: PR08-1 projection contracts and repository reads

- [ ] Add frozen ViewModels and projection modules in `src/rflp_lite/application/projections/` for common entity/status/issue aggregation, requirements, traceability, RFLP, behavior, assurance, and history.
- [ ] Extend `src/rflp_lite/repository/port.py` and `src/rflp_lite/repository/sqlite.py` with read-only revision/patch/run/step queries and snapshot loading needed by history.
- [ ] Add `tests/application/projections/test_requirements_projection.py`, `test_traceability_projection.py`, `test_rflp_projection.py`, `test_assurance_projection.py`, and `test_history_projection.py`.
- [ ] Run `./.venv/bin/python -m pytest -q tests/application/projections` and commit `feat(review): add industrial MBSE projection layer`.

## Task 2: PR08-2 review commands, requirements workbench, and matrix

- [ ] Add `src/rflp_lite/application/review_service.py` for accept/reject/edit/lock/unlock/re-analysis commands using `ModelService.apply_patch` and audit recording.
- [ ] Add requirements/detail/traceability JSON routes in `src/rflp_lite/interface/web/resource_api.py`, with CAS and locked error mapping.
- [ ] Add requirements, detail, and matrix pages/templates and navigation in `src/rflp_lite/interface/web/resource_pages.py` and `src/rflp_lite/interface/web/templates/`.
- [ ] Add `tests/interface/web/test_requirements_workbench.py`, `test_traceability_matrix.py`, and `test_review_actions.py`.
- [ ] Run focused application/web tests and commit `feat(review): add requirements workbench and traceability matrix`.

## Task 3: PR08-3 RFLP architecture and deterministic trace view

- [ ] Add deterministic RFLP SVG projection/rendering in `src/rflp_lite/application/projections/rflp.py` and `src/rflp_lite/diagrams/engineering/rflp.py`.
- [ ] Add RFLP and focused trace routes/pages with issue/gap links and filters.
- [ ] Add `tests/interface/web/test_rflp_view.py` and extend projection tests for invalid predicates and focus consistency.
- [ ] Run focused tests and commit `feat(review): add interactive RFLP architecture review`.

## Task 4: PR08-4 behavior and assurance workbenches

- [ ] Add operational, behavior, verification/validation, hazard/FMEA, gate, and repair projections using only existing entities and relations.
- [ ] Add behavior/assurance API routes and pages/templates, preserving explicit incomplete states for missing facts.
- [ ] Add `tests/interface/web/test_assurance_view.py` and behavior projection coverage.
- [ ] Run focused tests and commit `feat(review): add behavior and assurance workbenches`.

## Task 5: PR08-5 history, audit, and revision diff

- [ ] Add revision/patch/run/step/history projections and readable entity/payload/relation/status diffs.
- [ ] Add history and revision diff routes/pages and provenance links from review entities/issues.
- [ ] Add `tests/interface/web/test_history_diff.py` and end-to-end review story coverage.
- [ ] Run focused tests and commit `feat(review): add revision history and engineering diff`.

## Task 6: acceptance and handoff

- [ ] Run full pytest, compileall, Ruff, architecture metrics, and lint-imports without touching benchmark result files.
- [ ] Exercise the fixture review story and capture deterministic render/API evidence.
- [ ] Add `PR08_ACCEPTANCE_REPORT.md` with baseline/final commit, slice file list, tests, metrics, limitations, and honest incomplete items.
- [ ] Commit `docs(review): record PR08 acceptance report` and inspect final `git diff`/status.
