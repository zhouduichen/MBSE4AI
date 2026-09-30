# Output Budget Stability Experiment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether increasing only the effective `max_output_tokens` from the known 2000-token failure baseline makes the three-task sequential dependency chain structurally reliable.

**Architecture:** Run the existing workflow components against fresh fixture projects in isolated temporary workspaces, narrowing the operational task list at runtime to `system_definition → stakeholder_analysis → stakeholder_requirements`. Use the PR09 baseline source commit, keep context construction and sampling fixed, instrument provider calls for initial/repair budgets, and emit one aggregate JSON artifact per budget matrix.

**Tech Stack:** Python 3, the repository's `V2Services`/`WorkflowRunner`/`TaskExecutor`, native Ollama OpenAI-compatible adapter, SQLite run ledger, and `apply_patch` for the runner/report files.

## Global Constraints

- Keep model `qwen3.5:9b-q8_0`, temperature, seed, prompt, TaskSpec, compiler, and fixture unchanged.
- Use PR09 baseline commit `7bf00c2f9ab2e31287a7539b08e2ad7ee25258e4` as the runtime source.
- Treat 2000 as the known baseline from the five existing lifecycle runs; do not spend another 2000-token live matrix.
- Run only budgets 3000 and 4000, five repetitions each; run 6000 only if 4000 is not stable.
- Keep context construction fixed at effective context budget 2000, default context output reserve, and prompt reserve 256.
- Do not modify Harness source, Prompt, TaskSpec, Compiler, provider configuration, or model.
- Do not auto-rename `local_ref` values.
- Preserve provider diagnostics and raw-response hashes only; do not persist credentials or raw prompts in the artifact.

---

### Task 1: Build the isolated narrow-chain experiment runner

**Files:**
- Create: `scripts/pr09_output_budget_experiment.py`

**Interfaces:**
- Consumes: active Ollama profile endpoint/model and the campus delivery robot fixture.
- Produces: one JSON result line per repetition and one aggregate JSON object for each budget.

- [x] **Step 1: Define the fixed experiment constants and runtime configuration.**

  Use the active profile's base URL/model, force `temperature=0.0`, preserve the active profile's seed value, set `max_output_tokens` to the selected budget, and do not add a context-window override to the provider config.

- [x] **Step 2: Wrap the provider completion callback.**

  Record task id, call ordinal (`initial` or `repair`), actual `max_tokens`, `finish_reason`, `prompt_eval_count`, `eval_count`, total duration, response size, and response hash; delegate the actual request unchanged to `chat_completion`.

- [x] **Step 3: Narrow only the operational task enumeration at runtime.**

  Temporarily replace the workflow module's `tasks_for_phase(Phase.OPERATIONAL)` with the three-task tuple and restore it in `finally`; keep all source files unchanged.

- [x] **Step 4: Preserve the previous context budget while changing output budget.**

  Use a `WorkflowRunner` subclass whose `_configured_output_budget()` returns `False`, so the existing default context reserve remains active while `_output_budget()` returns the selected 3000 or 4000 request budget.

- [x] **Step 5: Seed a fresh fixture project for each repetition.**

  Create a unique temporary workspace, seed the unchanged fixture, run the narrowed operational phase, and query the SQLite ledger for all three task statuses, diagnostics, patches, revisions, entity/relation counts, and dependency blocking.

### Task 2: Execute the 3000-token matrix

**Files:**
- Read: `scripts/pr09_output_budget_experiment.py`
- Create: `docs/superpowers/artifacts/pr09/output-budget-3000-20260913.json`

**Interfaces:**
- Consumes: Task 1 runner with budget `3000`.
- Produces: Five sequential-chain runs and an aggregate funnel for budget utilization and retry behavior.

- [x] **Step 1: Run five fresh sequential chains at 3000 tokens.**

  Run the script with `--budget 3000 --repetitions 5` using the PR09 baseline source and the active Ollama endpoint.

- [x] **Step 2: Validate the 3000-token run output.**

  Confirm every task attempt records `requested max_output_tokens=3000`, every structural retry records its actual budget, and no run is silently treated as successful when a task is failed or blocked.

- [x] **Step 3: Write the 3000-token aggregate artifact.**

  Include per-run statuses, provider calls, output utilization `eval_count / max_output_tokens`, finish reasons, compiler/duplicate-ref counts, latency, patch/revision deltas, and the count of recovered/exhausted structural retries.

### Task 3: Execute the 4000-token matrix and apply the stopping rule

**Files:**
- Read: `scripts/pr09_output_budget_experiment.py`
- Create: `docs/superpowers/artifacts/pr09/output-budget-4000-20260913.json`

**Interfaces:**
- Consumes: Task 1 runner with budget `4000`.
- Produces: Five sequential-chain runs and the same comparable aggregate funnel.

- [x] **Step 1: Run five fresh sequential chains at 4000 tokens.**

  Run the script with `--budget 4000 --repetitions 5` under the same source, model, endpoint, fixture, context, and sampling conditions.

- [x] **Step 2: Validate the 4000-token run output.**

  Confirm the only changed request budget is 4000 and distinguish `finish_reason=stop` from responses that still terminate at the cap.

- [x] **Step 3: Decide whether 6000 is necessary.**

  Skip 6000 when the five 4000-token chains have zero truncated structural failures and zero structural retry exhaustion; otherwise record why the 4000 budget did not meet the stability criterion before considering 6000.

### Task 4: Consolidate and verify the experiment evidence

**Files:**
- Create: `docs/superpowers/artifacts/pr09/output-budget-stability-20260913.json`
- Read: `docs/superpowers/artifacts/pr09/structured-execution-forensics-20260913.json`

**Interfaces:**
- Consumes: Known 2000 baseline plus 3000/4000 matrices.
- Produces: A comparison report and the next lifecycle decision; no source mutation.

- [x] **Step 1: Compare budget utilization and failure classes.**

  Report per-budget counts for completed/failed/blocked tasks, structural first-pass validity, retry recovery/exhaustion, compiler failures, duplicate refs, semantic repair, provider transport, and latency.

- [x] **Step 2: Check the retry-budget hypothesis.**

  Explicitly report `initial_max_tokens` and `repair_max_tokens`; if they are equal at each budget, state that the current retry does not create extra output space.

- [x] **Step 3: Apply the predefined stability gate.**

  Mark 4000 as the minimum stable budget only if all five chains have no truncated structural terminal failure and no structural retry exhaustion; otherwise keep output-budget sufficiency failed/investigating.

- [x] **Step 4: State the next action without modifying code.**

  If stable, schedule one 23-task lifecycle run using the selected budget; if not, preserve the evidence and do not enter the semantic MBSE benchmark.

## Execution checkpoint (2026-09-13)

The 3000-token matrix completed, but it was not a clean budget comparison: two runs failed at the compiler on duplicate `local_ref`, one failed at structural JSON decoding, and two failed on provider transport. After the endpoint recovered, the 4000-token matrix completed with five identical `system_definition` compiler failures, zero transport failures, and 17.1% output utilization. The stopping rule therefore skips 6000: the current chain is blocked by proposal structure, not output length.
