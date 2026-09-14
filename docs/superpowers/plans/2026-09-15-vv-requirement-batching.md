# V&V Requirement Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use inline execution in this session, task-by-task with the checkpoints below.

**Goal:** Make large configured-LLM V&V stages complete all requirement-scoped Verification/Validation plans without exceeding a small model's output budget.

**Architecture:** Keep `StructuredModelRuntime` as the single provider-facing boundary. `OpenAICompatibleModel` exposes a boolean batching capability; for `vertical.verification_validation` requests containing more than three requirements and backed by that capability, the runtime splits the canonical worklist into chunks of two, compiles every response independently, then merges and deduplicates the compiled operations into one response Patch. `ModelGenerationService` remains unchanged and performs the existing single Validator/CAS commit after the runtime returns.

**Tech Stack:** Python 3.11+, dataclasses, existing OpenAI-compatible adapter, TaskProposal schema/compiler, ModelGraph Patch/CAS, pytest.

## Global Constraints

- Do not call `127.0.0.1:11434` or start any local model.
- Use the existing `TaskProposal → Compiler → Validator → CAS` boundary.
- Do not add a database table or a second ModelGraph source of truth.
- Keep three-or-fewer requirement requests, offline RuleRuntime, and non-V&V stages single-call and backward compatible.
- A failed batch must return no committable Patch; partial batch results must never be written.
- Enforce the existing V&V `PatchPolicy.max_operations` after merging.

---

### Task 1: Add batch-shape and merge tests

**Files:**
- Modify: `tests/runtime/test_task_execution.py` for request-level behavior.
- Modify: `tests/adapters/test_openai_compatible_model.py` for adapter call behavior.
- Modify: `tests/application/test_model_generation.py` for the five-requirement vertical acceptance fixture.

**Interfaces:**
- The tests will call `StructuredModelRuntime.execute(TaskExecutionRequest)` and inspect the provider-facing `GenerationRequest.user_payload`.
- The tests will assert one returned `TaskExecutionResponse.patch` containing the merged operations and no repository revision on failure.

- [ ] **Step 1: Add a deterministic five-requirement V&V model double.**

  Reuse the existing structured fixture helpers. The double must return two complete V&V cases for every `requirement_worklist` entry, include `requirement_ids` and RFLP scope in each payload, add the first-batch hazard/failure pair only when `requirement_batch.is_first` is true, and record each received worklist and batch metadata.

- [ ] **Step 2: Add the failing application test.**

  Run the production `StructuredModelRuntime` through `ModelGenerationService.generate` with five independent requirements and assert the result eventually has 10 V&V cases, five complete `resolve_requirement_trace` results, and a successful final traceability count. Before implementation this test should fail because the existing runtime sends one oversized request and the fixture returns only the single request's scope.

- [ ] **Step 3: Add adapter-level failure tests.**

  Use a fake `OpenAICompatibleModel` completion callback that records JSON payloads. Assert a five-requirement V&V request produces worklist lengths `[2, 2, 1]`, one combined response Patch, unique operation identities, and batch diagnostics. Add a second callback that raises on the second batch and assert `StructuredOutputFailure`/`TransportFailure` propagates without a response Patch.

- [ ] **Step 4: Run the focused tests to verify the new tests fail for the intended reason.**

  Run:

  ```bash
  ./.venv/bin/python -m pytest -q tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_execution.py tests/application/test_model_generation.py -x
  ```

  Expected: the new five-requirement batching assertions fail before the implementation; existing tests must continue to pass up to the new assertion.

### Task 2: Implement bounded V&V batching in the structured runtime

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`.
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py` to expose `supports_requirement_batching = True`.
- Test: `tests/adapters/test_openai_compatible_model.py` and `tests/application/test_model_generation.py`.

**Interfaces:**
- Add a private `_requirement_batches(request)` helper returning `tuple[tuple[Mapping[str, object], ...], ...]`.
- Add a private compiled-result record carrying `GenerationResponse`, parsed `TaskProposal`, and compiled `Patch | None`.
- Keep `StructuredModelRuntime.execute` returning exactly one `TaskExecutionResponse`.

- [ ] **Step 1: Detect only the configured adapter path.**

  Return one batch for all requests except `request.task_id == "vertical.verification_validation"`, more than three worklist entries, and `getattr(self.model, "supports_requirement_batching", False) is True`. Set the capability only on `OpenAICompatibleModel`, then split the sorted worklist into slices of two. This preserves all existing deterministic fixture behavior while making the real provider path scalable.

- [ ] **Step 2: Refactor the existing single-call flow into a reusable per-batch helper.**

  The helper must construct the normal prompt payload, append the existing TaskProposal rules, add the batch metadata and batch-only worklist, call `complete_json`, parse and compile it, and return all response metadata. Keep structural repair and compiler repair behavior exactly as it is today.

- [ ] **Step 3: Merge compiled batch patches without rewriting canonical references.**

  Combine operations in batch order. Deduplicate `AddEntity` by entity ID, `Relate` by `(source_id, predicate, target_id, evidence_ids)`, `UpdateEntity` by `(entity_id, canonical field-patch JSON)`, and `Deprecate` by entity ID. Ignore later hazard/failure additions and relations that target those ignored IDs; retain the first batch's risk objects. If merged operation count exceeds `request.patch_policy.max_operations`, raise `ProposalCompileFailure` with `code="batch_operation_limit"` before returning.

- [ ] **Step 4: Merge response metadata and create one response.**

  Concatenate and stable-deduplicate assumptions, open questions, decision records, and diagnostics. Hash all batch request/response payloads for `input_hash`/`output_hash`, sum durations, carry the first provider/model identity, and append `batch_count=N` and `batch=i/N` diagnostics. Build one `Patch.create(...)` using the original context revision. If any batch raises, propagate the failure and discard all accumulated patches.

- [ ] **Step 5: Run the focused tests to verify the implementation.**

  Run:

  ```bash
  ./.venv/bin/python -m pytest -q tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_execution.py tests/application/test_model_generation.py
  ```

  Expected: PASS, including the existing three-requirement one-call test and the new five-requirement `[2, 2, 1]` test.

### Task 3: Complete the product acceptance and documentation

**Files:**
- Modify: `tests/application/test_model_generation.py` if assertions need final trace/SysML/edit coverage.
- Modify: `docs/DEVELOPMENT_STATUS.md` with the accepted five-requirement batching capability and the explicit remote-provider boundary.

**Interfaces:**
- Product acceptance consumes the existing `GenerateModelResult`, `resolve_requirement_trace`, `graph_to_sysml`, `sysml_to_graph`, and ModelService editing APIs.

- [ ] **Step 1: Assert the end-to-end artifact.**

  Verify five requirements each have a complete R→F→L→P→Verification/Validation trace, all five stage results are complete, SysML export/import preserves entities and relations, and a post-import or original graph function edit creates the next CAS revision.

- [ ] **Step 2: Assert atomic failure behavior.**

  Use a batch failure double and verify the generation result is failed, the graph revision remains at the pre-V&V revision, and no partial V&V entities are present.

- [ ] **Step 3: Update the status record.**

  Record that large configured LLM V&V is bounded by two-requirement batches and that this is a structured-path acceptance, not a claim of live remote stability while the SSH/Tailscale node is offline.

- [ ] **Step 4: Run focused product tests.**

  Run:

  ```bash
  ./.venv/bin/python -m pytest -q tests/application/test_model_generation.py tests/e2e/test_vertical_model_generation.py tests/interface/web/test_vertical_generation_api.py
  ```

  Expected: PASS.

### Task 4: Run all gates, commit, push, and perform remote-only smoke check

**Files:**
- No additional source files unless a gate exposes a direct regression.

- [ ] **Step 1: Run the complete verification suite.**

  ```bash
  ./.venv/bin/python -m pytest -q
  ./.venv/bin/python -m compileall -q src tests scripts
  ./.venv/bin/ruff check src tests scripts
  ./.venv/bin/python scripts/architecture_metrics.py
  ./.venv/bin/lint-imports
  git diff --check
  ```

  Expected: all tests and static gates pass; no architecture metric regresses; `git diff --check` is clean.

- [ ] **Step 2: Commit the implementation.**

  ```bash
  git add src/rflp_lite/runtime/structured_model.py tests/adapters/test_openai_compatible_model.py tests/application/test_model_generation.py docs/DEVELOPMENT_STATUS.md README.md
  git commit -m "feat: batch large LLM verification plans"
  ```

- [ ] **Step 3: Push the current branch.**

  ```bash
  git push origin HEAD
  ```

- [ ] **Step 4: Check the remote node without local fallback.**

  First verify `autoresearch-5080` is online with SSH/Tailscale. Only if it responds, run exactly one `CASE-04` vertical LLM benchmark using `windows-5080-ollama`; if it is offline, report the timeout and do not run any local endpoint.
