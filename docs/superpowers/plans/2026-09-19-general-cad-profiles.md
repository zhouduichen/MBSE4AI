# 通用自然语言 CAD Profile 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the offline natural-language CAD path from bracket/base-only operations to reviewable housing, shaft and gear parameterized profiles.

**Architecture:** Keep `DesignIntentService` as the semantic boundary and compile each supported profile into the existing allowlisted `CadOperation` sequence. Preview and remote FreeCAD adapters consume the same operation vocabulary; annotation and design-rule adapters consume the resulting feature records without a second semantic parser.

**Tech Stack:** Python 3.12, JSON Schema, immutable domain records, vendor-neutral CAD port, deterministic preview adapter, pytest.

## Global Constraints

- Do not start local/remote models, servers, SSH, or FreeCAD during this slice.
- Do not execute natural-language text as code; only allowlisted operations may reach CAD adapters.
- Missing critical dimensions produce high-severity clarifications and block approval.
- Preview outputs remain `source_kind=development`; no manufacturing conclusion is auto-approved.
- Existing bracket/base operations and ModelGraph traceability remain backward compatible.

---

### Task 1: Extend profile intent contracts

**Files:**
- Modify: `src/rflp_lite/application/design_intent.py`
- Modify: `src/rflp_lite/resources/schemas/design_intent_draft.v1.json`
- Modify: `src/rflp_lite/resources/prompts/design_intent.v1.md`
- Test: `tests/application/test_design_intent.py`

- [x] Add tests that housing, shaft and gear phrases produce the target kind, profile parameters and high-severity questions for missing parameters.
- [x] Add bounded fallback parsing for `wall_thickness_mm`, shaft step parameters, and gear module/teeth/face width/bore.
- [x] Keep recommendations as `status=recommendation`; never treat inferred dimensions as approved facts.
- [x] Run `pytest tests/application/test_design_intent.py -q`.

### Task 2: Compile profile operations

**Files:**
- Modify: `src/rflp_lite/application/cad_workflow.py`
- Modify: `src/rflp_lite/domain/detail_design.py` only if a new immutable field is required
- Test: `tests/application/test_cad_workflow.py`

- [x] Add profile-specific operation builders with deterministic IDs and dependency order.
- [x] Generate shell, shaft-step and gear-blank/tooth-candidate operations only when required parameters are present.
- [x] Preserve selected structure option IDs, source requirement IDs and approval gating.
- [x] Test plan hashes differ when profile parameters differ and incomplete profiles remain unapprovable.

### Task 3: Consume features in both CAD adapters

**Files:**
- Modify: `src/rflp_lite/adapters/cad_preview.py`
- Modify: `src/rflp_lite/adapters/freecad_remote.py`
- Test: `tests/adapters/test_cad_preview.py`
- Test: `tests/adapters/test_freecad_remote_contract.py`

- [x] Add the shared operation names to both capability/validation allowlists.
- [x] Represent preview geometry deterministically and preserve profile parameters in `features`.
- [x] Extend the generated FreeCAD script with the same operations without executing any user text.
- [x] Test allowlist validation, stable artifact hashes, and script contract strings without connecting remotely.

### Task 4: Add feature-aware annotation and design-review evidence

**Files:**
- Modify: `src/rflp_lite/adapters/drawing_preview.py`
- Modify: `src/rflp_lite/adapters/design_rules_preview.py`
- Test: `tests/adapters/test_drawing_preview.py`
- Test: `tests/application/test_cad_workflow.py`

- [x] Emit diameter, bore, wall-thickness and profile-specific candidate annotations with collision-aware placement.
- [x] Add bounded DFM/DFA findings for missing/unsafe shell wall, shaft steps, gear bore and tool access.
- [x] Keep finding evidence, location and review status deterministic.

### Task 5: End-to-end verification and delivery

**Files:**
- Modify: `tests/e2e/test_local_product_acceptance.py`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`

- [x] Add an offline acceptance case covering all three new profiles through preview, review and ModelGraph application.
- [x] Run focused tests, `git diff --check`, full offline `scripts/verify_full.py`, and no-remote contract tests.
- [ ] Commit and push the completed slice.
