# Confirmation Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every generated object pass through an explicit editable, confirm/reject, auditable state transition before downstream execution or formal output.

**Architecture:** Keep the existing JSON workbench and SQLite repository as the source of truth. Add small application-level state transition functions for scenarios and MBSE revisions, expose them through existing FastAPI routes and visible HTML forms, and gate execution/export on accepted state. Reuse the existing requirement review and concept candidate review APIs rather than creating a second persistence model.

**Tech Stack:** Python 3.11+, dataclasses/JSON, existing SQLite repository, FastAPI/Jinja2, pytest, Import Linter.

## Global Constraints

- Preserve fixed core fields and existing versioned domain-pack contracts.
- Keep scenario execution declarative-only; it must never execute user code or external systems.
- Keep formal concept-candidate acceptance gated by formally approved discipline evidence.
- Preserve existing JSON/API/CLI compatibility and existing untracked customer files.

---

### Task 1: Scenario review and edit state transitions

**Files:**
- Modify: `src/rflp_lite/application/scenarios.py`
- Modify: `src/rflp_lite/application/scenario_execution.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Test: `tests/application/test_scenarios.py`
- Test: `tests/application/test_web_facade.py`

**Interfaces:**
- Add `revise_scenario(state, scenario_id, **fields) -> dict[str, object]`, preserving the scenario ID, setting status to `draft`, and recomputing its content hash.
- Add `review_scenario(state, scenario_id, decision) -> dict[str, object]`, accepting only `accepted` or `rejected` and recording the transition metadata in the workbench.
- `execute_scenario` must reject any scenario whose status is not `accepted`.

- [ ] **Step 1: Add failing tests for generated-scenario review, edit reset, and execution gate.**
- [ ] **Step 2: Run `pytest tests/application/test_scenarios.py -q` and verify the new tests fail.**
- [ ] **Step 3: Implement deterministic revision and review transitions, including required steps/outcomes validation.**
- [ ] **Step 4: Gate `execute_scenario` on `status == "accepted"`.**
- [ ] **Step 5: Run focused application tests and commit `feat: add scenario confirmation workflow`.**

### Task 2: Web scenario confirmation controls

**Files:**
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Test: `tests/interface/web/test_routes.py` or the existing scenario Web test module

**Interfaces:**
- Add `POST /w/{workspace_name}/requirements/scenarios/edit` for field updates that return the scenario to `draft`.
- Add `POST /w/{workspace_name}/requirements/scenarios/review` for `accepted`/`rejected` decisions.

- [ ] **Step 1: Add route tests asserting the forms and transition responses.**
- [ ] **Step 2: Add edit, confirm, reject, and disabled-execution presentation to the scenario template.**
- [ ] **Step 3: Run Web scenario tests and verify accepted scenarios expose execution while drafts do not.**
- [ ] **Step 4: Commit `feat: expose scenario review controls`.**

### Task 3: MBSE generation and confirmation workflow

**Files:**
- Modify: `src/rflp_lite/application/mbse_modeling.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-graph.html`
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Test: `tests/application/test_mbse_modeling.py`
- Test: `tests/interface/web/test_routes.py` or existing Web test module

**Interfaces:**
- `generate_mbse_revision` sets a model-level `status="review"` and keeps generated elements as `candidate`.
- Add `review_mbse_element(state, element_id, decision) -> dict[str, object]` for candidate/accepted/rejected element states.
- Add `confirm_mbse(state) -> dict[str, object]` which requires at least one accepted use case and activity, then sets `mbse.status="accepted"`.
- Add visible POST routes for generation, element review, and model confirmation; export remains read-only and requires an accepted model.

- [ ] **Step 1: Add tests for generation status, element review, model confirmation, and export gating.**
- [ ] **Step 2: Run focused MBSE tests to confirm failure before implementation.**
- [ ] **Step 3: Implement state transitions and route/template controls.**
- [ ] **Step 4: Run focused tests and commit `feat: close MBSE review loop`.**

### Task 4: Concept candidate Web review controls

**Files:**
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/concept-design.html`
- Test: `tests/interface/web/test_api_v1.py` or existing Web concept test module

**Interfaces:**
- Add Web POST route `/w/{workspace_name}/concept-design/review` delegating to `WebFacade.review_layout_candidate`.
- Render one explicit review action per candidate, showing formal-evidence gating and the recorded decision.

- [ ] **Step 1: Add route/template tests for accepted/rejected review records.**
- [ ] **Step 2: Implement the Web route and controls without weakening formal evidence checks.**
- [ ] **Step 3: Run focused concept Web tests and commit `feat: expose concept candidate review`.**

### Task 5: Full regression and user-facing documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: all existing tests plus new focused tests

- [ ] **Step 1: Document the actual closed-loop sequence and each confirmation gate.**
- [ ] **Step 2: Run `.venv/bin/pytest -q`.**
- [ ] **Step 3: Run `.venv/bin/lint-imports`, `git diff --check`, and `.venv/bin/python -m build --wheel --no-isolation`.**
- [ ] **Step 4: Run the concept acceptance command and a Web/API smoke test.**
- [ ] **Step 5: Commit `docs: explain confirmation closure workflow`.**
