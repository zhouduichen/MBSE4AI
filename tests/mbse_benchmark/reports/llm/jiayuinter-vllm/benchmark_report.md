# AI4MBSE Benchmark Report

## 1. Executive Summary

Track: **llm**

Track status: **EXPLICIT**

FINAL STATUS: **REJECTED**

Score: **90.0 / 100**

Current Capability Score: **90.0 / 100**

Full Target Capability Score: **100.0 / 100**

P0: **4 / 6 passed**

## 2. Tested System

- commit: `fa4d023dff6c69d2b4d2c68ace232f0ce111367b`
- branch: `codex/web-audit-2026-08-18`
- entrypoint: `build_v2_services -> ProjectService -> ModelGenerationService.generate -> five-stage vertical path`
- runtime/provider: `configured-llm`
- profile/provider/model: `jiayuinter-vllm` / `openai-compatible` / `qwen3.5-controller`
- methodology version: `v2.1`
- prompt hash: `a76a988bfaf4c43899ad27b3b7303160aeeb156994d08a86c78b1bf3cf411686`
- task spec hash: `21a7bd79ed630c767d67beb22668364a5791c54ec7869c907334cd56345f5a59`
- case/repeat: `CASE-04` / `1`
- test date: `2026-09-20T04:48:30.967104+00:00`
- configuration: `explicit LLM profile; isolated workspace; provider credentials are not written to reports`

## 3. Benchmark Results

| Test | Result | Score | Critical Issues |
| ---- | ------ | ----: | --------------- |
| T1 | PASS |  |  |
| T2 | PASS |  |  |
| T3 | PASS |  |  |
| T4 | PASS |  |  |
| T5 | PASS |  |  |
| T6 | PASS |  |  |
| T7 | PASS |  |  |
| T8 | PASS |  |  |
| T9 | PASS |  |  |
| T10 | PASS |  |  |
| T11 | PASS |  |  |
| T12 | PASS |  |  |
| T13 | PASS |  |  |
| T14 | PASS |  |  |
| T15 | PASS |  |  |
| T16 | PASS |  |  |
| T17 | PASS |  |  |
| T18 | PASS |  |  |
| T19 | PASS |  |  |
| T20 | BLOCKED |  | regression |

## 4. Metrics

| Metric | Observed | Target |
| ------ | -------: | -----: |
| stakeholder_coverage | 1.000 | 0.85 |
| lifecycle_coverage | 1.000 | 0.90 |
| scenario_recall | 1.000 | 0.85 |
| requirement_validity | 1.000 | 0.90 |
| requirement_atomicity | 1.000 | 0.85 |
| requirement_verifiability | 1.000 | 0.90 |
| upstream_traceability | 1.000 | 0.95 |
| use_case_activity_consistency | 1.000 | 0.90 |
| derived_requirement_precision | 1.000 | 0.80 |
| architecture_traceability | 1.000 | 0.90 |
| verification_coverage | 1.000 | 0.90 |
| end_to_end_traceability | 1.000 | 0.85 |
| orphan_element_rate | 0.000 | 0.05 |
| known_conflict_detection | 0.000 | 1.00 |
| unsupported_hard_assumption_rate | 0.000 | 0.05 |
| regression_stability | 0.000 | 0.85 |

## 5. P0 Failures

- FAIL: P0-01 weight conflict detected
- FAIL: P0-02 runtime conflict detected
- PASS: P0-03 upstream trace is not broadly broken
- PASS: P0-04 no false satisfied architecture
- PASS: P0-05 verification traces requirements
- PASS: P0-06 failure feedback/iteration exists

## 6. Traceability Analysis

CASE-04: 1.0 end-to-end coverage

## 7. Requirement Quality

CASE-04: validity=1.0, atomicity=1.0, verifiability=1.0

## 8. Cross-stage Consistency

CASE-04: conflict_detection=1.0

## 9. Fault Injection Result

CASE-05 was not selected.

## 10. Iteration Test

CASE-04: iteration_signal=True

## 11. Critical Problems

- [P1] CASE-04 T20: fewer than three runs were available

## 12. Recommended Fix Order

| Priority | Problem | Reason | Affected Module | Suggested Fix | Expected Benefit |
| -------- | ------- | ------ | --------------- | ------------- | --------------- |
| P1 | regression | fewer than three runs were available | current workflow | Run the case three times in isolated workspaces. | restores measurable MBSE coverage |

## 13. Final Acceptance Decision

**REJECTED**


## 14. Track-specific Metrics

| Metric | Observed |
| ------ | -------: |
| pipeline_completion | 0.0 |
| revision_determinism | 1.0 |
| graph_hash_determinism | 1.0 |
| rflp_trace_coverage | 1.0 |
| gate_detection | 0.0 |
| repair_recovery | 0.0 |
| cas_lock_protection | 1.0 |
| closure_manifest | 0.0 |
| audit_completeness | 1.0 |
| repeat_minimum | 1 |

## 15. Bare LLM Baseline

This baseline uses the same input and configured model without methodology workflow, gates, or repair.

| Metric | Observed |
| ------ | -------: |
| requirement_precision | 0.0 |
| requirement_recall | 0.0 |
| requirement_atomicity | 0.0 |
| requirement_verifiability | 0.0 |
| unsupported_numeric_claim_rate | 0.0 |
| trace_accuracy | 0.0 |
| RFLP_coverage | 0.0 |
| evidence_faithfulness | 0.0 |
| verification_quality | 0.0 |
| hallucinated_entity_rate | 0.0 |