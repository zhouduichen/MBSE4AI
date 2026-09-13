# Methodology Engine v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Methodology Engine that turns the current ModelGraph into logical, physical, V&V, and impact-analysis evidence used by generation and review flows.

**Architecture:** Keep ModelGraph as the semantic IR and add a pure analyzer under `rflp_lite.methodology.engine`; it never writes the repository or calls an LLM. Application services will invoke it after generation and during reanalysis requests, while Web only renders the report already produced by those services.

**Tech Stack:** Python 3.11+, dataclasses, `ModelGraph`, SQLite audit ledger, FastAPI/Jinja, pytest, Ruff, import-linter.

## Global Constraints

- 五阶段 UX 顺序固定为 Requirements → Functional → Logical → Physical → Verification & Validation。
- 23-task catalog 保留，并作为五阶段的内部 reasoning task 映射，不删除旧 pipeline 入口。
- ModelGraph 是唯一内部语义真源；SysML v2 只是 interchange/export format。
- 物理未知值必须进入 `needs_measurement`，不得计为 feasible。
- Verification 和 Validation 必须分别统计；二者同时存在才是端到端闭环。
- 影响分析最多遍历 4 跳，不增加外部依赖。

---

### Task 1: Build the pure Methodology Engine contract and analysis rules

**Files:**
- Create: `src/rflp_lite/methodology/engine.py`
- Test: `tests/methodology/test_engine.py`

**Interfaces:**
- Consumes: `ModelGraph`, `EntityKind`, `EntityStatus`, `RelationPredicate`.
- Produces: `MethodologyFinding`, `MethodologyReport`, and `MethodologyEngine.analyze(graph, changed_entity_ids=())`.

- [x] **Step 1: Write failing graph-analysis tests**

Create graphs covering: a valid Function → LogicalComponent → PhysicalBlock chain; an unallocated Function; a PhysicalBlock with `max_power_w` requirement conflict; a PhysicalBlock with unknown `power_w`; incomplete Verification/Validation payloads; and a changed Requirement with downstream relations. Assert stable finding codes, metrics, impact IDs, impacted stages, and recommended task IDs.

- [x] **Step 2: Run the focused tests and verify failure**

Run `./.venv/bin/python -m pytest tests/methodology/test_engine.py -q`. It must fail because `rflp_lite.methodology.engine` does not yet exist.

- [x] **Step 3: Implement immutable report types and deterministic analyzers**

Implement these signatures:

```python
@dataclass(frozen=True, slots=True)
class MethodologyFinding:
    code: str
    severity: str
    stage: str
    entity_ids: tuple[str, ...] = ()
    message: str = ""
    recommended_actions: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class MethodologyReport:
    findings: tuple[MethodologyFinding, ...] = ()
    metrics: Mapping[str, object] = field(default_factory=dict)
    decisions: tuple[Mapping[str, object], ...] = ()
    impacted_entity_ids: tuple[str, ...] = ()
    impacted_stages: tuple[str, ...] = ()
    recommended_tasks: tuple[str, ...] = ()
    impact_paths: tuple[tuple[str, ...], ...] = ()

class MethodologyEngine:
    def analyze(
        self,
        graph: ModelGraph,
        *,
        changed_entity_ids: Sequence[str] = (),
    ) -> MethodologyReport: ...
```

The logical analyzer shall calculate allocation coverage, orphan functions/components, interface crossings, and partition candidates from allocation and payload dependency signals. The physical analyzer shall normalize numeric limits from `payload["constraints"]`, `payload["limits"]`, and `max_*`/`min_*` fields, compare them with physical values, and emit `physical_constraint_conflict` or `physical_measurement_required`. The V&V analyzer shall separately count verification and validation coverage and check `method`, `precondition`, `input`, `procedure`, `expected_result`, `pass_criteria`, and `evidence_ids`. Impact traversal shall walk both relation directions with a four-hop bound and map reached kinds to concrete 23-task IDs.

- [x] **Step 4: Run focused tests and lint**

Run `./.venv/bin/python -m pytest tests/methodology/test_engine.py -q` and `./.venv/bin/ruff check src/rflp_lite/methodology/engine.py tests/methodology/test_engine.py`. Expected: PASS.

- [x] **Step 5: Commit the pure engine**

```bash
git add src/rflp_lite/methodology/engine.py tests/methodology/test_engine.py
git commit -m "feat: add deterministic methodology engine"
```

### Task 2: Connect generation and Review reanalysis to the engine

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py`
- Modify: `src/rflp_lite/application/review_service.py`
- Test: `tests/application/test_model_generation.py`
- Test: `tests/interface/web/test_review_actions.py`

**Interfaces:**
- Consumes: `MethodologyEngine.analyze` and `MethodologyReport.as_dict()`.
- Produces: `GenerateModelResult.methodology` and reanalysis payload fields `impact`, `impacted_stages`, `recommended_tasks`, and `impact_paths`.

- [x] **Step 1: Write failing integration assertions**

Assert a generated result exposes `methodology.metrics`, contains physical measurement findings for the offline candidate, and records `model_generation.methodology_analyzed`. Assert a reanalysis request for an edited Requirement contains the affected Function/Logical/Physical IDs and a non-empty recommended task list derived from the graph.

- [x] **Step 2: Run the focused tests and verify failure**

Run `./.venv/bin/python -m pytest tests/application/test_model_generation.py tests/interface/web/test_review_actions.py -q`. Expected: FAIL because generation and reanalysis currently return no methodology report or graph-derived impact.

- [x] **Step 3: Integrate without moving persistence into the engine**

Instantiate an injectable `MethodologyEngine` in `ModelGenerationService`. After the five stages, call `analyze(final_graph)`, add the report to `GenerateModelResult.as_dict()`, append actionable findings to warnings, and record the complete report in `model_generation.methodology_analyzed`. In `ReviewService.request_reanalysis`, call the same engine with the edited entity ID, use `report.recommended_tasks` with the existing static mapping only as a fallback, and persist the report fields in `review.reanalysis.requested`.

- [x] **Step 4: Run integration tests and lint**

Run `./.venv/bin/python -m pytest tests/application/test_model_generation.py tests/interface/web/test_review_actions.py -q` and `./.venv/bin/ruff check src/rflp_lite/application/model_generation.py src/rflp_lite/application/review_service.py tests/application/test_model_generation.py tests/interface/web/test_review_actions.py`. Expected: PASS.

- [x] **Step 5: Commit the application integration**

```bash
git add src/rflp_lite/application/model_generation.py src/rflp_lite/application/review_service.py tests/application/test_model_generation.py tests/interface/web/test_review_actions.py
git commit -m "feat: connect methodology analysis to generation and review"
```

### Task 3: Expose Methodology Findings and impact in the workbench

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_pages.py`
- Modify: `src/rflp_lite/interface/web/templates/analysis.html`
- Test: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: generation audit event `model_generation.methodology_analyzed` and `GenerateModelResult.methodology`.
- Produces: `latest_run.methodology` with findings, metrics, and next tasks visible on the analysis page.

- [x] **Step 1: Write failing API/page assertions**

Assert the generation JSON has `methodology.findings` and `methodology.metrics`; assert the analysis page contains “Methodology Findings”, “Physical feasibility”, “V&V Coverage”, and “Next Tasks”.

- [x] **Step 2: Implement one report decoration path**

Extend `_decorate_generation_run` to read the methodology audit event for the current `run_id`. Render only bounded finding codes/messages, key metric values, and task IDs; keep entity details linked through existing resource routes. Do not recompute analysis in Jinja or Web route code.

- [x] **Step 3: Run interface tests**

Run `./.venv/bin/python -m pytest tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_review_actions.py -q`. Expected: PASS.

- [x] **Step 4: Commit the workbench presentation**

```bash
git add src/rflp_lite/interface/web/resource_pages.py src/rflp_lite/interface/web/templates/analysis.html tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: show methodology findings in workbench"
```

### Task 4: Full product-path verification and documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: the engine, generation report, Review impact payload, and current ModelGraph export path.
- Produces: documented Methodology Engine behavior and a regression proving one offline run creates both a complete RFLP/V&V graph and non-empty engineering analysis.

- [x] **Step 1: Add the end-to-end acceptance test**

Run the offline generator, assert `methodology.metrics` includes logical allocation and separate verification/validation coverage, assert unknown physical values are not feasible, and assert SysML export remains readable.

- [x] **Step 2: Update product documentation**

Document Methodology Findings, impact analysis, and the distinction between graph truth and SysML interchange format in the three listed files.

- [x] **Step 3: Run the complete verification matrix**

```bash
./.venv/bin/python scripts/verify_full.py
git diff --check
git status --short --branch
```

Expected: all tests pass; architecture metrics remain within `architecture_budget.json`; Ruff and import-linter pass; the branch has only intended changes.

- [x] **Step 4: Commit and push the product-path slice**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md tests/e2e/test_vertical_model_generation.py
git commit -m "docs: document methodology engine product path"
git push origin HEAD
```

### Task 5: Execute targeted reanalysis from Review

**Files:**
- Modify: `src/rflp_lite/application/model_generation.py`
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/templates/requirement-detail.html`
- Test: `tests/application/test_model_generation.py`
- Test: `tests/interface/web/test_review_actions.py`

**Result:** Completed. `ModelGenerationService.reanalyze` maps changed entity kinds to the earliest affected vertical stage and executes all downstream stages with a `vertical_reanalysis` Run. The explicit `/reanalyze/execute` endpoint and requirement detail action expose the behavior while the original request-only endpoint remains compatible.

- [x] **Step 1: Add targeted execution tests**
- [x] **Step 2: Implement stage selection and downstream execution**
- [x] **Step 3: Expose the execution endpoint and Review action**
- [x] **Step 4: Run focused and full verification**
