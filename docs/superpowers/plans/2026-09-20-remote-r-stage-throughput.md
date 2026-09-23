# Remote R Stage Throughput Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce remote R-stage wall time enough for a real OpenAI-compatible model to reach the downstream F→L→P→V&V stages without weakening typed traceability or the single CAS write boundary.

**Architecture:** Keep R backbone slices as the dependency barrier. Remote providers will use the existing mixed-kind backbone contract by default; if a mixed slice fails schema/compile validation, the runtime falls back to one-kind retries. After the backbone is merged, independent requirement closures remain parallel and are merged deterministically into one patch. The provider adapter exposes an explicit override for endpoints that require one-kind backbone calls.

**Tech Stack:** Python 3.12, `StructuredModelRuntime`, `OpenAICompatibleModel`, pytest, existing `GenerationResponse`/`Patch` contracts.

## Global Constraints

- Do not start or call a model running on the development computer.
- Preserve canonical IDs, deterministic merge order, and one CAS boundary per stage.
- Keep the fallback path for providers that reject mixed-kind structured output.
- Do not change the domain model, SysML format, or benchmark scoring in this slice.

---

### Task 1: Make remote R backbone mode configurable

**Files:**
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py:815-828`
- Test: `tests/adapters/test_openai_compatible_model.py`

**Interfaces:**
- Consumes: profile key `r_backbone_single_kind` when present.
- Produces: `OpenAICompatibleModel.r_backbone_single_kind: bool`, defaulting to `False` for remote models and `False` for local models.

- [ ] **Step 1: Write the failing test**

Add assertions that a remote model uses mixed-kind R backbone slices by default and that an explicit `r_backbone_single_kind=True` profile still enables the compatibility fallback mode.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/adapters/test_openai_compatible_model.py::test_openai_compatible_remote_model_uses_single_vertical_pass_by_default -q`

Expected: FAIL because the current remote default is `True`.

- [ ] **Step 3: Implement the smallest configuration change**

Read the optional boolean without changing the existing model-location defaults:

```python
configured_single_kind = self._config.get("r_backbone_single_kind")
if isinstance(configured_single_kind, bool):
    self.r_backbone_single_kind = configured_single_kind
else:
    self.r_backbone_single_kind = False
```

- [ ] **Step 4: Run the focused adapter tests**

Run: `./.venv/bin/python -m pytest tests/adapters/test_openai_compatible_model.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/adapters/openai_compatible_model.py tests/adapters/test_openai_compatible_model.py
git commit -m "perf: use mixed remote R backbone slices by default"
```

### Task 2: Parallelize independent R backbone requests with deterministic fallback

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py:350-445`
- Test: `tests/runtime/test_task_execution.py`

**Interfaces:**
- Consumes: `supports_parallel_r_backbone`, `max_parallel_requests`, `_request_for_working_graph`, `_rebase_patch`.
- Produces: `_complete_r_backbone_slices(...)` behavior that returns compiled proposals in declared slice order and applies any fallback after successful peers are merged.

- [ ] **Step 1: Write failing tests**

Add a fake R model with two mixed-kind backbone slices. Make each call record its thread and return a valid disjoint patch. Assert both backbone calls are issued before the first closure call, the returned patch contains both entities, and diagnostics/order remain deterministic. Add a second fake model where one backbone returns `StructuredOutputFailure`; assert the successful slice is preserved and the failed slice retries by kind against the updated working graph.

- [ ] **Step 2: Run the focused runtime tests to verify the new behavior fails**

Run: `./.venv/bin/python -m pytest tests/runtime/test_task_execution.py -k 'r_stage and (parallel or fallback)' -q`

Expected: FAIL because the current loop executes each backbone serially.

- [ ] **Step 3: Implement the bounded parallel helper**

Use a `ThreadPoolExecutor` only when the provider advertises `supports_parallel_r_backbone` and there are at least two backbone slices. Submit each initial backbone request against the same pre-backbone graph, collect results in slice order, then apply successful patches with `_rebase_patch`. Providers without this explicit capability keep the dependency-safe serial path. For failures, run the existing one-kind fallback sequentially against the updated graph; preserve `_annotate_r_slice_failure` and stop before closures if fallback fails.

- [ ] **Step 4: Keep closure parallelism and stage boundary unchanged**

Call `_complete_batches` only after all backbone results/fallbacks have been merged. Do not apply any patch to the repository in the helper; return compiled proposals so `_merge_compiled` remains the sole stage-level merge boundary.

- [ ] **Step 5: Run focused runtime tests**

Run: `./.venv/bin/python -m pytest tests/runtime/test_task_execution.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/runtime/structured_model.py tests/runtime/test_task_execution.py
git commit -m "perf: parallelize independent R backbone slices"
```

### Task 3: Verify the full local contract and remote-ready configuration

**Files:**
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: existing runtime, adapter, e2e, lint, and architecture checks

**Interfaces:**
- Consumes: the two implementation commits and the existing SSH-forwarded profile.
- Produces: evidence that local behavior is unchanged and the remote profile can opt into compatibility mode without source changes.

- [ ] **Step 1: Run focused and product acceptance tests**

```bash
./.venv/bin/python -m pytest tests/adapters/test_openai_compatible_model.py tests/runtime/test_task_execution.py tests/e2e/test_local_product_acceptance.py -q
```

Expected: PASS with the existing pre-known skip only.

- [ ] **Step 2: Run static checks**

```bash
./.venv/bin/ruff check src tests scripts
git diff --check
./.venv/bin/python -m compileall -q src tests scripts
```

Expected: all commands exit 0.

- [ ] **Step 3: Run one remote CASE-04 attempt through SSH forwarding**

Use the existing `Jiayu-intern` tunnel and isolated `RFLP_CONFIG_DIR`; do not start a local model. Record whether the run reaches F/L/P/V&V, not merely the final score.

- [ ] **Step 4: Update the status record with the observed boundary**

Add one row to `docs/DEVELOPMENT_STATUS.md` that names the tested commit, stage reached, elapsed time, and whether the evidence is pure remote Provider or a mixed/offline path.

- [ ] **Step 5: Commit and push the evidence**

```bash
git add docs/DEVELOPMENT_STATUS.md tests/mbse_benchmark/reports/llm/jiayuinter-vllm tests/mbse_benchmark/results/llm/jiayuinter-vllm
git commit -m "test: record remote R throughput boundary"
git push origin codex/web-audit-2026-08-18
```

### Task 4: Recover one remote transport failure inside a parallel stage

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py:555-620`
- Test: `tests/runtime/test_task_execution.py`

**Interfaces:**
- Consumes: a `TransportFailure` returned by one parallel batch and the original batch payload.
- Produces: one serial retry for that payload; no patch is merged until every batch succeeds.

- [ ] **Step 1: Write the failing test**

Add a parallel fake provider whose first call for one functional batch raises `TransportFailure` and whose serial retry returns a valid empty proposal. Assert the batch is called twice, all other batches are retained, and the stage result still has one deterministic merged result.

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `./.venv/bin/python -m pytest tests/runtime/test_task_execution.py -k transport_retry -q`

Expected: FAIL because `_complete_batches` currently raises a parallel transport failure immediately.

- [ ] **Step 3: Implement the bounded retry**

In the ordered result-merge loop, retry only `TransportFailure` from a parallel-capable model once through `_complete_batch` with the original request and payload. Let a second transport failure or any semantic/compile failure raise normally. Do not append a partial patch before all batches have returned successfully.

- [ ] **Step 4: Run the focused and full runtime tests**

```bash
./.venv/bin/python -m pytest tests/runtime/test_task_execution.py -q
./.venv/bin/ruff check src tests scripts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rflp_lite/runtime/structured_model.py tests/runtime/test_task_execution.py docs/superpowers/plans/2026-09-20-remote-r-stage-throughput.md
git commit -m "fix: retry one failed remote vertical batch"
```

## Self-review

- Scope is one subsystem: remote R-stage throughput and its provider boundary.
- Mixed-kind mode is reversible through `r_backbone_single_kind=true`.
- Parallel calls share a read-only graph snapshot; all writes still pass through deterministic patch rebasing and the existing stage merge.
- Existing F/L/P/V&V contracts, SysML, CAD, and benchmark scoring are not modified.
