# Complete Structured LLM Vertical Acceptance Implementation Plan

**Status:** Completed; offline acceptance is covered by the compiler, complete structured vertical, SysML round-trip, and Controller trade-study tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove and harden one complete structured-LLM R→F→L→P→V&V run, including canonical payload references, SysML round-trip, and Controller-driven physical conflict iteration.

**Architecture:** Keep ModelGraph as the only source of truth and keep the existing `StructuredModelRuntime → TaskExecutor → Compiler → Validator → CAS` write path. Add a small typed payload-reference materializer inside `proposal_compiler.py`, then add a deterministic complete LLM fixture and product-level acceptance tests; reuse the existing Methodology Engine, Controller, impact planner and SysML projection for iteration checks.

**Tech Stack:** Python 3.11+, dataclasses, JSON Schema, SQLite ModelRepository, existing StructuredModelRuntime, pytest, Ruff, compileall, architecture metrics and import-linter.

## Global Constraints

- Never start or call a local model on this computer.
- ModelGraph remains the only model source of truth.
- Every generated change must pass the existing Compiler, Validator, PatchPolicy and CAS path.
- Proposal-local payload references are resolved only against the current Context and current Proposal; names are never used as implicit IDs.
- LOCKED and user_modified entities remain protected.
- Unresolved gaps remain explicit `needs_review`; they cannot be counted as completed.
- Trade Study options require an explicit user selection.
- Do not add a persistence table or a second model representation.

---

### Task 1: Materialize typed payload references in the Proposal Compiler

**Files:**
- Modify: `src/rflp_lite/methodology/proposal_compiler.py`
- Test: `tests/methodology/test_proposal_compiler.py`

**Interfaces:**
- Consumes: `TaskExecutionRequest.context_bundle.entities`, Proposal `local_ref` values, existing `make_entity` and `ContractViolation` boundaries.
- Produces: `_materialize_payload_references(kind, payload, ref_to_id, known_ids) -> dict[str, object]`, used by AddEntity and UpdateEntity compilation.

- [x] **Step 1: Write the failing test**

Add a `vertical.functional` `TaskExecutionRequest` with a Requirement in context. Compile a Proposal containing a Function with local ref `function-1`, a FunctionalFlow with `source_function_ids=["function-1"]` and `target_function_ids=["function-1"]`, and a FunctionalScenario with `function_ids=["function-1"]`. Assert all three compiled payloads contain the generated Function canonical ID rather than `function-1`. Add a second payload with `source_function_ids=["missing-function"]` and assert `ContractViolation`.

- [x] **Step 2: Run the focused test and verify failure**

```bash
./.venv/bin/pytest -q tests/methodology/test_proposal_compiler.py -k "payload_reference"
```

Expected: FAIL because payload values currently retain local refs and unknown payload references are not checked.

- [x] **Step 3: Implement the typed materializer**

Add an explicit allowlist and recursively materialize only these graph-reference fields:

```python
_GRAPH_REFERENCE_FIELDS = frozenset({
    "activity_ids", "actor_ids", "connected_component_ids", "dependencies",
    "dependency_ids", "depends_on", "depends_on_ids", "functional_behavior_ids",
    "functional_flow_ids", "function_ids", "impact_entity_ids", "internal_component_ids",
    "logical_component_ids", "logical_id", "owner_id", "physical_candidate_ids",
    "physical_ids", "requirement_ids", "scenario_ids", "shared_state_ids",
    "source_context_ids", "source_function_ids", "source_logical_ids",
    "source_physical_ids", "source_requirement_ids", "target_function_ids",
})
```

Build all AddEntity canonical IDs before constructing AddEntity operations. For an allowlisted scalar or list item, replace a matching local ref with `ref_to_id`, retain a known Context/output canonical ID, and raise `ContractViolation("unknown payload entity reference: ...")` otherwise. Recurse through mappings and lists so `impact_chain` and `resolution_options[*].impact_entity_ids` are handled. Apply the same helper to UpdateEntity payload patches before validating the merged payload. Do not process `evidence_ids`, `execution_evidence_ids`, external `source_ids`, free text or constraint provenance.

- [x] **Step 4: Run all compiler tests**

```bash
./.venv/bin/pytest -q tests/methodology/test_proposal_compiler.py
```

Expected: PASS, including existing schema, local-ref, CAS and partial-update tests.

- [x] **Step 5: Commit**

```bash
git add src/rflp_lite/methodology/proposal_compiler.py tests/methodology/test_proposal_compiler.py
git commit -m "feat: canonicalize llm payload references"
```

### Task 2: Build the complete five-stage structured fixture

**Files:**
- Modify: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: `StructuredModelRuntime`, `GenerationResponse`, current request context entities and the five vertical stage contracts.
- Produces: `CompleteVerticalModel.complete_json(request) -> GenerationResponse`, returning a complete stage-specific TaskProposal through the production compiler and validators.

- [x] **Step 1: Write the failing acceptance test**

Add `test_structured_runtime_generates_complete_editable_vertical_model` and run `ModelGenerationService.generate` from `系统应在校园内完成配送并支持人工接管`. Assert:

```python
assert result.status == "completed"
assert all(stage.status == "completed" for stage in result.stage_results)
assert all(stage.completion_issue_codes == () for stage in result.stage_results)
assert result.traceability.end_to_end_complete_count == 1
```

Also assert all required entity kinds exist and every graph-reference payload ID points to an entity in the resulting ModelGraph.

- [x] **Step 2: Run the test and verify failure**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_structured_runtime_generates_complete_editable_vertical_model
```

Expected: FAIL because no complete fixture exists and the existing scripted responses leave several stage completion checks unresolved.

- [x] **Step 3: Implement one response builder per stage**

Read canonical IDs from `request.user_payload["context"]["entities"]`; use local refs only for new entities. Include operational objects and requirement derivation, functional decomposition/flow/scenario plus requirement update, logical allocation/interface/state/evaluation, physical constraints/feasibility/impact chain, and V&V plan/scope/risk objects. Every new object must have a non-empty payload accepted by the existing schemas and every stage response must include the five required proposal arrays/fields. The fixture must reuse existing objects on retry and never create duplicate active entities.

- [x] **Step 4: Run focused structured tests**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_structured_runtime_generates_complete_editable_vertical_model tests/application/test_model_generation.py::test_structured_runtime_retries_one_stage_with_latest_graph_and_guidance
```

Expected: PASS; the complete fixture uses one attempt per stage, while the incomplete fixture still exercises the bounded feedback path.

- [x] **Step 5: Commit**

```bash
git add tests/application/test_model_generation.py
git commit -m "test: accept complete structured vertical model"
```

### Task 3: Verify SysML round-trip and editable ModelGraph integrity

**Files:**
- Modify: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: complete structured generation result, `graph_to_sysml`, `sysml_to_graph`, `ModelService.apply_patch` and Review/CAS behavior.
- Produces: acceptance evidence that SysML is an interchange projection and the canonical ModelGraph remains editable.

- [x] **Step 1: Add round-trip assertions**

Export the complete graph with `graph_to_sysml`, restore it with `sysml_to_graph`, and assert entity IDs, kinds, statuses, payloads and `(source_id, predicate, target_id)` relation triples are equal. Apply one `UpdateEntity` to the current project and assert the revision increments while the edited entity ID remains unchanged.

- [x] **Step 2: Run the round-trip test**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py::test_structured_runtime_generates_complete_editable_vertical_model
```

Expected: PASS.

- [x] **Step 3: Commit**

```bash
git add tests/application/test_model_generation.py
git commit -m "test: verify structured model sysml round trip"
```

### Task 4: Exercise Controller physical conflict and local re-entry

**Files:**
- Modify: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: complete structured model, Review/CAS edit, `ModelGenerationService.controller_plan`, `execute_controller_action`, `ImpactPlan` and existing Trade Study behavior.
- Produces: product-level proof for conflict → impact → user decision → Physical/V&V reanalysis.

- [x] **Step 1: Write the Controller acceptance test**

After complete generation, edit the Requirement with `constraints={"max_power_w": 50}` and the PhysicalBlock with `power_w=80`. Assert the plan includes `physical_constraint_conflict`, returns a `trade_study` action and does not change revision when called without `option_id`. Select the physical replacement option and assert:

```python
assert payload["execution_status"] == "completed"
assert payload["reanalysis"]["selected_stages"] == ["physical", "verification_validation"]
assert payload["reanalysis"]["before_traceability"]
assert payload["reanalysis"]["after_traceability"]
```

Also assert an alternative PhysicalBlock carries the selected decision and no locked entity changes.

- [x] **Step 2: Run the focused Controller tests**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py -k "structured.*controller or complete.*controller"
```

Expected: FAIL until the complete fixture exposes a full structured graph; if existing Controller behavior already passes, retain the test and make no unrelated changes.

- [x] **Step 3: Implement only required integration fixes**

Reuse `execute_controller_action`, `TypedImpactPlanner` and existing Runtime boundaries. If selected-stage context loses the decision or impact metadata, propagate it through the existing `ContextBundle` and audit payload; do not add a second Controller or direct repository write.

- [x] **Step 4: Run application and API regressions**

```bash
./.venv/bin/pytest -q tests/application/test_model_generation.py tests/interface/web/test_vertical_generation_api.py
```

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add src/rflp_lite tests/application/test_model_generation.py tests/interface/web/test_vertical_generation_api.py
git commit -m "test: accept controller driven architecture iteration"
```

### Task 5: Run full gates, document, and push

**Files:**
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: repository-wide quality gates

**Interfaces:**
- Consumes: Tasks 1–4 and the complete structured acceptance result.
- Produces: documented product behavior, verified clean worktree and pushed branch.

- [x] **Step 1: Update product documentation**

Document canonicalization before CAS, complete structured five-stage acceptance, SysML round-trip and user-decided Controller Trade Study re-entry into only impacted stages.

- [x] **Step 2: Run all quality gates**

```bash
./.venv/bin/pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
git diff --check
```

Expected: all tests pass; architecture metrics remain within budget; import contracts remain 5 kept/0 broken; no diff errors.

- [x] **Step 3: Inspect and push**

```bash
git status --short --branch
git log --oneline -8
git push origin HEAD
```

Expected: only intended commits are present, worktree is clean, and `origin/codex/web-audit-2026-08-18` points to the final commit.
