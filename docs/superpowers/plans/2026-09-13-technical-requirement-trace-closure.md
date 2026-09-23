# Physical Technical Requirement and Trace Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for implementation tasks when available.

**Goal:** 让输入中明确出现的工程约束在 Physical 阶段形成可审查、可验证、可导出的 Technical Requirement，并保持 R→F→L→P→V&V 的追溯口径一致。

**Architecture:** 复用既有 `EntityKind.REQUIREMENT`，以 `payload.level=technical` 区分技术需求。RuleRuntime 在生成 Physical Block 后，为显式 `max_*`/`min_*` 约束创建技术需求，并通过 `DERIVED_FROM` 连接来源需求、通过 `SATISFIED_BY` 连接物理候选。技术需求复用来源需求的 F→L→P 路径，同时拥有独立 V&V。

**Tech Stack:** Python 3.11+, typed ModelGraph, existing RuleRuntime, methodology engine, SysML v2 exporter/importer, FastAPI delivery APIs.

## Task 1: Add shared technical-requirement lineage and trace projection rules

**Files:**
- Modify: `src/rflp_lite/methodology/trace_rules.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Modify: `src/rflp_lite/application/projections/common.py`
- Test: `tests/methodology/test_trace_rules.py`
- Test: `tests/application/test_model_generation.py`
- Test: `tests/application/projections/test_traceability_projection.py`

- [x] Add `requirement_lineage(graph, requirement_id) -> tuple[str, ...]`, following only requirement-to-requirement `DERIVED_FROM` edges to stable root requirements.
- [x] Make application trace summaries resolve F/L/P targets from the root source requirement and append a technical requirement's direct Physical Block target without duplicating IDs.
- [x] Make the traceability projection use the same lineage rule, so summary rows, coverage states, and graph views agree.
- [x] Add focused tests for direct lineage, nested lineage, technical direct physical targets, and unchanged ordinary requirements.

## Task 2: Generate Technical Requirements from explicit Physical constraints

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py`
- Test: `tests/runtime/test_vertical_rule_runtime.py`
- Test: `tests/e2e/test_vertical_model_generation.py`

- [x] Add a small extractor for canonical explicit constraints found at the requirement top level or under `constraints`/`limits`; recognize only `max_*` and `min_*` keys.
- [x] After each Physical Block is created or selected, create one deterministic technical requirement per source requirement and physical candidate when the extractor returns constraints.
- [x] Populate provenance, source IDs, constraint fields, verification method, and open question metadata without fabricating a measurement or feasibility result.
- [x] Add `DERIVED_FROM` and `SATISFIED_BY` relations, and prove idempotency on repeated stage execution.
- [x] Cover both the normal physical candidate and an alternative candidate created by an architecture decision.

## Task 3: Align methodology and V&V semantics

**Files:**
- Modify: `src/rflp_lite/methodology/engine.py`
- Test: `tests/methodology/test_engine.py`
- Test: `tests/e2e/test_vertical_model_generation.py`
- Test: `tests/interface/web/test_vertical_generation_api.py`

- [x] Exclude `level=technical` requirements from Functional analysis so they do not produce false `functional_requirement_uncovered` findings.
- [x] Keep technical requirements in V&V analysis so each receives independent VerificationCase/ValidationCase coverage.
- [x] Verify constrained natural-language generation remains complete at the structural level while reporting measurement/open-question work honestly.

## Task 4: Preserve SysML, deliverables, documentation, and full-chain acceptance

**Files:**
- Test: `tests/application/test_sysml_v2.py`
- Test: `tests/interface/web/test_deliverables_api.py`
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`

- [x] Prove technical requirement payloads and both lineage relations survive SysML v2 export/import.
- [x] Prove model, RFLP, traceability, and V&V deliverables expose the generated technical requirement.
- [x] Document the explicit-constraint rule, its trace semantics, and the remaining measurement/feasibility boundary.
- [x] Run the complete verification suite: pytest, `scripts/verify_full.py`, compileall, ruff, import-linter, architecture metrics, and `git diff --check`.
- [x] Commit implementation/tests/docs in logical commits, push the branch to GitHub, and verify local HEAD equals its upstream HEAD.

## Verification commands

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```
