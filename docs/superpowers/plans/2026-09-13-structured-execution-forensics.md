# Real-model Structured Execution Reliability Forensics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an evidence-backed forensic report for the five PR09 lifecycle runs and reproduce the captured `duplicate local_ref` compiler failure without changing runtime behavior.

**Architecture:** Read each SQLite run database through a read-only connection and normalize persisted task diagnostics into a stable JSON report. Replay only the captured `system_definition` proposal through the current `ProposalCompiler` with an in-memory request/context; verify that compilation fails closed and that no repository mutation occurs.

**Tech Stack:** Python 3, stdlib `sqlite3`/`json`/`hashlib`, the repository's `rflp_lite` domain APIs, and `apply_patch` for the report artifact.

## Global Constraints

- Do not rerun the 23-task lifecycle during this phase.
- Do not modify Harness, compiler, retry, provider, or benchmark source code.
- Open all existing run databases read-only.
- Do not auto-rename duplicate `local_ref` values.
- Do not expose provider credentials or unrelated benchmark worktree changes.
- Record inference separately from directly observed fields.

---

### Task 1: Extract and classify persisted run diagnostics

**Files:**
- Read: `/tmp/ai4mbse-pr09-lifecycle-20260911.2ZQa7T/run-{a,b,c,d,e}/.rflp/model.db`
- Read: `/Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/application/llm_profiles.py`

**Interfaces:**
- Consumes: SQLite `runs`, `tasks`, `task_attempts`/diagnostic records, and repository graph metadata.
- Produces: normalized records containing `task_id`, failure stage/code, retry count, response/schema hashes and sizes, provider usage, output budget, context window, and repository revision deltas.

- [x] **Step 1: Open the five databases read-only and identify the diagnostic-bearing tables and columns.**

  Run a Python inspection using `sqlite3.connect("file:<path>?mode=ro", uri=True)` and print only table/column names and row counts.

- [x] **Step 2: Parse the persisted diagnostic JSON and provider usage fields.**

  Normalize `finish_reason`, `prompt_eval_count`, `eval_count`, `total_duration`, raw response sizes/hashes, schema hashes, and task/run status without emitting secrets.

- [x] **Step 3: Assign each terminal failure to one mutually exclusive class.**

  Use `structural.truncated`, `structural.invalid_json`, `structural.schema_validation`, `structural.provider_grammar`, `compiler.proposal_compile`, `transport`, or `semantic`; preserve the original stage/code alongside the classification.

- [x] **Step 4: Check the source defaults and actual observed request budget.**

  Record profile-level omission as `null`, source default context window as `8192`, and the observed task request/evaluation budget as `2000`; label the latter as observed rather than inferred from the profile file.

### Task 2: Write the forensic JSON artifact

**Files:**
- Create: `/Users/huangjiahao/Downloads/AI4MBSE/docs/superpowers/artifacts/pr09/structured-execution-forensics-20260913.json`

**Interfaces:**
- Consumes: Task 1 normalized records and aggregate counts.
- Produces: A machine-readable report that can be compared with later narrow sequential runs.

- [x] **Step 1: Add report metadata and experiment conditions.**

  Include baseline commit `7bf00c2f9ab2e31287a7539b08e2ad7ee25258e4`, fixture path, Ollama provider/model, run directory, and report date.

- [x] **Step 2: Add per-run and per-terminal-attempt forensic records.**

  Include the exact fields `task_id`, `stage`, `code`, `finish_reason`, `retry_count`, `initial_raw_response_hash`, `initial_raw_response_size`, `raw_response_hash`, `raw_response_size`, `schema_hash`, `prompt_eval_count`, `eval_count`, `total_duration_ms`, `max_output_tokens`, `context_window`, and `request_output_budget`.

- [x] **Step 3: Add aggregate funnel counts and an evidence interpretation.**

  Record four truncated structural failures, one compiler failure, zero invalid JSON/schema/grammar/transport/semantic-repair outcomes, and explicitly distinguish observed facts from the output-budget hypothesis.

- [x] **Step 4: Add repository safety and workflow outcomes.**

  Record completed/failed/blocked totals, revision/entity/relation changes, patch counts, invalid repository writes, and dependency blocking observations.

### Task 3: Reproduce the duplicate-local-ref compiler failure

**Files:**
- Read: `/tmp/ai4mbse-pr09-lifecycle-20260911.2ZQa7T/run-e/.rflp/model.db`
- Read: `/Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/methodology/proposal_compiler.py`
- Read: `/Users/huangjiahao/Downloads/AI4MBSE/src/rflp_lite/methodology/executor.py`
- Modify: `/Users/huangjiahao/Downloads/AI4MBSE/docs/superpowers/artifacts/pr09/structured-execution-forensics-20260913.json`

**Interfaces:**
- Consumes: Captured `system_definition` raw response and the current `compile_task_proposal` API.
- Produces: A reproduction record with duplicate counts, compiler diagnostic, `auto_renamed=false`, and `repository_mutated=false`.

- [x] **Step 1: Extract the full captured response excerpt from run E.**

  Parse the persisted terminal diagnostic, decode its JSON payload, and count every `entities[].local_ref`; do not alter the payload.

- [x] **Step 2: Build an isolated `TaskExecutionRequest` and context.**

  Load the run-E graph and evidence through read-only repository APIs, construct the `system_definition` request with token budget `2000`, and call `compile_task_proposal(request, payload)` without opening a write transaction.

- [x] **Step 3: Assert the current compiler rejects the duplicate reference.**

  Capture the exact `ContractViolation` message and verify that the graph revision and entity/relation counts are unchanged before and after replay.

- [x] **Step 4: Update the artifact with the reproduction result.**

  Add the duplicate ref and count, relation endpoint counts, exact rejection, and the no-auto-rename/no-mutation invariants.

### Task 4: Verify artifact integrity and leave code untouched

**Files:**
- Read: `git status --short`
- Read: `/Users/huangjiahao/Downloads/AI4MBSE/docs/superpowers/artifacts/pr09/structured-execution-forensics-20260913.json`

**Interfaces:**
- Consumes: The completed artifact and existing worktree state.
- Produces: A validated report and a concise next-experiment recommendation.

- [x] **Step 1: Parse the artifact as JSON and validate required keys and aggregate totals.**

  Confirm the report parses, five runs are present, four structural truncations and one compiler failure are represented, and no credentials are present.

- [x] **Step 2: Confirm no source or benchmark files changed during the forensic run.**

  Compare `git status --short` against the known pre-existing dirty benchmark paths; the only new file may be the forensic artifact.

- [x] **Step 3: Report the decision boundary.**

  Conclude that output-budget exhaustion is the leading hypothesis, duplicate refs are reproducible compiler rejection, and the next action is the planned narrow sequential stability test rather than another 23-task run.
