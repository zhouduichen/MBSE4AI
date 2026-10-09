# Remote LLM Campaign Collector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real A–E remote benchmark resumable and evidence-bearing even when a GitHub runner or the remote GPU scheduler interrupts a long foreground SSH step.

**Architecture:** A submit job stages an immutable repository/profile snapshot and launches one detached remote campaign with an atomic status manifest. A short collector job later reads that manifest, downloads terminal results, and validates the existing A–E comparison invariants. `success` is reserved for a complete comparison whose report status is `PASS`; running, interrupted, scheduler-preempted, and partial campaigns remain explicit non-PASS evidence.

**Tech Stack:** GitHub Actions YAML, Python standard library on the remote server, existing `run_benchmark.py`, OpenSSH/scp, pytest.

## Global Constraints

- Do not expand CAD, MDO, UI, or Harness core execution architecture.
- A–E must continue to use the existing same-input, ExternalEvaluator-only ground truth, ModelGraph normalizer, and telemetry invariants.
- A detached campaign must never create a fallback graph or rewrite a failed comparison as PASS.
- The remote wrapper may create campaign-scoped files only below the configured campaign root; it must not delete scheduler handoff markers or restart vLLM.
- A collector may copy results read-only and must preserve partial evidence when the campaign is interrupted.
- `main` remains protected by the existing `CI / quality` check; external evidence is not substituted for ordinary CI.

---

### Task 1: Define and test the campaign state contract

**Files:**
- Create: `scripts/remote_llm_campaign.py`
- Create: `tests/integration/test_remote_llm_campaign.py`

**Interfaces:**
- `CampaignState` serializes `campaign_id`, `run_id`, `state`, `created_at`, `started_at`, `finished_at`, `pid`, `exit_code`, `command_sha256`, `profile`, `comparison_mode`, `results_dir`, `reports_dir`, and `error`.
- `write_status(path, payload)` writes JSON through a same-directory temporary file followed by `os.replace`.
- `run_campaign(manifest_path)` executes only the manifest's argv with `subprocess.run`, writes `running`, then a terminal `completed`, `failed`, or `interrupted` state.
- `status_is_evidence_ready(payload)` returns true only for `state == "completed"`, `exit_code == 0`, and a report whose `status == "PASS"`.

- [ ] **Step 1: Write failing tests** for atomic status shape, command hashing, terminal-state rules, and rejection of partial/failed reports.
- [ ] **Step 2: Run** `pytest -q tests/integration/test_remote_llm_campaign.py` and verify the new tests fail because the wrapper does not exist.
- [ ] **Step 3: Implement** the standard-library wrapper without shell interpolation, fallback generation, scheduler-marker deletion, or process killing.
- [ ] **Step 4: Run** the focused tests and verify PASS.

### Task 2: Add detached submit and explicit collection to integration workflow

**Files:**
- Modify: `.github/workflows/integration.yml`
- Create: `.github/workflows/integration-remote-collector.yml`
- Modify: `docs/mbse_benchmark_external_ci.md`

**Interfaces:**
- `integration.yml` submits a campaign and uploads a `pending` manifest; it no longer waits on a foreground SSH benchmark for the full A–E duration.
- `integration-remote-collector.yml` accepts `campaign_id` for manual collection and runs on a non-empty schedule to discover/collect terminal campaigns.
- The collector downloads `a_to_e_comparison.json`, `reproducibility_manifest.json`, reports, results, and the campaign status manifest; it fails if terminal evidence is incomplete and reports `pending` without claiming PASS when a campaign is still running.

- [ ] **Step 1: Add** workflow inputs and repository variables for a persistent campaign root and collector mode.
- [ ] **Step 2: Replace** the long foreground remote command with immutable staging plus detached `python scripts/remote_llm_campaign.py run` and a status readback.
- [ ] **Step 3: Add** the collector workflow with SSH/scp, read-only artifact collection, status validation, and `if: always()` upload.
- [ ] **Step 4: Add** the schedule-safe contract and evidence-policy documentation, including the distinction between submitted, pending, failed, and PASS campaigns.

### Task 3: Verify local quality and workflow contracts

**Files:**
- Modify: `tests/integration/test_integration_contract.py` if the workflow contract needs a new assertion.
- Modify: `docs/mbse_benchmark_v032_acceptance_status.md` with authoritative run 36528400246 evidence.

- [ ] **Step 1: Run** `pytest -q tests/integration/test_remote_llm_campaign.py tests/integration/test_integration_contract.py`.
- [ ] **Step 2: Run** `ruff check src tests scripts`, `python -m compileall -q src tests scripts`, `lint-imports`, architecture metrics, and the robustness benchmark.
- [ ] **Step 3: Validate** both workflow YAML files and inspect the rendered GitHub job conditions without starting a new remote experiment.
- [ ] **Step 4: Commit** the focused workflow/collector change and push it to the existing PR branch.

### Task 4: Run and audit real evidence

- [ ] **Step 1:** Submit one campaign only after the remote Controller lease is stable and the scheduler has no active worker handoff.
- [ ] **Step 2:** Collect it through the collector workflow after the remote status is terminal.
- [ ] **Step 3:** Require exact input audit, evaluator isolation, orthogonal controls, real calls/tokens/latency/cost, and three repeats before treating the result as evidence.
- [ ] **Step 4:** Update the 15-item acceptance matrix; leave any missing criterion explicitly incomplete.
