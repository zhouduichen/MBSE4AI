# Remote Parallel Vertical Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove and operate one remote-LLM run that builds the complete R→F→L→P→V&V model while independent work inside each dependency-safe stage runs concurrently.

**Architecture:** Keep the five product stages ordered because downstream context depends on the committed upstream ModelGraph. Within a stage, dispatch only the existing dependency-safe task groups and independent requirement batches to the remote OpenAI-compatible endpoint; merge responses in deterministic order through the existing Validator/CAS boundary. Use the existing isolated benchmark/profile path to separate remote evidence from offline regression evidence.

**Tech Stack:** Python 3.11, pytest, FastAPI background execution, `ThreadPoolExecutor`, OpenAI-compatible vLLM, SQLite ModelGraph/CAS, existing benchmark runner, SysML v2 subset exporter/importer.

## Global Constraints

- Never start Ollama, vLLM, or any other model server on the development computer.
- Use only the SSH-forwarded Jiayu-intern endpoint for real LLM acceptance; do not stop unrelated remote GPU processes.
- Preserve ModelGraph as the only model source of truth and keep all writes on the existing Validator/CAS path.
- Keep R→F→L→P→V&V stage boundaries ordered; parallelize only independent tasks/batches with a shared immutable context snapshot.
- Keep remote `max_parallel_requests` bounded to 1–4 and default it to 2 for a single-GPU endpoint.
- Do not convert a single successful run into an early stability campaign; first collect full-chain, traceability, SysML round-trip, and editability evidence.

---

### Task 1: Lock full-lifecycle parallelism with a regression test

**Files:**
- Modify: `tests/methodology/test_workflow.py`
- Test: `tests/methodology/test_workflow.py`

**Interfaces:**
- Consumes: `WorkflowRunner.run`, `ParallelTrackingRuntime`, `tasks_for_phase`, and the existing `RunSummary` contract.
- Produces: a regression proving a configured full lifecycle reaches concurrent independent task execution without changing the phase order or final CAS behavior.

- [ ] **Step 1: Add a full lifecycle concurrency test**

Add a test next to `test_configured_runtime_parallelizes_dependency_safe_task_group`:

```python
def test_configured_full_lifecycle_parallelizes_only_independent_groups(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    RequirementInputService(repository, "p1").ensure_text_requirements(
        "系统应支持人工接管"
    )
    runtime = ParallelTrackingRuntime()
    runner = WorkflowRunner(repository, repository, runtime)
    runner.runtime_selection = SimpleNamespace(
        mode="configured", profile_id="test-llm", provider_id="test", model_id="test"
    )

    summary = runner.run("p1", force_run=True)

    assert summary.status is RunStatus.COMPLETED
    assert runtime.max_active >= 2
    assert runtime.max_active <= runtime.max_parallel_requests
    assert summary.phase is Phase.CLOSURE
    assert len(summary.completed_tasks) == 23
    stored = repository.load_run("p1", summary.run_id)
    assert stored is not None
    assert all(step.status == StepStatus.COMPLETED.value for step in stored.steps)
    assert repository.load_graph("p1").revision >= len(stored.steps)
```

- [ ] **Step 2: Run the focused test and inspect failure**

Run:

```bash
./.venv/bin/pytest -q tests/methodology/test_workflow.py::test_configured_full_lifecycle_parallelizes_only_independent_groups -vv
```

Expected: the test either passes against the current implementation or exposes a concrete rebase/phase-order defect; do not weaken the assertions to accommodate a failure.

- [ ] **Step 3: Fix only a discovered parallel lifecycle defect**

If the test fails, change only the affected code in `src/rflp_lite/methodology/workflow.py`. Preserve `_PARALLEL_PHASE_GROUPS`, immutable snapshot preparation, deterministic `executor.map` order, and `_rebase_parallel_patch` before CAS. A successful response must still be accepted by `_accept_task_response`; a transport or semantic failure must retain its existing recovery/status behavior.

- [ ] **Step 4: Run the focused workflow regression**

Run:

```bash
./.venv/bin/pytest -q tests/methodology/test_workflow.py -k 'parallel or configured_runtime'
```

Expected: all matching tests pass and at least one test observes `max_active >= 2`.

- [ ] **Step 5: Commit the test/defect fix**

```bash
git add tests/methodology/test_workflow.py src/rflp_lite/methodology/workflow.py
git commit -m "test: cover parallel full lifecycle execution"
```

### Task 2: Verify the remote profile and endpoint without local inference

**Files:**
- Inspect: `docs/REMOTE_LLM_TESTING.md`
- Inspect: `/tmp/ai4mbse-jiayuinter-live-20260917/llm-profiles.json`
- Create outside repository: `/tmp/ai4mbse-remote-benchmark-20260917/`

**Interfaces:**
- Consumes: SSH alias `Jiayu-intern`, local tunnel `127.0.0.1:18000`, and `model-profile` normalization.
- Produces: an isolated remote profile with Qwen thinking disabled, `vertical_feedback=false`, `vertical_batch_size=2`, and `max_parallel_requests=2`.

- [ ] **Step 1: Confirm the remote service before opening a test run**

Run:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 Jiayu-intern \
  'ss -ltn | grep -E ":8000($| )"; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader,nounits'
curl --fail --max-time 5 http://127.0.0.1:18000/v1/models
```

Expected: the endpoint lists `qwen3.5-controller`. If port 8000 is absent or GPU memory is unavailable, stop this task and report the external resource condition; do not kill unrelated jobs or launch a local server.

- [ ] **Step 2: Validate the isolated profile**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-live-20260917 \
  ./.venv/bin/python -c 'from rflp_lite.application.llm_profiles import LLMProfileService; print(LLMProfileService().get("jiayuinter-vllm"))'
```

Expected: remote location, OpenAI-compatible provider, `think=false`, `chat_template_kwargs.enable_thinking=false`, `vertical_feedback=false`, and parallel request cap `2`.

### Task 3: Run one real parallel vertical acceptance

**Files:**
- Create outside repository: `/tmp/ai4mbse-remote-benchmark-20260917/`
- Inspect: `tests/mbse_benchmark/runners/benchmark_runner.py`
- Inspect: `src/rflp_lite/application/model_generation.py`
- Inspect: `src/rflp_lite/application/sysml_v2.py`

**Interfaces:**
- Consumes: the isolated profile from Task 2 and `tests/mbse_benchmark/run_benchmark.py --track llm --path vertical`.
- Produces: one remote run artifact that records actual profile/provider/model, per-stage results, batch diagnostics, ModelGraph snapshot, traceability, deliverables, and SysML text.

- [ ] **Step 1: Run the focused remote vertical case once**

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-live-20260917 \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile jiayuinter-vllm --path vertical \
  --case CASE-04 --repeats 1 --timeout 900 --baseline bare \
  --output-dir /tmp/ai4mbse-remote-benchmark-20260917/vertical
```

Expected: one completed or reviewable remote run; no local model process; for multi-requirement stages the artifact includes `batch_count` and the provider observes no more than two in-flight requests.

- [ ] **Step 2: Audit the vertical result against product evidence**

Run a read-only audit over the generated JSON artifacts and assert:

```python
assert result["runtime"]["model_location"] == "remote"
assert len(result["stage_results"]) == 5
assert result["deliverable"]["snapshot_hash"] == result["snapshot_hash"]
assert result["traceability"]["end_to_end_complete_count"] >= 1
assert result["sysml_text"]
```

Then call the existing SysML importer on the emitted `model.sysml`, compare entity/relation IDs and graph-reference payload fields, and apply one existing Review/Edit operation to prove a new CAS revision is created.

- [ ] **Step 3: Preserve honest status for incomplete remote output**

If any stage is `needs_review`, keep the artifact and record the exact completion issue and candidate status. Do not replace the remote proposal with an offline success claim; the typed completion bridge may remain visible as its existing offline provenance.

### Task 4: Run the compatibility 23-task acceptance after the vertical chain

**Files:**
- Create outside repository: `/tmp/ai4mbse-remote-benchmark-20260917/`
- Inspect: `tests/mbse_benchmark/reports/`

**Interfaces:**
- Consumes: the same isolated remote profile and the lifecycle benchmark path.
- Produces: one dependency-safe 23-task run showing same-group concurrency, ordered phase boundaries, deterministic CAS merge, and final lifecycle artifacts.

- [ ] **Step 1: Run the lifecycle case once**

```bash
RFLP_CONFIG_DIR=/tmp/ai4mbse-jiayuinter-live-20260917 \
  ./.venv/bin/python tests/mbse_benchmark/run_benchmark.py \
  --track llm --profile jiayuinter-vllm --path lifecycle \
  --case CASE-04 --repeats 1 --timeout 2400 --baseline harness \
  --output-dir /tmp/ai4mbse-remote-benchmark-20260917/lifecycle
```

Expected: the run ledger contains all 23 task IDs or an explicit bounded failure; independent groups overlap, while Operational→Functional→Logical/Physical→Assurance remains ordered.

- [ ] **Step 2: Compare the two product paths**

Confirm both paths write the same typed ModelGraph contract and that the five-stage product path remains the primary user-facing result. Treat lifecycle output as compatibility/methodology evidence, not as a replacement for the vertical product acceptance.

### Task 5: Run repository gates and push evidence-bearing changes

**Files:**
- Inspect: all changed files
- Inspect: `docs/REMOTE_LLM_TESTING.md`

**Interfaces:**
- Consumes: completed code/tests and any remote artifacts kept outside the repository.
- Produces: clean, pushed branch and a concise evidence report with any unresolved remote resource blocker.

- [ ] **Step 1: Run the full local verification without a model profile**

```bash
./.venv/bin/python scripts/verify_full.py
```

Expected: compileall, pytest, architecture metrics, Ruff, import-linter, and `git diff --check` all pass; the command must not contact or start a model server.

- [ ] **Step 2: Review the final diff and repository state**

```bash
git diff --check
git status --short --branch
git log -5 --oneline
```

Expected: only intentional changes are present; benchmark artifacts remain outside the repository.

- [ ] **Step 3: Push the branch**

```bash
git push origin codex/web-audit-2026-08-18
```

- [ ] **Step 4: Report evidence and remaining gaps**

Report separately: local deterministic gates, parallel regression evidence, real remote vertical evidence, real remote 23-task evidence, SysML round-trip/editability evidence, and any external GPU/service blocker. Do not claim the broad product goal complete while any required category lacks direct evidence.

## Plan Self-Review

- The plan preserves the full product order and does not substitute repeated stability runs for vertical completion.
- Parallelism is tested at both batch and full lifecycle task-group levels, but no cross-stage parallelism is introduced.
- Remote inference is isolated from local verification and all generated artifacts stay outside the repository.
- A failed or incomplete LLM proposal remains reviewable; offline bridge provenance is not misreported as provider success.
- The plan has no placeholder requirements; every implementation/test step names concrete files, commands, and expected evidence.
