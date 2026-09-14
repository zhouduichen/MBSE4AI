# Web Per-Run LLM Profile Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow each Web analysis request to select a saved LLM Profile without changing the global active Profile.

**Architecture:** Resolve a request-scoped profile through the existing Settings/Profile service and pass the resulting config into the existing RuntimeFactory. Keep the existing active-profile and offline fallback behavior when no profile ID is supplied; expose only secret-free profile summaries in the page.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, browser Fetch API, pytest, existing typed ModelGraph and RuntimeFactory.

## Global Constraints

- ModelGraph remains the only model truth and no new persistence state is introduced.
- API keys remain in the existing keyring/session boundary and never enter HTML or public JSON.
- Tests use `VerticalRuleRuntime` or other explicit stubs; never start or call a local model.
- The legacy 23-task pipeline remains compatible.

---

### Task 1: Add request-scoped Profile resolution

**Files:**
- Modify: `src/rflp_lite/application/settings_service.py`
- Modify: `src/rflp_lite/bootstrap/v2.py`
- Test: `tests/application/test_services.py`

**Interfaces:**
- Add `SettingsService.profile_config(profile_id: str) -> Mapping[str, object]` delegating to `LLMProfileService.config_for_profile`.
- Add `profile_id: str | None = None` to `V2Services.analysis()` and `V2Services.generation()`.
- When `profile_id` is present, pass `self.settings.profile_config(profile_id)` to `RuntimeFactory.select`; otherwise preserve explicit `runtime_config`, then active config.

- [ ] **Step 1: Write the failing service test**

Create two saved profiles, keep the first active, construct services with `VerticalRuleRuntime`, request the second profile, and assert the generated Run records the second profile while the first remains active.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `./.venv/bin/python -m pytest -q tests/application/test_services.py -k profile`

Expected: FAIL because the service methods do not accept or resolve `profile_id`.

- [ ] **Step 3: Implement the minimal resolution path**

Use the exact priority rule in `V2Services`:

```python
config = (
    self.settings.profile_config(profile_id)
    if profile_id
    else self._runtime_config
    if self._runtime_config is not None
    else self.settings.active_config()
)
```

- [ ] **Step 4: Run the focused test and verify it passes**

Run: `./.venv/bin/python -m pytest -q tests/application/test_services.py -k profile`

Expected: PASS.

### Task 2: Thread Profile selection through Web API and page

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Test: `tests/interface/web/test_vertical_generation_api.py`
- Test: `tests/interface/web/test_analysis_workflow.py`

**Interfaces:**
- Analysis JSON accepts `profile_id` as an optional string.
- Analysis view exposes `model_profiles` (secret-free summaries) and `selected_profile_id`.
- The page sends `profile_id` only when the selector has a non-empty value.

- [ ] **Step 1: Write failing API/page assertions**

Assert a generated response using a non-active saved Profile has that Profile in `run.model_profile`, the active ID is unchanged, and the page contains a Profile selector plus `profile_id` request field.

- [ ] **Step 2: Run focused Web tests and verify they fail**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py -k profile`

Expected: FAIL because the API and template do not accept or render request-scoped Profile selection.

- [ ] **Step 3: Implement API/view/template wiring**

Normalize `profile_id`, pass it to `services.generation(project_id, profile_id=profile_id)` or `services.analysis(project_id, profile_id=profile_id)`, and render only `id`, `label`, `kind`, `provider`, `model`, and enabled status. Preserve the existing empty-value fallback to active Profile.

- [ ] **Step 4: Run focused Web tests and verify they pass**

Run: `./.venv/bin/python -m pytest -q tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_analysis_workflow.py -k profile`

Expected: PASS.

### Task 3: Run the complete offline gate and push

**Files:**
- Verify: all modified files and tests from Tasks 1–2.

- [ ] **Step 1: Run complete verification**

Run: `./.venv/bin/python scripts/verify_full.py`

Expected: compileall, full pytest, architecture metrics, Ruff, and import-linter all pass; no model process or local endpoint is used.

- [ ] **Step 2: Inspect and commit**

Run `git diff --check`, inspect `git status --short`, then commit with `feat: select LLM profile per web run`.

- [ ] **Step 3: Push the current branch**

Run `git push origin codex/web-audit-2026-08-18` and verify `HEAD` equals the remote branch tip.
