# Intake-aware 结构化 LLM 纵向主链实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the real structured-provider branch can start from document intake and produce a complete editable R→F→L→P→V&V ModelGraph without starting a model or server.

**Architecture:** Extend the existing structured-model test fixture with an explicit `supports_requirements_intake` capability and a schema-valid intake response. Run the public application generation entry point with repository-backed source regions, then verify the existing traceability, SysML, and deliverable projections. Production behavior changes only if the acceptance test exposes a missing capability boundary.

**Tech Stack:** Python 3.12, pytest, existing SQLite repository, `StructuredModelRuntime`, `ModelGenerationService`, JSON Schema, SysML v2 subset and deliverable services.

## Global Constraints

- Do not start a local model, remote model, web server, SSH session, or FreeCAD process.
- Use only the existing in-process deterministic fake provider and repository APIs.
- Preserve the stage-only runtime compatibility branch.
- Do not weaken schema validation, traceability completion, CAS revision checks, or placeholder review rules.

---

### Task 1: Commit the approved design and inspect the existing fixture

**Files:**
- Create: `docs/superpowers/specs/2026-09-19-intake-aware-vertical-acceptance-design.md`
- Create: `docs/superpowers/plans/2026-09-19-intake-aware-vertical-acceptance.md`
- Modify: `docs/superpowers/README.md`

- [x] **Step 1: Record the design and plan**

  The design defines a single provider fixture that supports both `requirements.use_case` and `vertical.*`, and explicitly excludes network/model execution.

- [ ] **Step 2: Commit the design documents before implementation**

```bash
git add docs/superpowers/specs/2026-09-19-intake-aware-vertical-acceptance-design.md docs/superpowers/plans/2026-09-19-intake-aware-vertical-acceptance.md docs/superpowers/README.md
git commit -m "docs: design intake-aware vertical acceptance"
```

Expected: one documentation commit; no source or test files are changed by this task.

### Task 2: Add an intake-aware structured provider fixture

**Files:**
- Modify: `tests/application/test_model_generation.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: existing `ScriptedModel.complete_json(request)` for `vertical.*` requests.
- Produces: `IntakeAwareScriptedModel.complete_json(request)` that returns a valid `requirements-use-case-draft.v1` payload for `requirements.use_case` and delegates all stage requests.

- [ ] **Step 1: Write the failing acceptance test**

  Add a test that creates a repository-backed document/source region, invokes `services.generation("robot").generate("robot", document_ids=("doc-1",))`, and asserts `result.status == "completed"`, `result.traceability.end_to_end_complete_count == 1`, and the provider call sequence starts with `requirements.use_case` followed by the five vertical stage lenses.

- [ ] **Step 2: Run the focused test to verify the capability is missing**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_intake_aware_structured_provider_generates_complete_document_model
```

Expected: FAIL because the fixture does not yet declare or answer the intake lens.

- [ ] **Step 3: Implement the minimal fixture branch**

  Add `supports_requirements_intake = True` and return a schema-valid intake payload for `requirements.use_case`, using `region-1` in every source-backed field:

```python
{
    "schema_version": "requirements-use-case-draft.v1",
    "source_document_ids": ["doc-1"],
    "system_context": {
        "name": "校园配送系统",
        "mission": "完成校园配送",
        "attributes": {"platform_type": "robot", "capture_source": "llm"},
        "source_refs": ["region-1"],
    },
    "entities": [{
        "local_ref": "actor_operator", "kind": "stakeholder",
        "name": "配送运营人员", "attributes": {"role": "任务运营"},
        "source_refs": ["region-1"], "confidence": 0.9,
    }],
    "requirements": [{
        "local_ref": "requirement_delivery",
        "statement": "系统应完成校园配送", "level": "system",
        "type": "functional", "obligation": "系统应",
        "verification_method": "test", "constraints": [],
        "source_refs": ["region-1"], "confidence": 0.9,
        "related_refs": [],
    }],
    "use_cases": [{
        "local_ref": "use_case_delivery", "name": "执行配送",
        "goal": "完成校园配送", "primary_actor_refs": ["actor_operator"],
        "preconditions": [], "postconditions": [],
        "scenario_refs": ["scenario_delivery"],
        "requirement_refs": ["requirement_delivery"],
        "source_refs": ["region-1"], "confidence": 0.9,
    }],
    "scenarios": [{
        "local_ref": "scenario_delivery", "kind": "operational_scenario",
        "name": "校园配送场景", "description": "运营人员提交任务并完成配送",
        "actor_refs": ["actor_operator"],
        "steps": [{"order": 1, "actor_ref": "actor_operator", "action": "提交配送任务", "guard": ""}],
        "branches": [], "requirement_refs": ["requirement_delivery"],
        "source_refs": ["region-1"], "confidence": 0.9,
    }],
    "clarifications": [], "diagnostics": [],
}
```

- [ ] **Step 4: Run the focused test to verify the provider branch**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_intake_aware_structured_provider_generates_complete_document_model
```

Expected: PASS; the call log contains intake plus five vertical lenses, and no `legacy_requirement_input` mode is recorded.

### Task 3: Assert full artifacts and source traceability

**Files:**
- Modify: `tests/application/test_model_generation.py`
- Modify: `docs/superpowers/plans/2026-09-19-intake-aware-vertical-acceptance.md`

- [ ] **Step 1: Extend the passing acceptance test with graph evidence**

  Assert the graph contains `SYSTEM`, `STAKEHOLDER`, `USE_CASE`, `OPERATIONAL_SCENARIO`, `ACTIVITY`, `REQUIREMENT`, `FUNCTION`, `LOGICAL_COMPONENT`, `PHYSICAL_BLOCK`, `VERIFICATION_CASE`, and `VALIDATION_CASE`; assert the Requirement retains `region-1` source/evidence IDs and `resolve_requirement_trace(...).complete` is true.

- [ ] **Step 2: Assert SysML round-trip and deliverable revision binding**

  Use `graph_to_sysml`/`sysml_to_graph` and `services.deliverables("robot").build("robot")`; assert restored entities/relations equal the source graph and the manifest revision/snapshot hash match the same graph.

- [ ] **Step 3: Verify focused acceptance and update the checklist**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_intake_aware_structured_provider_generates_complete_document_model
```

Expected: PASS with complete source trace, typed model, SysML round-trip, and deliverable evidence. Mark Tasks 2–3 complete in this plan.

### Task 4: Run the offline quality gates and commit

**Files:**
- Modify: `docs/superpowers/README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `README.md`

- [ ] **Step 1: Run the complete offline verification**

```bash
git diff --check
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python scripts/verify_full.py
```

Expected: all tests pass with the existing skip count; compileall, architecture metrics, Ruff, and import-linter pass.

- [ ] **Step 2: Document the stronger evidence boundary**

  State that the offline suite now covers both the rule fallback and the provider-shaped intake path; do not claim real provider quality or remote execution.

- [ ] **Step 3: Commit the implementation**

```bash
git add tests/application/test_model_generation.py docs/superpowers/plans/2026-09-19-intake-aware-vertical-acceptance.md docs/superpowers/README.md docs/DEVELOPMENT_STATUS.md README.md
git commit -m "test: verify intake-aware structured vertical chain"
```

- [ ] **Step 4: Push the current branch**

```bash
git push origin codex/web-audit-2026-08-18
```

Expected: the branch and origin point to the same new commit; working tree is clean.
