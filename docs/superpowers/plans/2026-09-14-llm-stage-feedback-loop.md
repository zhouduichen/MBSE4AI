# LLM Stage Feedback Loop Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Make the structured LLM vertical path use one bounded same-stage feedback round so deterministic completion gaps can be corrected before downstream RFLP generation.

Architecture: Keep ModelGenerationService as the product-level stage coordinator. Reuse TaskExecutor, ContextBuilder, MethodologyEngine, Patch/CAS repository and StageResult, while adding an attempt loop that rebuilds context after each committed patch. Offline RuleRuntime remains single-pass; configured or injected structured runtimes may receive one feedback retry.

Tech Stack: Python 3.11+, dataclasses, SQLite ModelRepository, existing StructuredModelRuntime, pytest, Ruff, compileall, architecture metrics and import-linter.

## Global Constraints

- Never start or call a local model on this computer.
- ModelGraph remains the only model source of truth.
- Every generated change must pass the existing Compiler, Validator, PatchPolicy and CAS path.
- LOCKED and user_modified entities remain protected.
- Maximum stage attempts are exactly two: initial generation plus one feedback attempt.
- Unresolved gaps remain explicit needs_review; they cannot be counted as completed.
- Do not add a persistence table or a second model representation.

---

### Task 1: Add explicit stage-attempt result metadata

Files:
- Modify: src/rflp_lite/application/model_generation.py StageResult and GenerateModelResult.as_dict
- Test: tests/application/test_model_generation.py

Interfaces:
- Consumes: existing StageResult construction and serialized stage results.
- Produces: StageResult.attempts: int = 1, serialized as attempts for every stage result.

- [x] Step 1: Write the failing test

Extend the structured generation test to assert every stage result exposes attempts as a positive integer and its serialized representation contains the same value.

- [x] Step 2: Run the test

Run: ./.venv/bin/python -m pytest -q tests/application/test_model_generation.py::test_generation_uses_structured_llm_runtime_for_all_five_stages

Expected: FAIL because StageResult has no attempts field.

- [x] Step 3: Implement

Extend StageResult with attempts: int = 1 and add attempts to the stage mapping in GenerateModelResult.as_dict. Keep all existing fields and order compatible.

- [x] Step 4: Verify

Run the same targeted test. Expected: PASS.

- [x] Step 5: Commit

    git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py
    git commit -m "feat: record vertical stage attempts"

### Task 2: Implement one same-stage feedback attempt

Files:
- Modify: src/rflp_lite/application/model_generation.py _execute_stage and stage helpers
- Test: tests/application/test_model_generation.py

Interfaces:
- Consumes: ContextBuilder.build, TaskExecutor.execute, _context, _promote_generated_entities, evaluate_vertical_stage and StageResult.
- Produces: _execute_stage may invoke the same stage twice, commits each valid Patch, and returns the final completion result plus attempts.

- [x] Step 1: Write the failing test

Add a deterministic FeedbackFunctionalModel. Its first vertical.functional response updates no requirement; its second response updates the first requirement with functional_behavior_ids and functional_requirement_status=allocated. Record each request context revision and assert the second request sees a greater revision and the final Functional stage has no functional_requirement completion issue.

- [x] Step 2: Run the test

Run: ./.venv/bin/python -m pytest -q tests/application/test_model_generation.py::test_structured_stage_feedback_closes_functional_completion_gap

Expected: FAIL because the current coordinator invokes vertical.functional only once.

- [x] Step 3: Implement

Refactor the current single-attempt body into a bounded loop:

    for attempt in range(1, 3):
        current = self.repository.load_graph(project_id)
        context = self._context(current, task.id, document_ids,
                                 controller_decision=controller_decision)
        response = self.executor.execute(
            task, context, self.methodology_version,
            evidence_bundle=context.evidence,
            token_budget=self.output_budget,
        )
        # retain validation, candidate promotion, CAS append and issue handling
        current = self.repository.load_graph(project_id)
        completion = evaluate_vertical_stage(stage.stage, current)
        missing_kinds = self._missing_stage_kinds(current, stage.stage)
        if attempt == 2 or not _stage_feedback_needed(
                missing_kinds, completion.issue_codes, semantic_invalid):
            return _stage_result(..., attempts=attempt)

The second pass must rebuild context from the repository after the first Patch. Enable the loop only when _feedback_enabled returns true for configured or explicitly injected structured Runtime; keep offline RuleRuntime single-pass. Preserve all existing exception and semantic-invalid handling.

- [x] Step 4: Run focused tests

Run: ./.venv/bin/python -m pytest -q tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py

Expected: PASS.

- [x] Step 5: Commit

    git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py
    git commit -m "feat: close llm stage gaps with bounded feedback"

### Task 3: Preserve stage ledger and audit evidence

Files:
- Modify: src/rflp_lite/application/model_generation.py Step and stage audit writes
- Test: tests/application/test_model_generation.py

Interfaces:
- Consumes: attempt number from Task 2 and existing Step/audit constructors.
- Produces: final stage Step with last attempt number and stage completion audit carrying attempts.

- [x] Step 1: Write the failing assertion

Extend the feedback test to load the generation Run and assert the Functional Step has attempt == 2; assert the matching model_generation.stage_completed audit event contains attempts == 2.

- [x] Step 2: Run the test

Run: ./.venv/bin/python -m pytest -q tests/application/test_model_generation.py::test_structured_stage_feedback_closes_functional_completion_gap

Expected: FAIL because current Step and audit data are hard-coded to attempt 1 and omit the field.

- [x] Step 3: Implement

Use the loop attempt value in both Step writes and add attempts to the stage audit payload. Do not create a new Run, Patch table, or non-CAS write path.

- [x] Step 4: Verify

Run the same targeted test. Expected: PASS.

- [x] Step 5: Commit

    git add src/rflp_lite/application/model_generation.py tests/application/test_model_generation.py
    git commit -m "feat: audit llm feedback attempts"

### Task 4: Add unresolved-gap and offline regressions

Files:
- Modify: tests/application/test_model_generation.py
- Modify: tests/e2e/test_vertical_model_generation.py
- Modify: docs/CURRENT_ARCHITECTURE.md
- Modify: docs/DEVELOPMENT_STATUS.md

Interfaces:
- Consumes: bounded feedback behavior and existing offline generation acceptance tests.
- Produces: proof that unresolved structured gaps remain needs_review, offline stages remain single-pass, and documentation describes the feedback loop.

- [x] Step 1: Add regression assertions

Add a fixture that returns the same incomplete Functional proposal twice. Assert stage.status == needs_review, the issue code remains, and no false completed status is returned. Assert existing VerticalRuleRuntime generation reports one attempt per stage.

- [x] Step 2: Run targeted tests

Run: ./.venv/bin/python -m pytest -q tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py

Expected: new assertions fail until the final status and offline gate are wired.

- [x] Step 3: Implement and document

Use _stage_feedback_needed only for missing kinds, completion issue codes or semantic-invalid output; leave measurement warnings and ordinary methodology findings as review feedback without retry. Document that the retry is a bounded LLM feedback loop and not an automatic engineering decision.

- [x] Step 4: Verify

Run the same targeted test command. Expected: PASS.

- [x] Step 5: Commit

    git add tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md
    git commit -m "test: verify bounded llm stage feedback"

### Task 5: Run full quality gates and push

Files:
- Test only: repository-wide quality gates

Interfaces:
- Consumes: Tasks 1–4.
- Produces: verified clean worktree and pushed branch.

- [ ] Step 1: Run full gates

    ./.venv/bin/python -m pytest -q
    ./.venv/bin/python -m compileall -q src tests scripts
    ./.venv/bin/ruff check src tests scripts
    ./.venv/bin/python scripts/architecture_metrics.py
    ./.venv/bin/lint-imports
    git diff --check

Expected: all tests pass; architecture metrics remain within architecture_budget.json; import contracts remain 5 kept, 0 broken; diff check is clean.

- [ ] Step 2: Inspect state

    git status --short
    git log --oneline -8

Expected: only intended commits are present and no generated artifacts are untracked.

- [ ] Step 3: Push

    git push origin HEAD

Expected: origin/codex/web-audit-2026-08-18 advances to the final implementation commit.
