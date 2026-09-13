# Task-Level Relation Predicate Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make TaskSpec relation policies explicit and enforce them in the provider-facing TaskProposal schema for the first three operational tasks.

**Architecture:** Add an optional predicate allowlist to TaskSpec construction and pass it through PatchPolicy. The existing `proposal_schema()` already derives its relation enum from the policy, so generated proposals are constrained before endpoint validation while Compiler behavior remains unchanged.

**Tech Stack:** Python 3.12, pytest, jsonschema, existing RFLP-Lite TaskSpec/ProposalCompiler, Ollama `qwen3.5:9b-q8_0`.

## Global Constraints

- `system_definition` allows no relations.
- `stakeholder_analysis` allows only `hasConcern`.
- `stakeholder_requirements` allows only `derivedFrom`.
- Do not automatically rewrite predicates or broaden endpoint rules.
- Keep `qwen3.5:9b-q8_0`, `max_output_tokens=4000`, and the existing fixture fixed during live probes.
- Preserve unrelated `tests/mbse_benchmark/` worktree changes.

---

### Task 1: Add explicit TaskSpec relation policies

**Files:**
- Modify: `src/rflp_lite/methodology/policy.py`
- Modify: `src/rflp_lite/methodology/tasks.py`
- Modify: `src/rflp_lite/resources/prompts/operational/system_definition.v1.md`
- Modify: `src/rflp_lite/resources/prompts/operational/stakeholder_analysis.v1.md`
- Modify: `src/rflp_lite/resources/prompts/operational/stakeholder_requirements.v1.md`
- Test: `tests/methodology/test_proposal_compiler.py`
- Test: `tests/methodology/test_taskspec_hash_stability.py`

**Interfaces:**
- `PatchPolicy.for_task(..., allowed_predicates: Iterable[RelationPredicate] | None = None)` retains the full vocabulary only when the argument is omitted.
- `_task(..., allowed_predicates=...)` passes the explicit policy to `PatchPolicy.for_task()`.
- `output_contract(task)` exposes the policy through `properties.relations.items.properties.predicate.enum`.

- [ ] **Step 1: Write failing tests for the three predicate enums.**

```python
def test_first_operational_tasks_expose_task_level_relation_predicates():
    expected = {
        "system_definition": set(),
        "stakeholder_analysis": {"hasConcern"},
        "stakeholder_requirements": {"derivedFrom"},
    }
    for task in task_catalog()[:3]:
        relation = output_contract(task)["properties"]["relations"]["items"]
        assert set(relation["properties"]["predicate"]["enum"]) == expected[task.id]
```

- [ ] **Step 2: Run the focused test and verify it fails.**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py::test_first_operational_tasks_expose_task_level_relation_predicates -q`

Expected: FAIL because all tasks currently expose the entire relation vocabulary.

- [ ] **Step 3: Implement the optional allowlist and the first three policies.**

Use `frozenset(RelationPredicate)` only when `allowed_predicates is None`. Pass `frozenset()` to `system_definition`, `{RelationPredicate.HAS_CONCERN}` to `stakeholder_analysis`, and `{RelationPredicate.DERIVED_FROM}` to `stakeholder_requirements`.

- [ ] **Step 4: Align the three prompts.**

State that `system_definition` emits no relations, `stakeholder_analysis` emits only `hasConcern`, and `stakeholder_requirements` emits only `derivedFrom`, preferring Concern and falling back to Stakeholder. Explicitly forbid `supportedBy` in `stakeholder_requirements`.

- [ ] **Step 5: Add a hash regression and run focused tests.**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py tests/methodology/test_taskspec_hash_stability.py tests/methodology/test_prompt_contracts.py -q`

Expected: PASS.

### Task 2: Verify compiler and validator fail-closed behavior

**Files:**
- Modify: `tests/methodology/test_proposal_compiler.py`

**Interfaces:**
- `compile_task_proposal()` rejects a `supportedBy` relation for `stakeholder_requirements` with `task relation predicate is outside write scope`.
- `derivedFrom` from the newly proposed Requirement to an existing Concern compiles.

- [ ] **Step 1: Add the two relation behavior tests.**

Use a context containing one Stakeholder and one Concern. Build one valid Requirement proposal whose relation is `derivedFrom` to the Concern, and one otherwise identical proposal using `supportedBy`.

- [ ] **Step 2: Run the tests and verify the allowlist behavior.**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py -q`

Expected: both tests PASS; the invalid predicate is rejected before Patch creation.

- [ ] **Step 3: Run the complete deterministic suite and lint.**

Run: `./.venv/bin/pytest -q && ./.venv/bin/ruff check src/rflp_lite tests/methodology tests/runtime tests/contract_conformance/runner.py`

Expected: PASS and `All checks passed!`.

### Task 3: Run staged real-model acceptance

**Files:**
- Create: `scripts/pr09_relation_policy_probe.py`
- Create: `docs/superpowers/artifacts/pr09/stakeholder-requirements-relation-policy-20260913.json`
- Create: `docs/superpowers/artifacts/pr09/relation-policy-three-task-chain-20260913.json`
- Create: `docs/superpowers/artifacts/pr09/relation-policy-operational-prefix-20260913.json` only if the three-task chain passes 5/5.

**Interfaces:**
- The probe reuses the existing narrow-run instrumentation while selecting a task list at runtime; it never changes Harness source or model parameters.

- [ ] **Step 1: Run `stakeholder_requirements ×10` at 4000 tokens.**

Record finish reason, schema/compile/domain rates, predicate failures, repository mutation, output utilization, and latency.

- [ ] **Step 2: Require the ten-run acceptance gate.**

Proceed only if `finish_reason=stop`, schema, compile, endpoint validation are all 100%, `supportedBy` misuse is 0, and invalid repository writes are 0.

- [ ] **Step 3: Run the three-task chain ×5.**

Keep the same fixture and model. Confirm both upstream tasks remain successful and the Requirement task now passes without `supportedBy` endpoint failures.

- [ ] **Step 4: Run the five-task Operational prefix ×5 only after 5/5 chain success.**

Add `lifecycle_analysis` and `scenario_exploration`; stop and report the first repeated contract failure if the gate is not met. Do not run 23-task.
