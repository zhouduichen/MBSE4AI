# AI4MBSE Benchmark Report

## 1. Executive Summary

Track: **llm**

Track status: **EXPLICIT**

FINAL STATUS: **REJECTED**

Score: **0.0 / 100**

Current Capability Score: **0.0 / 100**

Full Target Capability Score: **100.0 / 100**

P0: **1 / 6 passed**

## 2. Tested System

- commit: `1eca30e5db04d220a24e7990da48eb9d1609afae`
- branch: `codex/web-audit-2026-08-18`
- entrypoint: `build_v2_services -> ProjectService -> ModelGenerationService.generate -> five-stage vertical path`
- runtime/provider: `configured-llm`
- profile/provider/model: `jiayuinter-vllm` / `openai-compatible` / `qwen3.5-controller`
- methodology version: `v2.1`
- prompt hash: ``
- task spec hash: ``
- case/repeat: `CASE-05` / `1`
- test date: `2026-09-21T00:27:13.303060+00:00`
- configuration: `explicit LLM profile; isolated workspace; provider credentials are not written to reports`

## 3. Benchmark Results

| Test | Result | Score | Critical Issues |
| ---- | ------ | ----: | --------------- |
| T1 | NOT_IMPLEMENTED |  |  |
| T2 | NOT_IMPLEMENTED |  |  |
| T3 | NOT_IMPLEMENTED |  |  |
| T4 | NOT_IMPLEMENTED |  |  |
| T5 | NOT_IMPLEMENTED |  |  |
| T6 | NOT_IMPLEMENTED |  |  |
| T7 | NOT_IMPLEMENTED |  |  |
| T8 | NOT_IMPLEMENTED |  |  |
| T9 | NOT_IMPLEMENTED |  |  |
| T10 | NOT_IMPLEMENTED |  |  |
| T11 | NOT_IMPLEMENTED |  |  |
| T12 | NOT_IMPLEMENTED |  |  |
| T13 | NOT_IMPLEMENTED |  |  |
| T14 | NOT_IMPLEMENTED |  |  |
| T15 | NOT_IMPLEMENTED |  |  |
| T16 | NOT_IMPLEMENTED |  |  |
| T17 | NOT_IMPLEMENTED |  |  |
| T18 | NOT_IMPLEMENTED |  |  |
| T19 | NOT_IMPLEMENTED |  |  |
| T20 | NOT_IMPLEMENTED |  |  |

## 4. Metrics

| Metric | Observed | Target |
| ------ | -------: | -----: |
| stakeholder_coverage | 0.000 | 0.85 |
| lifecycle_coverage | 0.000 | 0.90 |
| scenario_recall | 0.000 | 0.85 |
| requirement_validity | 0.000 | 0.90 |
| requirement_atomicity | 0.000 | 0.85 |
| requirement_verifiability | 0.000 | 0.90 |
| upstream_traceability | 0.000 | 0.95 |
| use_case_activity_consistency | 0.000 | 0.90 |
| derived_requirement_precision | NOT_IMPLEMENTED | 0.80 |
| architecture_traceability | 0.000 | 0.90 |
| verification_coverage | 0.000 | 0.90 |
| end_to_end_traceability | 0.000 | 0.85 |
| orphan_element_rate | 0.000 | 0.05 |
| known_conflict_detection | 0.000 | 1.00 |
| unsupported_hard_assumption_rate | 0.000 | 0.05 |
| regression_stability | 0.000 | 0.85 |

## 5. P0 Failures

- FAIL: P0-01 weight conflict detected
- FAIL: P0-02 runtime conflict detected
- FAIL: P0-03 upstream trace is not broadly broken
- PASS: P0-04 no false satisfied architecture
- FAIL: P0-05 verification traces requirements
- FAIL: P0-06 failure feedback/iteration exists

## 6. Traceability Analysis

CASE-05: 0 end-to-end coverage

## 7. Requirement Quality

CASE-05: validity=0, atomicity=0, verifiability=0

## 8. Cross-stage Consistency

CASE-05: conflict_detection=0

## 9. Fault Injection Result

{}

## 10. Iteration Test

CASE-05: iteration_signal=False

## 11. Critical Problems

- [P0] CASE-05 EXECUTION: execution exceeded bounded timeout

## 12. Recommended Fix Order

| Priority | Problem | Reason | Affected Module | Suggested Fix | Expected Benefit |
| -------- | ------- | ------ | --------------- | ------------- | --------------- |
| P0 | execution | execution exceeded bounded timeout | current workflow | Fix the execution/runtime blocker before evaluating semantic quality. | restores measurable MBSE coverage |

## 13. Final Acceptance Decision

**REJECTED**


## 14. Track-specific Metrics

| Metric | Observed |
| ------ | -------: |
| pipeline_completion | 0.0 |
| revision_determinism | 0.0 |
| graph_hash_determinism | 0.0 |
| rflp_trace_coverage | 0.0 |
| gate_detection | 0.0 |
| repair_recovery | 0.0 |
| cas_lock_protection | 0.0 |
| closure_manifest | 0.0 |
| audit_completeness | 0.0 |
| repeat_minimum | 1 |