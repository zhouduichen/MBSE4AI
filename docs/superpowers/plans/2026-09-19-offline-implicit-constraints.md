# 离线需求隐含约束实施计划

> **执行约束：** 本计划只使用离线规则和现有测试夹具；不启动本机模型、远程模型、服务器、SSH 或 FreeCAD。

**Goal:** Preserve a small, reviewable set of implicit requirement constraints in the default offline intake path.

**Architecture:** Add a deterministic semantic inference helper beside the existing explicit unit parser. `RequirementsUseCaseService._fallback_payload` combines explicit and derived constraints, while the existing schema validation, explicit-wins merge, compiler, ModelGraph, RFLP and UI remain the single persistence path. Derived candidates are never promoted to approved facts.

**Tech Stack:** Python 3.12, existing requirement draft schema, typed ModelGraph compiler, FastAPI/Jinja, pytest.

## Global Constraints

- Derived constraints use `source=derived`, `operator=eq`, `value=1`, `unit=boolean`, low confidence, and a non-empty assumption.
- Only the five phrase families listed in the design spec are inferred.
- Explicit numeric constraints keep precedence over derived/LLM-inferred values.
- The fallback remains explicitly `degraded` and does not call a model.
- Existing RFLP and review gates remain unchanged.

## Task 1: Add deterministic inference beside explicit extraction

**Files:**
- Modify: `src/rflp_lite/application/requirement_intake.py`
- Modify: `src/rflp_lite/application/requirements_use_case.py`
- Test: `tests/application/test_requirement_intake.py` (create if absent)
- Test: `tests/application/test_requirements_use_case.py`

- [x] Add failing tests for phrase matching, source refs, low confidence, assumptions, and no inference for unrelated text.
- [x] Add `infer_requirement_constraints(statement, source_refs=())` with the five fixed semantic rule families.
- [x] Merge inferred constraints into fallback requirement payloads, set safety-like requirement type where applicable, and add bounded diagnostics.
- [x] Run focused requirement tests and verify explicit numeric values still win.

## Task 2: Expose candidates in the intake UI and downstream graph

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/requirements-use-case.html`
- Test: `tests/interface/web/test_requirements_use_case.py`
- Test: `tests/e2e/test_requirements_use_case_vertical_slice.py`

- [x] Show the count of derived constraints and the text “需人工确认” in each draft card when applicable.
- [x] Assert API drafts and applied Requirement payloads preserve `source=derived`, assumptions, and `requires_human_review`.
- [x] Assert existing behavior/traceability projection remains available.

## Task 3: Document and verify the vertical chain

**Files:**
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/superpowers/README.md`

- [x] Document offline derived constraints as development candidates, not approved engineering facts.
- [x] Run focused tests, full offline verification, `git diff --check`, Ruff, architecture metrics and import-linter.
- [ ] Commit and push to the current GitHub branch.
