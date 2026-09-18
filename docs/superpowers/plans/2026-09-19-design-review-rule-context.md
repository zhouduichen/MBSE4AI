# DFM/DFA 规则上下文与风险摘要实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic design review explain which manufacturing rule set and assembly context produced each finding.

**Architecture:** Keep `DesignRulePort` unchanged. `DesignReviewService` merges `model_payload.design_review_context` with annotation context, and `PreviewDesignRuleAdapter` resolves a bounded rule profile, validates assembly interfaces, and returns a finding summary/evidence hash alongside the existing risk SVG.

**Tech Stack:** Python 3.12, immutable `DesignFinding`, canonical hashing, existing detail-design store and pytest.

## Global Constraints

- No model, server, SSH or FreeCAD execution.
- Unknown rule sets and malformed assembly declarations become review findings, not silent defaults.
- Findings remain development evidence and require human review.
- Existing adapter method signatures and CAD operation contracts remain compatible.

---

### Task 1: Define bounded rule profiles and context resolution

**Files:**
- Modify: `src/rflp_lite/adapters/design_rules_preview.py`
- Test: `tests/adapters/test_design_rules_preview.py`

- [x] Add profile constants for `generic_preview`, `cnc_machined` and `additive_preview` with explicit wall/fillet/hole-edge thresholds.
- [x] Resolve `rule_set` from context or model payload; emit `ruleset.unknown` for unsupported values.
- [x] Include the resolved profile in every rule evidence payload.

### Task 2: Check assembly interfaces and summarize findings

**Files:**
- Modify: `src/rflp_lite/adapters/design_rules_preview.py`
- Modify: `src/rflp_lite/application/design_review_service.py`
- Test: `tests/application/test_cad_workflow.py`

- [x] Validate required `{part_id, feature_id, interface}` records against model parts/features.
- [x] Emit `dfa.assembly_interface` with stable evidence when an interface is missing or malformed.
- [x] Add `finding_summary` counts by severity/category and a canonical `evidence_hash` to review artifacts.

### Task 3: Verify UI/deliverable propagation

**Files:**
- Modify: `tests/e2e/test_local_product_acceptance.py`
- Modify: `README.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`

- [x] Assert rule context and summaries survive PhysicalBlock review write-back and detail-design delivery.
- [ ] Run focused tests, `git diff --check`, full offline `scripts/verify_full.py`, Ruff, architecture metrics and import-linter.
- [ ] Commit and push the slice.
