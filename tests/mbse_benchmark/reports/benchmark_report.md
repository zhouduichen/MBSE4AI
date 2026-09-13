# AI4MBSE Benchmark Report

## 1. Executive Summary

FINAL STATUS: **REJECTED**

Score: **41.11 / 100**

Current Capability Score: **41.11 / 100**

Full Target Capability Score: **100.0 / 100**

P0: **3 / 6 passed**

## 2. Tested System

- commit: `abf2078c533a803d45b5c0183228164ea7f5ceb2`
- branch: `codex/web-audit-2026-08-18`
- entrypoint: `build_v2_services -> ProjectService -> AnalysisService.run -> WorkflowRunner`
- runtime/provider: `RuleRuntime`
- test date: `2026-09-09T12:26:52.685177+00:00`
- configuration: `offline runtime override; isolated workspace; no external model`

## 3. Benchmark Results

| Test | Result | Score | Critical Issues |
| ---- | ------ | ----: | --------------- |
| T1 | PASS |  |  |
| T2 | PASS |  |  |
| T3 | PASS |  |  |
| T4 | FAIL |  | requirement_quality |
| T5 | PASS |  |  |
| T6 | FAIL |  | requirement_use_case_traceability |
| T7 | FAIL |  | use_case_activity_consistency |
| T8 | NOT_IMPLEMENTED |  |  |
| T9 | PASS |  |  |
| T10 | PASS |  |  |
| T11 | PASS |  |  |
| T12 | FAIL |  | verification_generation |
| T13 | FAIL |  | activity_to_test_case |
| T14 | PASS |  |  |
| T15 | FAIL |  | end_to_end_traceability |
| T16 | FAIL |  | orphan_detection |
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
| requirement_validity | 0.889 | 0.90 |
| requirement_atomicity | 0.889 | 0.85 |
| requirement_verifiability | 0.444 | 0.90 |
| upstream_traceability | 1.000 | 0.95 |
| use_case_activity_consistency | 0.000 | 0.90 |
| derived_requirement_precision | NOT_IMPLEMENTED | 0.80 |
| architecture_traceability | 1.000 | 0.90 |
| verification_coverage | 1.000 | 0.90 |
| end_to_end_traceability | 0.000 | 0.85 |
| orphan_element_rate | 0.159 | 0.05 |
| known_conflict_detection | 0.000 | 1.00 |
| unsupported_hard_assumption_rate | 0.000 | 0.05 |
| regression_stability | 0.000 | 0.85 |

## 5. P0 Failures

- FAIL: P0-01 weight conflict detected
- FAIL: P0-02 runtime conflict detected
- PASS: P0-03 upstream trace is not broadly broken
- PASS: P0-04 no false satisfied architecture
- PASS: P0-05 verification traces requirements
- FAIL: P0-06 failure feedback/iteration exists

## 6. Traceability Analysis

CASE-01: 0.0 end-to-end coverage

## 7. Requirement Quality

CASE-01: validity=0.888889, atomicity=0.888889, verifiability=0.444444

## 8. Cross-stage Consistency

CASE-01: conflict_detection=1.0

## 9. Fault Injection Result

CASE-05 was not selected.

## 10. Iteration Test

CASE-01: iteration_signal=False

## 11. Critical Problems

- [P0] CASE-01 T17: no failure feedback or targeted iteration evidence is recorded
- [P0] case-01 T15: trace breaks between upstream behavior and downstream architecture/verification
- [P1] CASE-01 T16: model elements have no trace or source
- [P1] CASE-01 T20: fewer than three runs were available
- [P1] case-01 T12: verification payload is incomplete
- [P1] case-01 T13: activity details are not converted to verification scenarios
- [P1] case-01 T4: requirement fields are vague, compound, unverifiable, or unproven
- [P1] case-01 T6: requirements have no Use Case link
- [P1] case-01 T7: use cases or activities do not link to requirements

## 12. Recommended Fix Order

| Priority | Problem | Reason | Affected Module | Suggested Fix | Expected Benefit |
| -------- | ------- | ------ | --------------- | ------------- | --------------- |
| P0 | iteration | no failure feedback or targeted iteration evidence is recorded | current workflow | Persist failure-to-requirement impact and rerun the smallest affected stage. | restores measurable MBSE coverage |
| P0 | end_to_end_traceability | trace breaks between upstream behavior and downstream architecture/verification | current workflow | Repair the earliest broken relation and rerun downstream phases. | restores measurable MBSE coverage |
| P1 | orphan_detection | model elements have no trace or source | current workflow | Require every generated node to carry a source relation or lifecycle rationale. | restores measurable MBSE coverage |
| P1 | regression | fewer than three runs were available | current workflow | Run the case three times in isolated workspaces. | restores measurable MBSE coverage |
| P1 | verification_generation | verification payload is incomplete | current workflow | Emit method, precondition, input, procedure, expected result, and pass/fail criterion. | restores measurable MBSE coverage |
| P1 | activity_to_test_case | activity details are not converted to verification scenarios | current workflow | Generate normal, failure, boundary, and exception verification scenarios from Activity branches. | restores measurable MBSE coverage |
| P1 | requirement_quality | requirement fields are vague, compound, unverifiable, or unproven | current workflow | Normalize atomic shall-statements with source and verification criteria. | restores measurable MBSE coverage |
| P1 | requirement_use_case_traceability | requirements have no Use Case link | current workflow | Populate explicit Requirement ↔ Use Case relations. | restores measurable MBSE coverage |
| P1 | use_case_activity_consistency | use cases or activities do not link to requirements | current workflow | Populate explicit Use Case ↔ Activity relations and branch payloads. | restores measurable MBSE coverage |

## 13. Final Acceptance Decision

**REJECTED**
