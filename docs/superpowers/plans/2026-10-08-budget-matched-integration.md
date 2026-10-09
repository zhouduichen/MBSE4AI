# Budget-Matched Integration Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing `budget_matched` A–E comparison through the GitHub Integration workflow while keeping scheduled runs deterministic and fail-closed.

**Architecture:** `workflow_dispatch` accepts a comparison mode and optional total output budget. A small Bash validation step resolves the effective mode (`natural` for schedule, explicit dispatch value otherwise), rejects a missing/invalid budget for `budget_matched`, and exports the resolved values. The detached campaign manifest includes those values and passes them to `run_benchmark.py`; existing comparison invariants remain the authority for PASS/FAIL.

**Tech Stack:** GitHub Actions YAML, Bash, Python static contract tests, existing `run_benchmark.py` comparison CLI.

## Global Constraints

- Scheduled Integration runs use `natural` mode unless an explicit future scheduler configuration is added.
- `budget_matched` requires a positive integer `total_output_token_budget`.
- All five scenarios continue to use the same resolved model, input, evaluator, normalizer, per-call cap, and repeat count.
- A campaign submission is not experiment evidence; only a terminal complete PASS comparison is evidence.
- Do not modify Harness, CAD, MDO, or UI behavior.

---

### Task 1: Define and validate workflow comparison controls

**Files:**
- Modify: `.github/workflows/integration.yml:5-31,255-278`
- Test: `tests/integration/test_integration_contract.py:20-100`

**Interfaces:**
- Consumes: `workflow_dispatch` inputs and `github.event_name`.
- Produces: `AI4MBSE_COMPARISON_MODE` and `AI4MBSE_TOTAL_OUTPUT_TOKEN_BUDGET` environment values for the detached campaign step.

- [ ] **Step 1: Write the failing contract assertions**

  Assert that the workflow declares `comparison_mode` with `natural` and `budget_matched` choices, declares `total_output_token_budget`, records the resolved mode in the summary, and rejects a non-positive budget for `budget_matched`.

- [ ] **Step 2: Run the focused test and verify it fails**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/integration/test_integration_contract.py
  ```

  Expected: FAIL because the workflow has no comparison-mode dispatch input or validation block.

- [ ] **Step 3: Add the workflow inputs and validation**

  Add:

  ```yaml
  comparison_mode:
    description: "A–E comparison budget mode"
    required: true
    default: natural
    type: choice
    options: [natural, budget_matched]
  total_output_token_budget:
    description: "Per-repeat total output-token cap for budget_matched"
    required: false
    default: ""
    type: string
  ```

  In the remote-LLM control step, resolve `natural` for scheduled events and dispatch input otherwise. Reject any mode outside the two CLI values; reject a missing, non-numeric, or non-positive total budget in `budget_matched`; reject a supplied total budget in `natural`. Export the validated values through `$GITHUB_ENV` and print both in `$GITHUB_STEP_SUMMARY`.

- [ ] **Step 4: Run the focused test and verify it passes**

  Run the command from Step 2. Expected: all integration contract tests PASS.

- [ ] **Step 5: Commit the workflow contract**

  ```bash
  git add .github/workflows/integration.yml tests/integration/test_integration_contract.py
  git commit -m "ci: expose budget matched integration mode"
  ```

### Task 2: Pass resolved controls into the detached campaign

**Files:**
- Modify: `.github/workflows/integration.yml:300-370`
- Test: `tests/integration/test_integration_contract.py:20-100`

**Interfaces:**
- Consumes: `AI4MBSE_COMPARISON_MODE` and `AI4MBSE_TOTAL_OUTPUT_TOKEN_BUDGET` from Task 1.
- Produces: manifest fields `comparison_mode` and `total_output_token_budget`, plus matching CLI arguments.

- [ ] **Step 1: Extend the contract assertions**

  Assert that the manifest-building Python block writes `comparison_mode`, writes `total_output_token_budget`, and passes `--comparison-mode` and `--total-output-token-budget` to the remote command conditionally for budget-matched runs.

- [ ] **Step 2: Run the focused test and verify it fails**

  ```bash
  .venv/bin/python -m pytest -q tests/integration/test_integration_contract.py
  ```

  Expected: FAIL on the missing manifest/command assertions.

- [ ] **Step 3: Update manifest generation**

  Build the command with the resolved mode, append the total-budget argument only when the resolved budget is non-empty, and store both values in the manifest:

  ```python
  command += ["--comparison-mode", os.environ["AI4MBSE_COMPARISON_MODE"]]
  if os.environ["AI4MBSE_TOTAL_OUTPUT_TOKEN_BUDGET"]:
      command += ["--total-output-token-budget", os.environ["AI4MBSE_TOTAL_OUTPUT_TOKEN_BUDGET"]]
  payload["comparison_mode"] = os.environ["AI4MBSE_COMPARISON_MODE"]
  payload["total_output_token_budget"] = os.environ["AI4MBSE_TOTAL_OUTPUT_TOKEN_BUDGET"] or None
  ```

- [ ] **Step 4: Run focused tests and static checks**

  ```bash
  .venv/bin/python -m pytest -q tests/integration/test_integration_contract.py
  .venv/bin/ruff check tests/integration/test_integration_contract.py
  git diff --check
  ```

  Expected: all tests and checks PASS.

- [ ] **Step 5: Commit the manifest wiring**

  ```bash
  git add .github/workflows/integration.yml tests/integration/test_integration_contract.py
  git commit -m "ci: record comparison budget in campaign manifest"
  ```

### Task 3: Document and verify the implementation

**Files:**
- Modify: `docs/mbse_benchmark_v032_acceptance_status.md`
- Test: full repository CI commands

**Interfaces:**
- Consumes: the workflow contract and manifest behavior from Tasks 1–2.
- Produces: an auditable statement that natural is the scheduled default and budget-matched is dispatch-selectable, without claiming a real external run before one exists.

- [ ] **Step 1: Update the acceptance row for item 10**

  Record that the implementation supports both modes through the CLI and Integration dispatch, while marking real budget-matched remote evidence as NOT YET VERIFIED until a terminal campaign exists.

- [ ] **Step 2: Run local gates**

  ```bash
  .venv/bin/python -m pytest -q
  .venv/bin/ruff check src tests scripts
  .venv/bin/python -m compileall -q src tests scripts
  .venv/bin/lint-imports
  .venv/bin/python scripts/architecture_metrics.py
  .venv/bin/python tests/mbse_benchmark/run_benchmark.py --track robustness
  ```

  Expected: all commands PASS; robustness output may be removed if generated under an ignored report directory.

- [ ] **Step 3: Push and verify GitHub checks**

  ```bash
  git push origin HEAD:codex/mbse-v032-fair-evaluation
  gh run list --repo zhouduichen/MBSE4AI --branch codex/mbse-v032-fair-evaluation --limit 4
  gh pr view 2 --repo zhouduichen/MBSE4AI --json headRefOid,state,mergeStateStatus,reviewDecision,statusCheckRollup
  ```

  Expected: push and PR `CI / quality` checks PASS; PR remains review-gated unless an authorized reviewer approves it.

- [ ] **Step 4: Commit the evidence update**

  ```bash
  git add docs/mbse_benchmark_v032_acceptance_status.md
  git commit -m "docs: record budget matched integration support"
  ```

## Self-review

- Scope is limited to Integration dispatch controls, manifest reproducibility, tests, and evidence documentation.
- Scheduled runs remain natural-mode and cannot silently inherit a budget value.
- Budget-matched mode cannot start without a positive total cap and cannot claim PASS without the existing complete-comparison invariants.
- The plan does not claim external runner availability or a completed remote experiment; those remain runtime evidence requirements.
