# Methodology Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Make Logical architecture synthesis explicitly evaluate timing coordination and safety-isolation evidence, then expose the same decision evidence through ModelGraph payloads, LLM guidance, Controller, Workbench and Architecture Report while preserving the existing physical feasibility contract.

**Architecture:** Extend the pure architecture_synthesis result with normalized timing pairs, explicit safety-separation pairs, candidate cut/violation counts and structured violation summaries. Reuse that result in the existing runtime payload builder and methodology report; no new persistence truth or relation vocabulary is introduced. The product remains usable offline, and a configured remote LLM remains the only permitted live model path.

**Tech Stack:** Python 3.11+, dataclasses, existing Typed ModelGraph, JSON-compatible payloads, pytest, Ruff, Import Linter.

## Global Constraints

- ModelGraph remains the only model truth; SysML, Workbench and reports are projections.
- synthesize_architecture(graph) stays read-only and deterministic; it must not call an LLM or write Repository state.
- Missing measurement is not a physical conflict; physical status remains exactly feasible, infeasible or needs_measurement.
- Natural-language safety strings without explicit Function endpoints must not become inferred safety pairs.
- Do not add a dependsOn relation predicate or a second state machine.
- Do not start or install a model on this Mac; live LLM calls, if available, use an explicit remote Profile only.
- Do not add repeated stability campaigns; verification is a focused unit, vertical E2E and existing full regression.

## File Map

- Modify: src/rflp_lite/methodology/architecture_synthesis.py — normalize timing/safety evidence and score Logical candidates.
- Modify: src/rflp_lite/methodology/architecture_reasoning.py — persist safety basis and candidate decision fields.
- Modify: src/rflp_lite/runtime/rule_based.py — pass source safety evidence into LogicalComponent reasoning payloads.
- Modify: src/rflp_lite/methodology/engine.py — expose bounded timing/safety metrics and guidance fields.
- Modify: src/rflp_lite/application/deliverables.py — render the new architecture decision evidence from the existing report mapping.
- Modify: docs/CURRENT_ARCHITECTURE.md and docs/DEVELOPMENT_STATUS.md — record the delivered boundary.
- Create: tests/methodology/test_architecture_reasoning_v2.py — focused evidence and scoring tests.
- Modify: tests/e2e/test_vertical_model_generation.py — assert persistence through Workbench and SysML.

### Task 1: Add failing tests for explicit timing and safety evidence

Files:
- Create tests/methodology/test_architecture_reasoning_v2.py.
- Modify tests/methodology/test_architecture_synthesis.py.

Interfaces:
- Consume make_entity, ModelGraph, Relation and synthesize_architecture.
- Produce expectations for LogicalArchitectureCandidate.timing_constraint_count, timing_cut_count, safety_isolation_count, safety_violation_count and constraint_violations.

- [x] Step 1: Write the failing tests.

Create two validated Functions. Give both the same timing_constraints string. Give one Function a safety_isolation object whose function_ids explicitly name both canonical Function IDs and whose must_separate value is true. Assert that one_component_per_function reports one timing cut and zero safety violations, while shared_coordinator reports one safety violation and a violation record with kind safety_isolation. Add a graph whose Functions contain only safety_isolation string values and assert every candidate has safety_isolation_count equal to zero. Assert every result is JSON serializable.

- [x] Step 2: Run the focused test and verify it fails.

Run: .venv/bin/python -m pytest -q tests/methodology/test_architecture_reasoning_v2.py

Expected: FAIL because the candidate does not yet expose the new timing/safety fields.

### Task 2: Normalize evidence and score Logical candidates

Files:
- Modify src/rflp_lite/methodology/architecture_synthesis.py in LogicalArchitectureCandidate, _logical_candidates, _score_logical and _function_links.
- Test tests/methodology/test_architecture_reasoning_v2.py.

Interfaces:
- Consume Function payload keys timing_constraints, safety_isolation and safety_constraints.
- Produce candidate fields timing_constraint_count, timing_cut_count, safety_isolation_count, safety_violation_count and constraint_violations; _function_links keys timing and safety_isolation.

- [x] Step 1: Add typed candidate fields with defaults.

Add timing_constraint_count, timing_cut_count, safety_isolation_count, safety_violation_count and constraint_violations after the existing required fields. Give all new fields defaults so old positional construction remains valid. Include the fields in as_dict(), converting violation mappings to copied JSON lists.

- [x] Step 2: Add deterministic endpoint normalization.

Implement _timing_pairs(functions) and _safety_pairs(functions). Equal non-empty timing string labels shared by at least two Functions form pairs. Timing objects use function_ids or members only when every endpoint resolves. Safety objects use function_ids or members only when every endpoint resolves and must_separate is the boolean true. Strings and unresolved IDs form no safety pair. Return sorted unique pairs and deterministic constraint metadata; do not infer a pair from a plain natural-language safety sentence.

- [x] Step 3: Include the evidence in _function_links().

Return the existing shared_state, dependency, flows, all and flow_pairs keys plus timing and safety_isolation. Keep timing and safety pairs out of all: timing is an evaluation cost and safety is a separation constraint, not evidence that Functions belong in one component.

- [x] Step 4: Apply deterministic penalties.

In _score_logical(), count a timing cut when a timing pair crosses partitions and a safety violation when a required-separation pair stays in one partition. Keep the existing cohesion, balance, dependency and flow calculations. Use penalties of 6 points per timing cut and 25 points per safety violation, clamp the result to 0..100, and emit one record per safety violation with kind, function_ids and a message. Preserve score-descending and alternative-name tie ordering.

- [x] Step 5: Run focused and regression tests.

Run: .venv/bin/python -m pytest -q tests/methodology/test_architecture_reasoning_v2.py tests/methodology/test_architecture_synthesis.py

Expected: PASS.

### Task 3: Persist and expose the same reasoning evidence

Files:
- Modify src/rflp_lite/methodology/architecture_reasoning.py.
- Modify src/rflp_lite/runtime/rule_based.py.
- Modify src/rflp_lite/methodology/engine.py.
- Modify tests/e2e/test_vertical_model_generation.py.
- Test tests/methodology/test_architecture_reasoning_v2.py.

Interfaces:
- Consume ArchitectureSynthesis and canonical Function payloads.
- Produce architecture_reasoning.basis.safety_isolation, candidate decision fields, logical_timing_* metrics and logical_safety_* metrics.

- [x] Step 1: Extend logical_reasoning_payload().

Add a safety_isolation sequence parameter after timing_constraints. Validate it using the existing sequence contract, copy it through the JSON compatibility helper, and add it to basis beside timing_constraints. Keep candidate alternatives sourced from item.as_dict(names), so the new counts and violation records cannot diverge from Methodology.

- [x] Step 2: Pass source safety evidence from the rule runtime.

In _logical_component_payload(), collect the group’s explicit safety_isolation values and pass them to logical_reasoning_payload(). Preserve a human-readable fallback only when no source evidence exists; do not turn that fallback into a scored safety pair.

- [x] Step 3: Add report metrics and bounded guidance.

When logical candidates exist, expose logical_timing_constraint_count, logical_timing_cut_count, logical_safety_isolation_count, logical_safety_violation_count and logical_safety_review_required. The counts must be derived from the same candidate tuple. Add these metric names to _GUIDANCE_METRICS[logical]. Keep _bounded_architecture_guidance() as the only candidate size limit.

- [x] Step 4: Add persistence assertions.

Extend the existing vertical E2E to assert that a LogicalComponent architecture_reasoning basis contains timing_constraints and safety_isolation, that alternatives contain timing_cut_count and safety_violation_count, and that the same values exist in the Workbench card after graph generation and in the graph restored by graph_to_sysml() then sysml_to_graph().

- [x] Step 5: Run focused tests.

Run: .venv/bin/python -m pytest -q tests/methodology/test_architecture_reasoning_v2.py tests/methodology/test_architecture_synthesis.py tests/e2e/test_vertical_model_generation.py

Expected: PASS.

### Task 4: Make Architecture Report and Controller consume the evidence

Files:
- Modify src/rflp_lite/application/deliverables.py only in the existing Architecture Report projection if it currently omits candidate fields.
- Modify src/rflp_lite/methodology/controller.py only if its existing logical_partition_needs_review reason needs the new metrics.
- Test tests/application/test_deliverables.py and tests/application/test_model_generation.py.

Interfaces:
- Consume MethodologyReport.metrics architecture_synthesis and the logical timing/safety metrics.
- Produce Architecture Report JSON/Markdown showing timing cuts and safety violations; keep logical_partition_needs_review mapped to bounded trade_study.

- [x] Step 1: Write report assertions.

Build a graph with one explicit safety pair, call the existing deliverable service, and assert the JSON architecture report contains candidate timing/safety fields and the same logical_safety_violation_count metric. Assert Markdown contains the human-readable safety review phrase. Do not assert or add TaskSpec, Patch or CAS details to user-facing report text.

- [x] Step 2: Reuse the existing serialized mapping.

Render fields from architecture_synthesis.logical.candidates and physical.rows; do not recompute scores in the application layer. If a Markdown row currently shows only alternative and score, append timing cuts and safety violations from that same mapping. Preserve fixed ZIP member names and ordering.

- [x] Step 3: Verify bounded Controller behavior.

Keep logical_partition_needs_review routed to trade_study. Do not add an automatic architecture-selection action. The existing user decision and re-entry stages remain authoritative.

- [x] Step 4: Run application tests.

Run: .venv/bin/python -m pytest -q tests/application/test_deliverables.py tests/application/test_model_generation.py tests/interface/web/test_model_workbench.py

Expected: PASS.

### Task 5: Document, self-review and verify

Files:
- Modify docs/DEVELOPMENT_STATUS.md.
- Modify docs/CURRENT_ARCHITECTURE.md.
- Test all focused and existing tests.

- [x] Step 1: Update product documentation.

Record that Methodology Engine v2 evaluates explicit timing coordination and safety separation in Logical alternatives, preserves unknown physical values as measurement gaps, and reuses one serialized result in guidance, Controller, Workbench, SysML and Architecture Report. State that unstructured safety text is not treated as a hard constraint.

- [x] Step 2: Run plan self-review.

Run:
rg -n "T[B]D|T[O]DO|待实现|fill in details|Similar to" docs/superpowers/specs/2026-09-14-methodology-reasoning-v2-design.md
git diff --check

Expected: no forbidden marker matches and no whitespace errors.

- [x] Step 3: Run all gates.

Run:
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests scripts
.venv/bin/ruff check src tests scripts
.venv/bin/lint-imports
.venv/bin/python scripts/architecture_metrics.py

Expected: all commands exit 0. No command may start a local model. A live remote model smoke test is optional and only runs when the explicitly configured remote host is reachable.

- [x] Step 4: Commit and push.

Run:
git add docs/superpowers/specs/2026-09-14-methodology-reasoning-v2-design.md docs/superpowers/plans/2026-09-14-methodology-reasoning-v2.md src/rflp_lite/methodology/architecture_synthesis.py src/rflp_lite/methodology/architecture_reasoning.py src/rflp_lite/runtime/rule_based.py src/rflp_lite/methodology/engine.py src/rflp_lite/methodology/controller.py src/rflp_lite/application/deliverables.py docs/DEVELOPMENT_STATUS.md docs/CURRENT_ARCHITECTURE.md tests
git commit -m "feat: deepen architecture reasoning evidence"
git push origin codex/web-audit-2026-08-18

Expected: clean worktree and remote branch updated; if the Tailscale peer remains offline, record the remote LLM test as skipped rather than using a local model.
