# AI4MBSE Benchmark Report

## 1. Executive Summary

Track: **llm**

Track status: **EXPLICIT**

FINAL STATUS: **ACCEPTED**

Score: **100.0 / 100**

Current Capability Score: **100.0 / 100**

Full Target Capability Score: **100.0 / 100**

P0: **6 / 6 passed**

## 2. Tested System

- commit: `1eca30e5db04d220a24e7990da48eb9d1609afae`
- branch: `codex/web-audit-2026-08-18`
- entrypoint: `build_v2_services -> ProjectService -> ModelGenerationService.generate -> five-stage vertical path`
- runtime/provider: `configured-llm`
- profile/provider/model: `jiayuinter-vllm-fast` / `openai-compatible` / `qwen3.5-controller`
- methodology version: `v2.1`
- prompt hash: `a76a988bfaf4c43899ad27b3b7303160aeeb156994d08a86c78b1bf3cf411686`
- task spec hash: `21a7bd79ed630c767d67beb22668364a5791c54ec7869c907334cd56345f5a59`
- case/repeat: `CASE-05` / `1`
- test date: `2026-09-21T01:22:22.238743+00:00`
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
| known_conflict_detection | 1.000 | 1.00 |
| unsupported_hard_assumption_rate | 0.000 | 0.05 |
| regression_stability | 0.000 | 0.85 |

## 5. P0 Failures

None

## 6. Traceability Analysis

CASE-05: 1.0 end-to-end coverage

## 7. Requirement Quality

CASE-05: validity=1.0, atomicity=1.0, verifiability=1.0

## 8. Cross-stage Consistency

CASE-05: conflict_detection=1.0

## 9. Fault Injection Result

{'expected_conflicts': [{'conflict_id': 'weight-conflict', 'actual_value': 32.0, 'limit': 20, 'unit': 'kg'}, {'conflict_id': 'runtime-conflict', 'actual_value': 5.0, 'limit': 12, 'unit': 'h'}], 'conflict_signals': [{'conflict_id': 'weight-conflict', 'actual_value': 32.0, 'limit': 20, 'unit': 'kg', 'detected': True}, {'conflict_id': 'runtime-conflict', 'actual_value': 5.0, 'limit': 12, 'unit': 'h', 'detected': True}], 'known_conflict_detection': 1.0, 'false_satisfaction_signal': False, 'iteration_signal': True, 'change_impact_terms': {'scenario': True, 'function': True, 'battery': True, 'power': True, 'physical': True, 'verification': True}, 'findings': [{'test_id': 'T10', 'case_id': 'CASE-05', 'status': 'PASS', 'severity': 'P0', 'category': 'architecture_requirement_conflict', 'expected': 'detect CASE-05 weight and runtime conflicts', 'actual': [{'conflict_id': 'weight-conflict', 'actual_value': 32.0, 'limit': 20, 'unit': 'kg', 'detected': True}, {'conflict_id': 'runtime-conflict', 'actual_value': 5.0, 'limit': 12, 'unit': 'h', 'detected': True}], 'related_elements': ['REQ-WEIGHT', 'REQ-RUNTIME', 'PHY-BATTERY', 'PHY-CHASSIS', 'PHY-MOTOR', 'PHY-SENSOR', 'PHY-COMPUTE'], 'root_cause': '', 'recommended_fix': 'Add generic mass/energy/power feasibility checks to Assurance and prevent SATISFIED claims.'}, {'test_id': 'T17', 'case_id': 'CASE-05', 'status': 'PASS', 'severity': 'P0', 'category': 'iteration', 'expected': 'verification failure leads to diagnosis, modification, and re-verification', 'actual': True, 'related_elements': [], 'root_cause': '', 'recommended_fix': 'Persist failure-to-requirement impact and rerun the smallest affected stage.'}, {'test_id': 'T18', 'case_id': 'CASE-05', 'status': 'PASS', 'severity': 'P1', 'category': 'change_impact', 'expected': 'requirement change identifies affected design and verification elements', 'actual': {'scenario': True, 'function': True, 'battery': True, 'power': True, 'physical': True, 'verification': True}, 'related_elements': [], 'root_cause': '', 'recommended_fix': 'Add versioned impact traversal from requirement to scenario, function, power/physical design, and verification.'}, {'test_id': 'T9', 'case_id': 'CASE-05', 'status': 'PASS', 'severity': 'P0', 'category': 'false_satisfied_architecture', 'expected': 'violated physical architecture must not be reported SATISFIED', 'actual': False, 'related_elements': [], 'root_cause': '', 'recommended_fix': 'Gate closure on numeric feasibility findings.'}]}

## 10. Iteration Test

CASE-05: iteration_signal=True

## 11. Critical Problems

- [P1] CASE-05 T20: fewer than three runs were available

## 12. Recommended Fix Order

| Priority | Problem | Reason | Affected Module | Suggested Fix | Expected Benefit |
| -------- | ------- | ------ | --------------- | ------------- | --------------- |
| P1 | regression | fewer than three runs were available | current workflow | Run the case three times in isolated workspaces. | restores measurable MBSE coverage |

## 13. Final Acceptance Decision

**ACCEPTED**


## 14. Track-specific Metrics

| Metric | Observed |
| ------ | -------: |
| pipeline_completion | 0.0 |
| revision_determinism | 1.0 |
| graph_hash_determinism | 1.0 |
| rflp_trace_coverage | 1.0 |
| gate_detection | 1.0 |
| repair_recovery | 1.0 |
| cas_lock_protection | 1.0 |
| closure_manifest | 0.0 |
| audit_completeness | 1.0 |
| repeat_minimum | 1 |