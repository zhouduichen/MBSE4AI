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

- [x] **Step 1: Write failing tests for the three predicate enums.**

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

- [x] **Step 2: Run the focused test and verify it fails.**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py::test_first_operational_tasks_expose_task_level_relation_predicates -q`

Expected: FAIL because all tasks currently expose the entire relation vocabulary.

- [x] **Step 3: Implement the optional allowlist and the first three policies.**

Use `frozenset(RelationPredicate)` only when `allowed_predicates is None`. Pass `frozenset()` to `system_definition`, `{RelationPredicate.HAS_CONCERN}` to `stakeholder_analysis`, and `{RelationPredicate.DERIVED_FROM}` to `stakeholder_requirements`.

- [x] **Step 4: Align the three prompts.**

State that `system_definition` emits no relations, `stakeholder_analysis` emits only `hasConcern`, and `stakeholder_requirements` emits only `derivedFrom`, preferring Concern and falling back to Stakeholder. Explicitly forbid `supportedBy` in `stakeholder_requirements`.

- [x] **Step 5: Add a hash regression and run focused tests.**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py tests/methodology/test_taskspec_hash_stability.py tests/methodology/test_prompt_contracts.py -q`

Expected: PASS.

### Task 2: Verify compiler and validator fail-closed behavior

**Files:**
- Modify: `tests/methodology/test_proposal_compiler.py`

**Interfaces:**
- `compile_task_proposal()` rejects a `supportedBy` relation for `stakeholder_requirements` with `task relation predicate is outside write scope`.
- `derivedFrom` from the newly proposed Requirement to an existing Concern compiles.

- [x] **Step 1: Add the two relation behavior tests.**

Use a context containing one Stakeholder and one Concern. Build one valid Requirement proposal whose relation is `derivedFrom` to the Concern, and one otherwise identical proposal using `supportedBy`.

- [x] **Step 2: Run the tests and verify the allowlist behavior.**

Run: `./.venv/bin/pytest tests/methodology/test_proposal_compiler.py -q`

Expected: both tests PASS; the invalid predicate is rejected before Patch creation.

- [x] **Step 3: Run the complete deterministic suite and lint.**

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

- [x] **Step 1: Run `stakeholder_requirements ×10` at 4000 tokens.**

Record finish reason, schema/compile/domain rates, predicate failures, repository mutation, output utilization, and latency.

- [x] **Step 2: Require the ten-run acceptance gate.**

Proceed only if `finish_reason=stop`, schema, compile, endpoint validation are all 100%, `supportedBy` misuse is 0, and invalid repository writes are 0.

- [x] **Step 3: Run the three-task chain ×5.**

Keep the same fixture and model. Confirm both upstream tasks remain successful and the Requirement task now passes without `supportedBy` endpoint failures.

- [x] **Step 4: Run the five-task Operational prefix ×5 only after 5/5 chain success.**

Add `lifecycle_analysis` and `scenario_exploration`; stop and report the first repeated contract failure if the gate is not met. Do not run 23-task.

### Task 4: Close the discovered lifecycle identity contract

The first five-task prefix exposed a repeated semantic identity conflict: the
fixture already contains lifecycle stages, while `lifecycle_analysis` proposed
stages with the same canonical IDs. The smallest fix was to contextualize the
provider schema so that, when active stages exist, the task may emit only
`lifecycle_transition` entities and must reuse existing stage IDs. The prompt
was aligned with the same branch and covered by a schema regression test.

- [x] Implement the contextual lifecycle-stage reuse branch.
- [x] Rerun the five-task Operational prefix ×5.

### Measured acceptance

Using Ollama `qwen3.5:9b-q8_0`, the fixed campus fixture, and
`max_output_tokens=4000`:

| Probe | Result | Structural/compiler/domain failures | Repository safety |
| --- | --- | --- | --- |
| `stakeholder_requirements ×10` (initial reuse branch) | 10/10 completed; no-op detected | 0 | revision unchanged |
| `stakeholder_requirements ×10` (non-empty relation branch) | 10/10 completed; `derivedFrom` written | 0 | 10/10 revision `+1` |
| three-task chain ×5 | 15/15 tasks completed | 0 | 5/5 revision `+3` |
| five-task Operational prefix ×5 (before lifecycle fix) | 20/25 completed; lifecycle identity conflict | 0 | no failed patch |
| five-task Operational prefix ×5 (after lifecycle fix) | 25/25 tasks completed | 0 | 5/5 revision `+5` |

All 25 calls in the final prefix had `finish_reason=stop`; no transport
failure, structural retry, compiler failure, duplicate `local_ref`, semantic
rejection, or failed/blocked task carrying a patch was observed. The 23-task
lifecycle remains intentionally pending.

### Follow-up: nine-task Operational phase

The staged continuation added `use_case_analysis`, `operational_scenario`,
`activity_analysis`, and `system_requirement_derivation`.

- [x] Run the nine-task Operational chain once.
- [x] Correct the two observed relation-direction contracts:
  `scenario_exploration` now uses only `derivedFrom`; `operational_scenario`
  distinguishes `derivedFrom`, `participatesIn`, and `occursIn` by endpoint.
- [x] Rerun the nine-task chain once: 9/9 completed. One transient transport
  error on `scenario_exploration` recovered on retry; no terminal failure.
- [x] Run the corrected nine-task chain ×5: 45/45 tasks and 5/5 runs
  completed, with revision delta `+9` on every run.
- [x] Inspect the Operational Gate and explicit graph trace. The Gate passes
  5/5, but explicit scenario provenance and Activity → OperationalScenario
  relations are not yet complete; this is recorded as semantic trace
  `PARTIAL`, not as an execution failure.

The full evidence report is
`docs/superpowers/artifacts/pr09/operational-9-task-acceptance-20260913.md`.
The nine-task stability artifact is
`docs/superpowers/artifacts/pr09/relation-policy-operational-9-task-stability-20260913.json`.
