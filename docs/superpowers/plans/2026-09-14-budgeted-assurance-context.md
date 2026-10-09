# Budgeted Assurance Context Implementation Plan

> For the implementation pass: use the repository's existing test runner and make each task independently verifiable. Keep all LLM tests deterministic/offline; do not start a model on this workstation.

## Goal

Make V&V and global cross-analysis context selection obey the runtime's available context budget while preserving the highest-value R→F→L→P trace scope. Large inputs must produce a bounded, explainable ContextBundle instead of sending the whole graph to the structured runtime.

## Architecture and constraints

- ModelGraph remains the source of truth; this change only selects a read-only context view.
- ContextBuilder is the single budget boundary. The available graph/evidence budget is token_budget - output_reserve - prompt_reserve.
- Assurance priority is deterministic: all active Requirement IDs first, then their Function, LogicalComponent, PhysicalBlock scope, then directly matching Verification/Validation cases, then supporting Activity/Scenario/Hazard/FailureMode entities.
- Keep relations closed over selected entity IDs and sort all output deterministically.
- Report selected/omitted IDs in methodology_guidance context_selection so the runtime can explain bounded context without inventing model gaps.
- Preserve existing behavior for normal task planning, evidence budgeting, ModelGraph mutation, SysML export/import, and remote provider configuration.

## Task 1 — Add failing regression tests

Files: tests/methodology/test_context_budget.py, tests/application/test_model_generation.py

1. Update the two existing assurance tests that use token_budget=1 to use a generous budget, because they verify complete trace preservation rather than bounded selection.
2. Add a methodology test with multiple requirements and a fixed token estimator. Assert that:
   - the assurance context estimate is at or below the available budget;
   - all requirement IDs are retained when they fit;
   - downstream entities are omitted when the budget is exhausted;
   - omitted IDs are exposed in context_selection; and
   - every returned relation has both endpoints in the returned entity set.
3. Add a structured vertical-generation regression using the existing deterministic CompleteVerticalModel and a recorder. Configure context_window=4096, max_output_tokens=1024, and prompt_reserve=256 through the service path; assert assurance contexts stay within 4096 - 1024 - 256 = 2816 estimated tokens and expose selection diagnostics.
4. Run the focused tests and confirm the new bounded assertions fail against the current unbounded assurance helper.

Commands:

pytest -q tests/methodology/test_context_budget.py
pytest -q tests/application/test_model_generation.py -k "vertical_generation_bounds or assurance"

## Task 2 — Implement budgeted assurance selection

Files: src/rflp_lite/methodology/context.py, src/rflp_lite/methodology/workflow.py

1. Import EntityStatus and requirement_trace_scope using existing package conventions.
2. Pass available_context into the assurance helper instead of bypassing the planner budget.
3. Replace the unbounded helper with deterministic priority selection:
   - collect active requirements and build each trace scope;
   - try requirement IDs in a first pass, then F/L/P IDs by layer, then matching V&V IDs;
   - rank supporting active entities that reference or connect to the selected scope first, then add other supported assurance entities while budget remains;
   - accept an entity only if adding its entity cost plus any newly closed relation cost remains within the budget;
   - use the existing planner estimator and preserve relation closure.
4. Add a guidance payload containing selected IDs, omitted IDs, selected/omitted requirement IDs, available budget, and estimate. Keep IDs sorted and JSON-serializable.
5. Ensure empty/very small budgets return a valid, deterministic context and never raise solely because the graph is large.
6. Align the no-profile offline WorkflowRunner fallback with the RuntimeFactory default context window so existing deterministic multi-requirement runs are not degraded solely by the new bounded selector.

Commands:

pytest -q tests/methodology/test_context_budget.py tests/methodology/test_context_planner.py
pytest -q tests/application/test_model_generation.py -k "vertical"

## Task 3 — Verify the full offline vertical path

Files: tests/application/test_model_generation.py, optionally docs/README.md only if user-facing behavior needs documenting.

1. Keep the integration test on CompleteVerticalModel/RuleRuntime; do not require network access or invoke Ollama locally.
2. Verify the service completes (with or without expected warnings), records bounded assurance contexts, and retains the existing editable ModelGraph/SysML roundtrip coverage.
3. Run the complete repository quality gates and inspect failures for regressions outside this change.

Commands:

pytest -q
python -m compileall -q src tests
git diff --check

## Task 4 — Commit and push

1. Review git diff, git status, and the focused/full test output.
2. Commit the implementation and test changes with a concise message such as feat: bound assurance context for large models.
3. Push the current branch to origin and verify the local HEAD matches the remote branch.

## Acceptance criteria

- No assurance task can serialize an unbounded graph into a context bundle.
- R→F→L→P scope is prioritized and deterministic under a finite budget.
- V&V can consume the bounded context and receives explicit omission diagnostics.
- Existing offline vertical generation, editability, traceability, and SysML roundtrip tests pass.
- The implementation does not run a local model and does not add a new stability-experiment harness.
