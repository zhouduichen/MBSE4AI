# 离线需求实体与属性捕获实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make document/text intake capture bounded system, stakeholder and concern entities with traceable attributes in the typed ModelGraph.

**Architecture:** Add a deterministic lexical rule table beside the existing requirement constraint extractor. The fallback payload emits `system_context.attributes` plus source-backed entities; the existing schema preparation, compiler and repository remain the persistence path used by both offline and structured LLM intake.

**Tech Stack:** Python 3.12, JSON Schema, existing IntakeDraft/ModelGraph compiler, pytest.

## Global Constraints

- No model, server, SSH or FreeCAD execution.
- Rules are bounded and deterministic; no unmatched open-domain entity is promoted to fact.
- Derived entities retain source refs, low confidence and human-review semantics.
- Existing local refs and relations remain stable for actor/scenario inputs.

---

### Task 1: Add bounded entity/profile inference

**Files:**
- Modify: `src/rflp_lite/application/requirement_intake.py`
- Modify: `src/rflp_lite/application/requirements_use_case.py`
- Test: `tests/application/test_requirement_intake.py`
- Test: `tests/application/test_requirements_use_case.py`

- [x] Add rule-table tests for platform attributes, multiple stakeholders, concerns, refs and low confidence.
- [x] Implement `infer_requirement_entities(text, source_refs=())` and system profile inference without changing raw statements.
- [x] Add derived entities/attributes and bounded diagnostics to `_fallback_payload`.

### Task 2: Persist system attributes through structured intake

**Files:**
- Modify: `src/rflp_lite/resources/schemas/requirements_use_case_draft.v1.json`
- Modify: `src/rflp_lite/application/requirements_use_case.py`
- Modify: `src/rflp_lite/resources/prompts/requirements_use_case.v1.md`
- Test: `tests/application/test_requirements_use_case.py`

- [x] Allow `system_context.attributes` in the draft schema and normalize it in `_prepare_payload`.
- [x] Copy system attributes into the compiled System payload without allowing arbitrary patch fields.
- [x] Assert a structured fake LLM payload preserves attributes through apply.

### Task 3: Verify downstream deliverables

**Files:**
- Modify: `tests/e2e/test_requirements_use_case_vertical_slice.py`
- Modify: `tests/e2e/test_local_product_acceptance.py`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`

- [x] Assert document/text intake persists system/stakeholder/concern attributes and source trace.
- [ ] Run focused tests, `git diff --check`, full offline `scripts/verify_full.py`, Ruff, architecture metrics and import-linter.
- [ ] Commit and push the slice.
