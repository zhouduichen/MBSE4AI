# `system_definition` Entity Identity Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align `system_definition` with existing System-of-Interest identity semantics and validate the contract before resuming lifecycle experiments.

**Architecture:** Keep ProposalCompiler fail-closed and keep `local_ref` proposal-scoped. Make task-specific semantics explicit in the prompt/schema, use a minimum active SYSTEM completion condition, and reject a second SYSTEM only in the `system_definition` identity validation path.

**Tech Stack:** Python 3.12, pytest, jsonschema, existing RFLP-Lite TaskSpec/ProposalCompiler/WorkflowRunner, Ollama `qwen3.5:9b-q8_0` for the live probe.

## Global Constraints

- Do not automatically rename duplicate `local_ref` values.
- Do not change CAS, repository write, workflow failure routing, or semantic-repair architecture.
- Keep the live probe at `max_output_tokens=4000` and vary no other model parameter.
- Preserve unrelated pre-existing `tests/mbse_benchmark/` worktree changes.

---

### Task 1: Encode the SYSTEM payload and TaskSpec contract

**Files:**
- Modify: `src/rflp_lite/methodology/tasks.py`
- Modify: `src/rflp_lite/resources/prompts/operational/system_definition.v1.md`
- Test: `tests/methodology/test_proposal_compiler.py`
- Test: `tests/methodology/test_prompt_contracts.py`

**Interfaces:**
- Produces a `system_definition` output contract with a dedicated SYSTEM payload schema and `CompletionCondition(minimum_entities=1)`.
- Keeps `TaskSpec.input_kinds` and `output_kinds` as `{EntityKind.SYSTEM}`.

- [ ] **Step 1: Add tests for the dedicated SYSTEM schema and minimum cardinality.**

```python
def test_system_definition_contract_describes_system_payload_and_cardinality():
    task = next(item for item in task_catalog() if item.id == "system_definition")
    contract = output_contract(task)
    payload = contract["properties"]["entities"]["items"]["properties"]["payload"]

    assert task.completion_condition.minimum_entities == 1
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == {
        "mission", "system_boundary", "objectives",
        "environment_assumptions", "exclusions", "open_questions",
    }
    assert contract["properties"]["updates"]["items"]["properties"]["field_patch"]["properties"]["payload"] == payload
```

- [ ] **Step 2: Run the focused test and verify it fails before implementation.**

Run: `pytest tests/methodology/test_proposal_compiler.py::test_system_definition_contract_describes_system_payload_and_cardinality -q`

Expected: FAIL because SYSTEM has no dedicated payload schema and the completion condition has no minimum.

- [ ] **Step 3: Implement the explicit SYSTEM schema and task completion condition.**

Add a local `system_payload_schema` in `output_contract()` with required fields `mission`, `system_boundary`, `objectives`, `environment_assumptions`, `exclusions`, and `open_questions`; use string arrays for list fields and an object with `inside`/`outside` string arrays for `system_boundary`. For `system_definition`, bind the update payload field to the same schema. Construct that TaskSpec with `CompletionCondition(frozenset({EntityKind.SYSTEM}), 1)`.

- [ ] **Step 4: Update the task prompt with the existing-vs-missing SYSTEM branch.**

The prompt must require exactly one update to the existing canonical SYSTEM when one exists, exactly one new SYSTEM when none exists, and no second System-of-Interest. It must tell the model to put the required semantic content in the SYSTEM payload.

- [ ] **Step 5: Run the focused contract tests.**

Run: `pytest tests/methodology/test_proposal_compiler.py tests/methodology/test_prompt_contracts.py -q`

Expected: PASS.

### Task 2: Preserve fail-closed identity and test all four cases

**Files:**
- Modify: `src/rflp_lite/methodology/validators/identity.py`
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Test: `tests/methodology/test_proposal_compiler.py`
- Test: `tests/methodology/validators/test_identity_validator.py`
- Test: `tests/runtime/test_task_specific_prompts.py`

**Interfaces:**
- Consumes `ValidationContext.task.id`, the prospective `Patch`, and active graph SYSTEM entities.
- Produces `identity_conflict` for a `system_definition` add when an active SYSTEM already exists.
- Keeps duplicate `local_ref` rejection in `parse_task_proposal()` and adds explicit global prompt guidance.

- [ ] **Step 1: Add the failing duplicate-ref and existing/missing SYSTEM tests.**

Cover an existing SYSTEM update, a missing SYSTEM add, duplicate `local_ref`, and a second SYSTEM identity conflict. Apply the valid existing-SYSTEM patch and assert revision increases by one while SYSTEM count remains one.

- [ ] **Step 2: Run the focused tests and verify the new behavior fails.**

Run: `pytest tests/methodology/test_proposal_compiler.py tests/methodology/validators/test_identity_validator.py -q`

Expected: the duplicate test may already pass; the identity-conflict test must fail because identity validation currently permits a second SYSTEM.

- [ ] **Step 3: Add the task-scoped identity cardinality guard.**

In `identity.validate()`, before iterating operations, collect active SYSTEM IDs. When `context.task.id == "system_definition"` and the patch contains `AddEntity` of kind SYSTEM while an active SYSTEM already exists, raise `MethodologyValidationError("identity_conflict", "system_definition cannot add a second active SYSTEM")`. Do not affect other tasks or update operations.

- [ ] **Step 4: Add proposal-level `local_ref` guidance to the common runtime suffix.**

State that every proposal `entities[i].local_ref` must be unique, it is only a temporary proposal reference, and relations may reference only context canonical IDs or proposal-local refs.

- [ ] **Step 5: Run all focused tests and lint.**

Run: `pytest tests/methodology/test_proposal_compiler.py tests/methodology/validators/test_identity_validator.py tests/runtime/test_task_specific_prompts.py -q && ruff check src/rflp_lite/methodology/tasks.py src/rflp_lite/methodology/validators/identity.py src/rflp_lite/runtime/structured_model.py`

Expected: PASS and `All checks passed!`.

### Task 3: Run deterministic regression and the narrow live Qwen probe

**Files:**
- Create: `docs/superpowers/artifacts/pr09/system-definition-contract-20260913.json`
- Modify: `scripts/pr09_output_budget_experiment.py` only if its fixture/metrics cannot express the new branch.

**Interfaces:**
- Uses the committed local runtime and the existing remote Ollama endpoint.
- Records case, task status, finish reason, usage, compile/domain result, SYSTEM count, and revision delta.

- [ ] **Step 1: Run the full methodology test slice.**

Run: `pytest tests/methodology tests/runtime -q`

Expected: PASS.

- [ ] **Step 2: Run the live `system_definition × 10` probe at 4000 tokens.**

Use the same `qwen3.5:9b-q8_0` Ollama profile, fixture, temperature, seed, context, prompt version, and output budget as the previous 4000 matrix. Do not start the 23-task lifecycle yet.

- [ ] **Step 3: Record acceptance metrics.**

Require `finish_reason=stop`, `duplicate_local_ref=0`, `identity_conflict=0` for valid single-SYSTEM cases, `compile >= 95%`, `domain validation >= 95%`, correct SYSTEM cardinality, and zero invalid repository writes. If a run fails, retain the raw diagnostic and classify it before changing code.

- [ ] **Step 4: Update the artifact with the measured result and stop at the next gate.**

If stable, proceed next to the three-task chain `system_definition → stakeholder_analysis → stakeholder_requirements`; otherwise leave the 23-task lifecycle and semantic benchmark pending.
