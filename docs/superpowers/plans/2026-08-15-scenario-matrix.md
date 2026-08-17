# Scenario Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a deterministic 12–20 item scenario matrix from one submitted requirement and present each scenario as a collapsed, expandable card in the existing scenario module.

**Architecture:** Keep the existing scenario JSON/API, edit/review, execution, and MBSE sequence routes. Add a deterministic matrix generator in `application/scenarios.py` using the existing domain-pack dimensions and claims. Call it from unified submission and scenario-page backfill, then render the existing scenario objects with native HTML `<details>` cards.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, SQLite workbench JSON, pytest, existing domain-pack JSON.

## Global Constraints

- Preserve the existing `scenarios` JSON/API shape; new fields are additive.
- Generated scenarios are `accepted` and remain executable by the existing declarative executor.
- Keep user-created and manually revised scenarios during regeneration.
- Use a deterministic limit of 16 generated scenarios.
- Do not add a separate intelligent-completion action.
- LLM failure must not clear scenarios or block RFLP/MBSE generation.

---

### Task 1: Define failing matrix and UI tests

**Files:**
- Modify: `tests/application/test_scenarios.py`
- Modify: `tests/interface/web/test_pages.py`
- Modify: `tests/interface/web/test_auto_requirements.py`

**Interfaces:**
- Consumes: existing scenario helpers and the urban-medical domain-pack fixture.
- Produces: tests defining `generate_scenario_matrix(state, pack, limit=16)` and the collapsed-card contract.

- [x] **Step 1: Write the application test**

Assert 12–16 accepted scenarios, unique IDs, non-empty `dimensions` and `requirement_ids`, `generation_mode == "scenario-matrix"`, and all four types: `normal`, `exception`, `failure`, `emergency`. Add a second test proving a manually added scenario survives regeneration.

- [x] **Step 2: Run the test and confirm failure**

```bash
.venv/bin/python -m pytest -q tests/application/test_scenarios.py -k matrix
```

Expected: import or assertion failure because the generator does not exist.

- [x] **Step 3: Define the web assertions**

After submitting one requirement, assert the scenario API count is 12–16 and the HTML contains at least 12 `<details class="scenario-card"` elements, no `open` attribute, `场景维度`, `展开详情`, all detail labels, the execute action, and the MBSE sequence link. Update the existing auto-flow test to require multiple scenarios.

- [x] **Step 4: Run focused web tests**

```bash
.venv/bin/python -m pytest -q tests/interface/web/test_pages.py::test_scenario_page_generates_output_without_manual_scenario_fields tests/interface/web/test_auto_requirements.py
```

Expected: failure until Tasks 2–4 are complete.

### Task 2: Implement stable scenario-matrix generation

**Files:**
- Modify: `src/rflp_lite/application/scenarios.py`
- Test: `tests/application/test_scenarios.py`

**Interfaces:**
- Consumes: `state["claims"]`, `state["stakeholders"]`, existing scenarios, and domain-pack `scenario_dimensions`/`lifecycle_phases`.
- Produces: `generate_scenario_matrix(state: dict[str, object], pack: dict[str, object], *, limit: int = 16) -> dict[str, object]`.

- [x] **Step 1: Add the generator signature and immutable clone**

Add `SCENARIO_MATRIX_LIMIT = 16`; clamp the requested limit to 12–20 and clone the state with `canonical_json` before modifications. Derive the objective and `requirement_ids` from the first non-rejected claim.

- [x] **Step 2: Add representative rows**

Create stable rows for normal medical transfer, patient handoff, night/low visibility, rain, peak dense-city operation, communication loss, untrusted navigation, high wind, unavailable landing site, critical patient, life-threatening patient, thunderstorm diversion, GNSS interference, hospital-rooftop landing, disaster-zone response, and total-failure safe handling. Each row sets `scenario_type` (`normal`, `exception`, `failure`, or `emergency`) and dimensions such as `mission_phase`, `weather`, `visibility`, `system_state`, `medical_urgency`, `urban_context`, `connectivity`, and `time`.

- [x] **Step 3: Build complete scenario records**

Use `build_scenario` for title, description, actors, preconditions, steps, expected outcomes, faults, and `requirement_ids`. Add `dimensions`, `scenario_type`, `lifecycle_phase`, `producer="system"`, `generated_from`, and `generation_mode="scenario-matrix"`. Use a canonical hash of claim ID, type, title, and dimensions for stable IDs. Select actor names from matching stakeholders and always include `系统`.

- [x] **Step 4: Preserve manual data and deduplicate**

Keep scenarios whose producer is not `system`, whose mode is not `minimum-input`/`scenario-matrix`, or whose automatic record has revision > 1 or review history. Replace only untouched automatic rows, cap generated rows at `limit`, and sort deterministically.

- [x] **Step 5: Run application tests**

```bash
.venv/bin/python -m pytest -q tests/application/test_scenarios.py -k "matrix or generated_scenario"
```

Expected: PASS.

### Task 3: Integrate matrix generation into unified submission and backfill

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Test: `tests/interface/web/test_auto_requirements.py`

**Interfaces:**
- Consumes: `load_mbse_domain_pack`, `generate_scenario_matrix`, `confirm_requirements`, `generate_model`, `approve_workbench_baseline`, and `generate_mbse_revision`.
- Produces: multi-scenario state after one submit and after opening an old empty/single-scenario workbench.

- [x] **Step 1: Replace the single-scenario fallback in `_auto_complete_requirements`**

After `auto_accept_and_bridge_discovery`, call:

```python
result = generate_scenario_matrix(result, pack, limit=16)
```

Run this before `confirm_requirements`, `generate_model`, and `generate_mbse_revision` so all scenarios are accepted and available to MBSE.

- [x] **Step 2: Update `prepare_requirement_scenarios`**

Load the default pack and call the matrix generator when there are no scenarios or only untouched automatic minimum-input scenarios. Save with `scenario.matrix.generated` and retain manual/revised scenarios.

- [x] **Step 3: Add integration tests**

Assert that normal submit and no-LLM submit both produce 12–16 accepted scenarios, non-empty RFLP, and non-empty MBSE; assert that a manually added scenario remains.

- [x] **Step 4: Run integration tests**

```bash
.venv/bin/python -m pytest -q tests/interface/web/test_auto_requirements.py tests/interface/web/test_pages.py::test_requirements_page_runs_one_click_flow_from_current_input tests/interface/web/test_pages.py::test_scenario_page_generates_output_without_manual_scenario_fields
```

Expected: PASS.

### Task 4: Implement collapsed expandable scenario cards

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_pages.py`

**Interfaces:**
- Consumes: existing scenario fields plus `scenario_type`, `dimensions`, and `lifecycle_phase`.
- Produces: default-collapsed cards with existing edit, delete, execute, and sequence actions preserved.

- [x] **Step 1: Use native details/summary markup**

Wrap each scenario in `<details class="scenario-card" data-scenario-type="{{ scenario.scenario_type|default('normal') }}">`. Put title, lifecycle phase, type, status, and linked-requirement count in `<summary>`, with no `open` attribute. Put the existing edit form and action links in the body. Render `场景维度` from the dimensions mapping and keep all fields visible after expansion.

- [x] **Step 2: Add responsive card styling**

Add `.scenario-card`, `.scenario-card-summary`, `.scenario-card-body`, and focus/marker styles to the existing CSS. Use native details behavior; add no JavaScript.

- [x] **Step 3: Run page tests**

```bash
.venv/bin/python -m pytest -q tests/interface/web/test_pages.py tests/interface/web/test_auto_requirements.py
```

Expected: PASS with at least 12 collapsed cards and all existing scenario actions.

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: full existing suite

**Interfaces:**
- Consumes: completed generator, unified flow, and collapsed-card UI.
- Produces: documented multi-scenario workflow and verified implementation.

- [x] **Step 1: Document the workflow**

Update the requirements workflow to state that “提交并分析” creates a default 16-scenario matrix and that `/requirements/scenarios` shows collapsed cards expandable into full analysis.

- [x] **Step 2: Run all verification**

```bash
git diff --check
env -u RFLP_LLM_BASE_URL -u RFLP_LLM_MODEL -u RFLP_LLM_API_KEY RFLP_CONFIG_DIR=/tmp/rflp-test-config.scenario-matrix .venv/bin/python -m pytest -q
```

Expected: all tests pass, with only the known Starlette/httpx deprecation warning.

- [x] **Step 3: Verify the active local workspace**

Check `/api/v1/workspaces/<workspace>/requirements` after one submit: scenario count 12–16, all four scenario types present, and every scenario has a non-empty `requirement_ids` list.

- [ ] **Step 4: Commit the implementation**

```bash
git add src/rflp_lite/application/scenarios.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/templates/requirements-scenarios.html src/rflp_lite/interface/web/static/app.css tests/application/test_scenarios.py tests/interface/web/test_pages.py tests/interface/web/test_auto_requirements.py README.md docs/DEVELOPMENT_STATUS.md
git commit -m "feat: generate expandable scenario matrix"
```
