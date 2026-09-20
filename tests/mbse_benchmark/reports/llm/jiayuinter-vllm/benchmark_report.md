# AI4MBSE Benchmark Report

## 1. Executive Summary

Track: **llm**

Track status: **EXPLICIT**

FINAL STATUS: **REJECTED**

Score: **45.0 / 100**

Current Capability Score: **45.0 / 100**

Full Target Capability Score: **100.0 / 100**

P0: **2 / 6 passed**

## 2. Tested System

- commit: `02d87baaea8a46685d8846b0964d7bdfa1a7f6f3`
- branch: `codex/web-audit-2026-08-18`
- entrypoint: `build_v2_services -> ProjectService -> ModelGenerationService.generate -> five-stage vertical path`
- runtime/provider: `configured-llm`
- profile/provider/model: `jiayuinter-vllm` / `openai-compatible` / `qwen3.5-controller`
- methodology version: `v2.1`
- prompt hash: `a76a988bfaf4c43899ad27b3b7303160aeeb156994d08a86c78b1bf3cf411686`
- task spec hash: `21a7bd79ed630c767d67beb22668364a5791c54ec7869c907334cd56345f5a59`
- case/repeat: `CASE-04` / `1`
- test date: `2026-09-20T11:13:19.513884+00:00`
- configuration: `explicit LLM profile; isolated workspace; provider credentials are not written to reports`

## 3. Benchmark Results

| Test | Result | Score | Critical Issues |
| ---- | ------ | ----: | --------------- |
| T1 | PASS |  |  |
| T2 | PASS |  |  |
| T3 | PASS |  |  |
| T4 | PASS |  |  |
| T5 | PASS |  |  |
| T6 | FAIL |  | requirement_use_case_traceability |
| T7 | FAIL |  | use_case_activity_consistency |
| T8 | PASS |  |  |
| T9 | PASS |  |  |
| T10 | PASS |  |  |
| T11 | NOT_IMPLEMENTED |  |  |
| T12 | PASS |  |  |
| T13 | FAIL |  | activity_to_test_case |
| T14 | FAIL |  | verification_coverage |
| T15 | FAIL |  | end_to_end_traceability |
| T16 | PASS |  |  |
| T17 | FAIL |  | iteration |
| T18 | NOT_IMPLEMENTED |  |  |
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
| use_case_activity_consistency | 0.000 | 0.90 |
| derived_requirement_precision | 1.000 | 0.80 |
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
- PASS: P0-03 upstream trace is not broadly broken
- PASS: P0-04 no false satisfied architecture
- FAIL: P0-05 verification traces requirements
- FAIL: P0-06 failure feedback/iteration exists

## 6. Traceability Analysis

CASE-04: 0.0 end-to-end coverage

## 7. Requirement Quality

CASE-04: validity=1.0, atomicity=1.0, verifiability=1.0

## 8. Cross-stage Consistency

CASE-04: conflict_detection=1.0

## 9. Fault Injection Result

CASE-05 was not selected.

## 10. Iteration Test

CASE-04: iteration_signal=False

## 11. Critical Problems

- [P0] CASE-04 T17: no failure feedback or targeted iteration evidence is recorded
- [P0] case-04 T14: verification cases are absent, orphaned, or not linked to requirements
- [P0] case-04 T15: trace breaks between upstream behavior and downstream architecture/verification
- [P1] CASE-04 T20: fewer than three runs were available
- [P1] case-04 T13: activity details are not converted to verification scenarios
- [P1] case-04 T6: requirements have no Use Case link
- [P1] case-04 T7: use cases or activities do not link to requirements

## 12. Recommended Fix Order

| Priority | Problem | Reason | Affected Module | Suggested Fix | Expected Benefit |
| -------- | ------- | ------ | --------------- | ------------- | --------------- |
| P0 | iteration | no failure feedback or targeted iteration evidence is recorded | current workflow | Persist failure-to-requirement impact and rerun the smallest affected stage. | restores measurable MBSE coverage |
| P0 | verification_coverage | verification cases are absent, orphaned, or not linked to requirements | current workflow | Link every verification case to a requirement and retain its pass/fail criterion. | restores measurable MBSE coverage |
| P0 | end_to_end_traceability | trace breaks between upstream behavior and downstream architecture/verification | current workflow | Repair the earliest broken relation and rerun downstream phases. | restores measurable MBSE coverage |
| P1 | regression | fewer than three runs were available | current workflow | Run the case three times in isolated workspaces. | restores measurable MBSE coverage |
| P1 | activity_to_test_case | activity details are not converted to verification scenarios | current workflow | Generate normal, failure, boundary, and exception verification scenarios from Activity branches. | restores measurable MBSE coverage |
| P1 | requirement_use_case_traceability | requirements have no Use Case link | current workflow | Populate explicit Requirement ↔ Use Case relations. | restores measurable MBSE coverage |
| P1 | use_case_activity_consistency | use cases or activities do not link to requirements | current workflow | Populate explicit Use Case ↔ Activity relations and branch payloads. | restores measurable MBSE coverage |

## 13. Final Acceptance Decision

**REJECTED**


## 14. Track-specific Metrics

| Metric | Observed |
| ------ | -------: |
| pipeline_completion | 0.0 |
| revision_determinism | 1.0 |
| graph_hash_determinism | 1.0 |
| rflp_trace_coverage | 0.0 |
| gate_detection | 0.0 |
| repair_recovery | 0.0 |
| cas_lock_protection | 0.0 |
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