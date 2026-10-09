# Per-Requirement Coverage Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each active input Requirement produce an explicit, revision-bound coverage result for the vertical R→F→L→P→V&V stages and feed exact missing IDs back to the structured LLM retry.

**Architecture:** Add a pure `vertical_coverage` resolver over the existing Typed ModelGraph and named trace predicates. Reuse its result in vertical-stage completion and `methodology_guidance`; the existing Structured Runtime, compiler, validators, PatchPolicy, CAS, and five-stage call boundary remain unchanged.

**Tech Stack:** Python 3.11+, dataclasses, existing `ModelGraph`, `EntityKind`, `RelationPredicate`, pytest, ruff.

## Global Constraints

- Do not invoke or start a local model, Ollama, or any local model endpoint.
- Do not add a Provider, database table, ModelGraph schema field, task, or per-requirement LLM call.
- Keep ModelGraph as the only source of truth; the resolver is read-only.
- Count only typed, active trace targets; rejected/deprecated targets cannot satisfy coverage.
- Preserve aggregate metrics, existing five stages, 23-task pipeline, SysML round-trip, and current API shape.
- All generated mutations continue through Structured Runtime → Compiler → Validator → PatchPolicy → CAS.

## File Map

- Create: `src/rflp_lite/methodology/vertical_coverage.py` — immutable per-requirement and per-stage coverage values.
- Modify: `src/rflp_lite/methodology/completion.py` — add stage-level checks backed by the resolver.
- Modify: `src/rflp_lite/methodology/engine.py` — expose bounded coverage details in LLM guidance.
- Modify: `src/rflp_lite/runtime/structured_model.py` — add one common instruction for repairing listed missing IDs.
- Modify: `tests/methodology/test_completion.py` — assert exact per-requirement gaps.
- Modify: `tests/methodology/test_engine.py` — assert guidance contains bounded coverage rows.
- Modify: `tests/runtime/test_task_specific_prompts.py` — assert the structured prompt carries the repair instruction.
- Modify: `tests/application/test_model_generation.py` — prove a structured multi-requirement retry receives and resolves the missing ID.
- Modify: `docs/DEVELOPMENT_STATUS.md` and `README.md` — record the new product acceptance boundary.

### Task 1: Add the pure per-requirement Coverage Resolver

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RequirementCoverageRow:
    requirement_id: str
    stage: str
    function_ids: tuple[str, ...]
    logical_component_ids: tuple[str, ...]
    physical_ids: tuple[str, ...]
    verification_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    missing: tuple[str, ...]
    path: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class VerticalCoverage:
    stage: str
    rows: tuple[RequirementCoverageRow, ...]
    passed: bool

def resolve_vertical_coverage(graph: ModelGraph, stage: str) -> VerticalCoverage: ...
```

The resolver must use active Requirement entities, follow `Requirement → Function` through `satisfiedBy`, `Function → LogicalComponent` through `allocatedTo`/`satisfiedBy`, and `LogicalComponent → PhysicalBlock` through `allocatedTo`/`realizedBy`. For technical requirements, allow the existing direct Requirement `satisfiedBy` → PhysicalBlock path. Assurance rows require both typed V&V relations and `vv_scope_matches`. Use requirement lineage for derived technical requirements and keep IDs sorted and deduplicated.

- [ ] **Step 1: Write failing resolver tests**

```python
def test_resolver_lists_the_requirement_that_lacks_function_and_vv_scope():
    graph, first_requirement, second_requirement = build_two_requirement_graph()
    result = resolve_vertical_coverage(graph, "functional")
    assert result.passed is False
    assert [row.requirement_id for row in result.rows if row.missing] == [second_requirement.id]
    assert result.rows[1].missing == ("function",)
```

Add one complete row and one physical/assurance gap row so the tests verify each stage’s exact missing labels and that deprecated targets do not count.

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `./.venv/bin/pytest -q tests/methodology/test_vertical_coverage.py`

Expected: collection or import failure because `vertical_coverage.py` and `resolve_vertical_coverage` do not yet exist.

- [ ] **Step 3: Implement the resolver**

Implement only read-only helpers in `vertical_coverage.py`. Use the existing `requirement_lineage`, `is_technical_requirement`, and `vv_scope_matches` helpers where they match the named semantics; do not duplicate a second database traversal or mutate entities.

- [ ] **Step 4: Run resolver tests**

Run: `./.venv/bin/pytest -q tests/methodology/test_vertical_coverage.py`

Expected: all resolver tests pass.

### Task 2: Attach exact coverage to stage completion and guidance

**Interfaces:** `evaluate_vertical_stage(stage, graph)` keeps its existing return type. It adds one check with ID `requirement_coverage:<stage>` for Functional, Logical, Physical, and Verification/Validation. The check includes `passed`, `requirement_count`, `covered_count`, `missing_requirement_ids`, and bounded `gaps` rows. A failed check adds `completion_requirement_coverage:<stage>` while retaining every existing reasoning check.

- [ ] **Step 1: Extend completion tests**

Update the existing check-count assertion and add:

```python
result = evaluate_vertical_stage(VerticalStage.FUNCTIONAL, graph)
check = next(item for item in result.checks if item["id"] == "requirement_coverage:functional")
assert check["missing_requirement_ids"] == [second_requirement.id]
assert "completion_requirement_coverage:functional" in result.issue_codes
```

- [ ] **Step 2: Run completion tests and observe the expected failure**

Run: `./.venv/bin/pytest -q tests/methodology/test_completion.py`

Expected: the new check is absent before integration.

- [ ] **Step 3: Integrate the resolver into `completion.py`**

Add the resolver-backed check after the existing reasoning checks for the four downstream stages. Keep Requirements stage behavior unchanged and keep existing issue-code ordering stable before the new check.

- [ ] **Step 4: Add bounded guidance assertions**

In `tests/methodology/test_engine.py`, assert `MethodologyEngine().context_guidance(graph, "vertical.functional")` contains `requirement_coverage`, its stage is `functional`, and its `missing_requirement_ids` are canonical IDs. Ensure no more than 24 gap rows are emitted.

- [ ] **Step 5: Integrate guidance and run focused tests**

In `build_methodology_guidance`, copy the resolver-backed completion check into `guidance["requirement_coverage"]` without exposing unbounded graph content. Run:

```bash
./.venv/bin/pytest -q tests/methodology/test_completion.py tests/methodology/test_engine.py tests/methodology/test_vertical_coverage.py
```

Expected: all focused tests pass and existing aggregate metric assertions remain unchanged.

### Task 3: Make the structured LLM feedback consume the exact gaps

**Interfaces:** No new runtime interface. Append a stable instruction to the existing `StructuredModelRuntime` system prompt: when `methodology_guidance.stage_completion.requirement_coverage.passed` is false, repair only listed `missing_requirement_ids`/`gaps`, reuse canonical IDs, and leave unresolvable items in `open_questions`.

- [ ] **Step 1: Add prompt contract assertion**

In `tests/runtime/test_task_specific_prompts.py`, assert the captured system prompt contains `missing_requirement_ids`, `canonical`, and the instruction to repair the listed coverage gap.

- [ ] **Step 2: Run the prompt test to verify it fails**

Run: `./.venv/bin/pytest -q tests/runtime/test_task_specific_prompts.py`

Expected: the captured system prompt does not yet contain the new instruction.

- [ ] **Step 3: Add the common instruction**

Modify only the prompt suffix in `src/rflp_lite/runtime/structured_model.py`; do not loosen schema or validator behavior and do not let the model write coverage fields as authoritative facts.

- [ ] **Step 4: Add a multi-requirement feedback test**

Extend the structured test double in `tests/application/test_model_generation.py` so the first Functional response covers only one of two requirements, records the guidance payload, and the second Functional response adds the missing Function and relation. Assert the second request contains the exact missing Requirement ID, the Functional stage ends `completed`, and the final traceability complete count is two.

- [ ] **Step 5: Run the feedback tests**

Run:

```bash
./.venv/bin/pytest -q tests/runtime/test_task_specific_prompts.py tests/application/test_model_generation.py
```

Expected: the prompt contract and multi-requirement feedback test pass without any local model invocation.

### Task 4: Document, run the full verification matrix, and publish

- [ ] **Step 1: Update product documentation**

Add the new boundary to `README.md` and `docs/DEVELOPMENT_STATUS.md`: stage completion and feedback are per Requirement, while aggregate metrics remain projections.

- [ ] **Step 2: Run the full test suite**

Run: `./.venv/bin/pytest -q`

Expected: all tests pass.

- [ ] **Step 3: Run static and architecture gates**

Run each command separately and require exit code 0:

```bash
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```

- [ ] **Step 4: Commit and push**

```bash
git add docs/DEVELOPMENT_STATUS.md README.md \
  src/rflp_lite/methodology/vertical_coverage.py \
  src/rflp_lite/methodology/completion.py \
  src/rflp_lite/methodology/engine.py \
  src/rflp_lite/runtime/structured_model.py \
  tests/methodology/test_vertical_coverage.py \
  tests/methodology/test_completion.py tests/methodology/test_engine.py \
  tests/runtime/test_task_specific_prompts.py tests/application/test_model_generation.py
git commit -m "feat: close per-requirement coverage loop"
git push origin codex/web-audit-2026-08-18
```

- [ ] **Step 5: Confirm remote parity**

Run: `git status --short && git rev-parse HEAD && git rev-parse '@{u}'`

Expected: clean status and identical local/upstream commit IDs.
