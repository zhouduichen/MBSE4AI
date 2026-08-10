# Professional UI Copy Cleanup Implementation Plan

> **For agentic workers:** Inline execution is approved for this task.

**Goal:** Remove developer-facing explanatory copy from the formal Web UI while preserving business data, statuses, actions, validation errors, and technical documentation.

**Architecture:** Keep the existing Jinja templates, routes, presenters, and application services unchanged except where dashboard guidance text is directly rendered as page copy. Replace explanatory paragraphs and safety/implementation notes with compact business labels or remove them when the surrounding field already conveys the meaning.

**Tech Stack:** FastAPI, Jinja2 templates, existing pytest/TestClient suite.

## Global Constraints

- Modify formal Web UI copy only; do not change persistence, APIs, workflow state, or technical documentation.
- Keep actionable validation failures and status values visible.
- Do not remove identifiers, counts, source data, review decisions, or operation buttons.
- Preserve customer-provided untracked files.

### Task 1: Inventory and normalize formal page copy

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/*.html`
- Modify: `src/rflp_lite/application/requirements_workbench.py` for generated draft-map copy

- [ ] Remove explanatory paragraphs about implementation, demo behavior, local persistence, optionality, and “next step” narration from formal pages.
- [ ] Keep concise labels for status, source, count, and operation outcomes.
- [ ] Keep error banners and field-level validation messages.

### Task 2: Protect the copy contract with page tests

**Files:**
- Modify: `tests/interface/web/test_pages.py`
- Modify: `tests/application/test_requirements_workbench.py`

- [ ] Add assertions that formal pages omit the known developer-facing sentence and retain the requirement ledger, review controls, and status labels.
- [ ] Run the focused Web page tests.

### Task 3: Full verification and commit

- [ ] Run full pytest, import-linter, `git diff --check`, and wheel build.
- [ ] Stage only the intended UI, facade, test, and plan files.
- [ ] Commit as `style: professionalize formal web ui copy`.
