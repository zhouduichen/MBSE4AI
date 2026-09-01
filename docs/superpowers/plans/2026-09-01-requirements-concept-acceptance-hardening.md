# 需求分析与总体概念设计验收收口实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 1.1 正式 gold 验收契约，补强 1.2 MBSE 一致性验收，并让 2.1/2.2 的概念设计证据和评估器正式门禁可审计，同时明确不实施 3.1–3.3。

**Architecture:** 在现有 acceptance harness、canonical MBSE flow、概念设计服务和 `DisciplineAdapter` 端口上增量扩展。来源区域 ID 只作为追溯证据，需求 gold 使用稳定 key+原文锚点；布局清单和评估器批准证据作为派生、可哈希的审计对象，不改变现有页面流程或旧 API 字段。

**Tech Stack:** Python 3.11+, dataclasses, JSON/JSON Schema, SQLite persistence boundary, FastAPI/Jinja/HTMX, pytest, Import Linter, compileall。

## Global Constraints

- 本计划只实施客户功能 1.1、1.2、2.1、2.2；不实施 3.1、3.2、3.3 的 CAD、PMI/GD&T 或 DFM/DFA。
- 不引入向导、不重排现有导航；保留项目 → 需求输入 → 审核 → 场景 → MBSE 和概念设计页面路径。
- 旧 v1/v2 gold、旧 API 字段和旧 `DisciplineAdapter.evaluate()` 调用继续可读；旧 gold 不得正式通过。
- 代码最低正式门槛固定为需求 precision/recall ≥ 0.90、详情 micro-F1 ≥ 0.85（gold 提供详情时）和 provenance 完整率 100%；gold 只能提高门槛。
- 动态 `region-*` ID 不参与跨运行需求身份匹配；来源文本和 `source_anchor` 参与配对，区域 ID 只用于完整性检查。
- 所有隐含约束仍须逐条人工审核；概念布局仍明确标记 `conceptual_2d_svg`；内置低阶评估器仍为 `development_only`。
- 不执行任意用户命令、CAD 脚本或外部求解器；外部正式评估器只通过已存在的 `DisciplineAdapter` 端口注入。
- 测试命令使用 `RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config`，避免桌面 LLM 配置影响结果。
- 根目录未跟踪参考 PPT/PDF/DOCX、`release/` 交付目录和虚拟环境不加入代码提交。

---

## 文件结构

### 新建生产文件

- `src/rflp_lite/application/acceptance_gold.py` — Gold v3 读取、校验、来源锚点配对和稳定匹配对象。
- `src/rflp_lite/application/mbse_acceptance.py` — canonical flow、视图覆盖、追溯和编辑 CAS 验收指标。
- `src/rflp_lite/application/layout_evidence.py` — `LayoutArtifactManifest` 的构造和哈希。
- `src/rflp_lite/application/evaluator_approval.py` — 评估器批准证据、适用域和误差门禁。

### 新建测试和样例

- `tests/application/test_acceptance_gold.py`
- `tests/application/test_mbse_acceptance.py`
- `tests/application/test_layout_evidence.py`
- `tests/application/test_evaluator_approval.py`
- `src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json`

### 重点修改文件

- `src/rflp_lite/application/acceptance_metrics.py`
- `src/rflp_lite/application/acceptance_harness.py`
- `src/rflp_lite/interface/cli.py`
- `src/rflp_lite/application/use_case_modeling.py`
- `src/rflp_lite/application/mbse_semantics.py`
- `src/rflp_lite/application/mbse_modeling.py`
- `src/rflp_lite/domain/concept_design.py`
- `src/rflp_lite/application/concept_design_service.py`
- `src/rflp_lite/application/discipline_batch.py`
- `src/rflp_lite/adapters/disciplines.py`
- `src/rflp_lite/interface/web/api_v1.py`
- `src/rflp_lite/interface/web/routes.py`
- `src/rflp_lite/interface/web/templates/concept-design.html`
- `src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json`
- `README.md`
- `docs/DEVELOPMENT_STATUS.md`

每个任务都先写失败测试、单独运行、实现最小改动、运行回归并提交；后续任务只依赖此前任务的公开接口。

---

### Task 1: Gold v3 契约与稳定来源锚点配对

**Files:**

- Create: `src/rflp_lite/application/acceptance_gold.py`
- Modify: `src/rflp_lite/application/acceptance_metrics.py`
- Create: `tests/application/test_acceptance_gold.py`

**Interfaces:**

- Consumes: JSON gold payload and actual requirement dictionaries containing `statement` and `source_region_id`/`source_span_id`.
- Produces:
  - `load_gold_contract(path: Path) -> GoldContract`
  - `validate_gold_payload(payload: object) -> GoldContract`
  - `match_requirement_items(actual, expected, source_text_by_region) -> RequirementMatchReport`
  - `evaluate_requirement_extraction(actual, expected, *, source_text_by_region=None, contract=None) -> dict[str, object]`

- [ ] **Step 1: Write failing contract and matcher tests**

```python
def test_source_region_id_is_not_a_cross_run_identity():
    gold = validate_gold_payload({
        "version": 3,
        "corpus_mode": "complete",
        "details_mode": "complete",
        "requirements": [{
            "key": "REQ-1",
            "statement": "系统支持导入 PDF",
            "source_anchor": "支持导入 PDF",
            "details": [],
        }],
    })
    report = match_requirement_items(
        ({"id": "actual-1", "statement": "系统支持导入 PDF", "source_region_id": "region-new"},),
        gold.requirements,
        {"region-new": "第 1 条：支持导入 PDF。"},
    )
    assert report.matched == ("REQ-1",)
    assert report.provenance_complete == 100


def test_same_anchor_with_wrong_statement_is_not_a_match():
    gold = validate_gold_payload({
        "version": 3,
        "corpus_mode": "complete",
        "details_mode": "complete",
        "requirements": [{
            "key": "REQ-1",
            "statement": "系统支持导入 PDF",
            "source_anchor": "支持导入 PDF",
            "details": [],
        }],
    })
    report = match_requirement_items(
        ({"id": "actual-1", "statement": "系统删除全部数据", "source_region_id": "region-new"},),
        gold.requirements,
        {"region-new": "第 1 条：支持导入 PDF。"},
    )
    assert report.matched == ()
    assert report.unmatched_actual


def test_gold_rejects_duplicate_keys_and_non_complete_corpus():
    with pytest.raises(ContractViolation):
        validate_gold_payload({"version": 3, "corpus_mode": "sample", "details_mode": "complete", "requirements": []})
    with pytest.raises(ContractViolation):
        validate_gold_payload({
            "version": 3,
            "corpus_mode": "complete",
            "details_mode": "complete",
            "requirements": [
                {"key": "REQ-1", "statement": "A", "source_anchor": "A", "details": []},
                {"key": "REQ-1", "statement": "B", "source_anchor": "B", "details": []},
            ],
        })
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_gold.py -q
```

Expected: FAIL because `acceptance_gold.py` and the extended matcher do not exist.

- [ ] **Step 3: Implement the immutable gold contract and deterministic matcher**

Implement the following public records and normalization behavior:

```python
@dataclass(frozen=True, slots=True)
class GoldRequirement:
    key: str
    statement: str
    accepted_statements: tuple[str, ...]
    source_anchor: str
    details: tuple[dict[str, object], ...]

@dataclass(frozen=True, slots=True)
class GoldContract:
    version: int
    corpus_mode: str
    details_mode: str
    requirements: tuple[GoldRequirement, ...]
    thresholds: dict[str, float]
    mbse_expectations: dict[str, object]

def normalize_acceptance_text(value: object) -> str:
    text = "" if value is None else str(value)
    return "".join(text.split()).rstrip("。.!！?？;；")
```

`validate_gold_payload()` must require version 3, `corpus_mode == "complete"`, `details_mode == "complete"`, non-empty unique keys/anchors/statements, and finite numeric thresholds. It must copy values into immutable tuples and reject unknown top-level fields only if they can alter gates.

`match_requirement_items()` must first map each actual source ID to source text, find exactly one normalized `source_anchor` containment, then pair the actual statement to `statement + accepted_statements`. Exact normalized equality passes; containment passes only when the shorter normalized string is at least 80% of the longer one. Resolve ties by descending similarity, then gold key, then actual ID. Return matched keys, unmatched actual/expected, pair diagnostics and provenance percentage.

- [ ] **Step 4: Extend metrics without changing the old call shape**

Keep `evaluate_requirement_extraction(actual, expected)` valid for v1 callers. Add keyword-only source mapping and contract support:

```python
def evaluate_requirement_extraction(
    actual,
    expected,
    *,
    source_text_by_region=None,
    contract=None,
) -> dict[str, object]:
    """Return deterministic requirement and optional detail metrics."""
```

When a v3 contract is present, use source-anchor matching and add `gold_contract_status`, `requirement_matches`, `detail_metrics`, and `provenance_diagnostics`. Keep `precision`, `recall`, `f1`, `provenance_complete`, `matched`, `unmatched_actual`, and `unmatched_expected` for API compatibility.

- [ ] **Step 5: Run focused and compatibility tests**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_gold.py tests/application/test_acceptance_metrics.py -q
```

Expected: all new and existing metric tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/acceptance_gold.py src/rflp_lite/application/acceptance_metrics.py tests/application/test_acceptance_gold.py tests/application/test_acceptance_metrics.py
git commit -m "feat: add stable gold source-anchor matching"
```

---

### Task 2: 完整 Gold v3 与 1.1 正式验收报告

**Files:**

- Create: `src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json`
- Modify: `src/rflp_lite/application/acceptance_harness.py`
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `tests/application/test_acceptance_harness.py`

**Interfaces:**

- Consumes: Task 1 `GoldContract` and the existing `analyze_artifact()` state.
- Produces: gold-backed reports whose `formal_status` can pass only with complete requirements, details, provenance and MBSE gates.

- [ ] **Step 1: Write failing harness tests**

```python
def test_complete_gold_ignores_dynamic_region_ids_and_reports_detail_metrics(tmp_path):
    gold = tmp_path / "gold-v3.json"
    gold.write_text(json.dumps({
        "version": 3,
        "corpus_mode": "complete",
        "details_mode": "complete",
        "requirements": [{
            "key": "REQ-1",
            "statement": "支持导入 PDF",
            "source_anchor": "支持导入 PDF",
            "details": [],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。".encode(), gold)
    assert report["formal_status"] == "passed"
    assert report["gold_contract_status"] == "valid"
    assert report["extraction_metrics"]["provenance_complete"] == 100


def test_incomplete_or_legacy_gold_cannot_formally_pass(tmp_path):
    gold = tmp_path / "gold-v2.json"
    gold.write_text('{"version": 2, "requirements": [{"statement": "支持导入 PDF"}]}', encoding="utf-8")
    report = run_customer_acceptance("requirements.txt", "支持导入 PDF。".encode(), gold)
    assert report["smoke_status"] == "passed"
    assert report["formal_status"] in {"failed", "not_evaluated"}
    assert report["gold_contract_status"] == "legacy_only"
```

- [ ] **Step 2: Run tests to capture current false positive/ID behavior**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_harness.py -q
```

Expected: the v3 test fails and the legacy behavior exposes no `gold_contract_status`.

- [ ] **Step 3: Create a complete v3 gold sample**

Create `requirements-gold-v3.json` with six stable keys, one for each non-empty line in `customer-requirements.txt`, and source anchors copied from the original lines. Include explicit details for the `3~5` range and any numeric/unit constraint extracted by the current parser. Do not place generated `region-*` IDs in this file. Set:

```json
{
  "version": 3,
  "corpus_mode": "complete",
  "details_mode": "complete",
  "thresholds": {
    "requirement_precision": 0.9,
    "requirement_recall": 0.9,
    "detail_micro_f1": 0.85,
    "provenance_complete": 100
  },
  "mbse_expectations": {
    "requirement_coverage": 1.0,
    "trace_complete": 1.0,
    "canonical_flow_consistent": true,
    "edit_cas_verified": true
  },
  "requirements": [
    {
      "key": "REQ-1.1-DOCUMENT-IMPORT",
      "statement": "支持导入作战纲要、技战术指标文档（Word/PDF），利用NLP自动提取实体、属性及隐含约束。",
      "source_anchor": "支持导入作战纲要、技战术指标文档（Word/PDF）",
      "details": []
    },
    {
      "key": "REQ-1.2-USE-CASE",
      "statement": "智能体基于需求文本，推荐典型作战场景的时序图/活动图框架；支持人机交互修改。",
      "source_anchor": "推荐典型作战场景的时序图/活动图框架",
      "details": []
    },
    {
      "key": "REQ-2.1-LAYOUT",
      "statement": "输入指标包络，智能体检索相似方案库，生成3~5套满足约束的初始总体布局草图。",
      "source_anchor": "生成3~5套满足约束的初始总体布局草图",
      "details": [
        {"kind": "attribute", "name": "候选数量", "minimum": 3, "maximum": 5, "unit": "套"}
      ]
    },
    {
      "key": "REQ-2.2-MDO",
      "statement": "针对生成的布局参数，自动调用轻量化仿真工具（或AI降阶模型）进行多学科的批量快速仿真计算，并反馈给优化器。",
      "source_anchor": "自动调用轻量化仿真工具",
      "details": []
    },
    {
      "key": "REQ-3.1-CAD",
      "statement": "设计师通过自然语言描述设计意图，智能体自动驱动三维建模软件执行参数化建模操作。",
      "source_anchor": "通过自然语言描述设计意图",
      "details": []
    },
    {
      "key": "REQ-3.2-ANNOTATION",
      "statement": "智能体自动标注关键尺寸公差与形位公差基准，并检查可制造性与可装配性风险。",
      "source_anchor": "自动标注关键尺寸公差与形位公差基准",
      "details": []
    }
  ]
}
```

The validator must reject an empty list so the sample cannot silently pass. The 3.x records remain in the corpus for honest coverage reporting, but no 3.x implementation gate is added by this plan.

- [ ] **Step 4: Integrate the contract into `run_customer_acceptance()`**

Load v3 through `load_gold_contract()`. Build `source_text_by_region` from the analyzed document. For v3, call `evaluate_requirement_extraction(..., source_text_by_region=..., contract=...)`; for v1/v2, preserve compatibility metrics but set `gold_contract_status` to `legacy_only` and `formal_status` to `failed` or `not_evaluated`.

Add report fields:

```python
report["effective_thresholds"] = effective_thresholds
report["formal_failures"] = formal_failures
report["provenance_diagnostics"] = metrics.get("provenance_diagnostics", [])
```

Formal status must remain false when `corpus_mode` is not complete, the gold contract is invalid, any expected requirement is missing, any unexpected actual item remains, or details are incomplete. `status` continues to alias formal status when gold is provided and smoke status otherwise.

- [ ] **Step 5: Update CLI and tests**

Keep `rflp acceptance --requirements FILE [--gold FILE]` unchanged. Ensure its exit code reads `formal_status` for any gold file. Add tests for complete v3 pass, wrong statement fail, extra actual fail, and dynamic source IDs.

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_acceptance_harness.py tests/application/test_acceptance_metrics.py tests/application/test_acceptance_gold.py -q
```

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json src/rflp_lite/application/acceptance_harness.py src/rflp_lite/interface/cli.py tests/application/test_acceptance_harness.py
git commit -m "fix: close formal requirements acceptance contract"
```

---

### Task 3: MBSE canonical flow formal metrics and edit acceptance

**Files:**

- Create: `src/rflp_lite/application/mbse_acceptance.py`
- Modify: `src/rflp_lite/application/use_case_modeling.py`
- Modify: `src/rflp_lite/application/mbse/legacy_builder.py`
- Modify: `src/rflp_lite/application/mbse_semantics.py`
- Modify: `src/rflp_lite/application/mbse_modeling.py`
- Modify: `src/rflp_lite/application/acceptance_harness.py`
- Create: `tests/application/test_mbse_acceptance.py`
- Modify: `tests/application/test_acceptance_harness.py`

**Interfaces:**

- Consumes: reviewed workbench state and `generate_mbse_revision()` output.
- Produces: `evaluate_mbse_acceptance(state: dict[str, object]) -> dict[str, object]` with coverage, consistency, trace and CAS metrics.

- [ ] **Step 1: Write failing metrics tests**

```python
def test_mbse_acceptance_requires_one_canonical_flow_across_views():
    state = fixture_reviewed_state()
    state = generate_mbse_revision(state)
    metrics = evaluate_mbse_acceptance(state)
    assert metrics["requirement_coverage"] == 1.0
    assert metrics["cross_view_consistency"] == 1.0
    assert metrics["trace_complete"] == 1.0
    assert metrics["projection_complete"] is True


def test_mbse_edit_cas_and_targeted_stale_are_verified_without_persisting():
    state = generate_mbse_revision(fixture_reviewed_state())
    metrics = evaluate_mbse_acceptance(state)
    assert metrics["edit_cas_verified"] is True
    assert metrics["edited_target_id"]
    assert metrics["unrelated_stale_count"] == 0


def test_different_flow_hash_is_not_consistent():
    state = generate_mbse_revision(fixture_reviewed_state())
    state["mbse"]["messages"][0]["canonical_flow_hash"] = "wrong"
    assert evaluate_mbse_acceptance(state)["cross_view_consistency"] < 1.0
```

- [ ] **Step 2: Run the focused tests and verify failure**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_mbse_acceptance.py -q
```

Expected: FAIL because no formal metrics module or canonical flow hash fields exist for every projection.

- [ ] **Step 3: Attach canonical flow identity to projections**

In `build_use_case_drafts()`, calculate one hash from the ordered flow steps and add it to each draft:

```python
flow_payload = tuple(
    (step["order"], step["sender"], step["receiver"], step["message"], step["guard"], step["branch"])
    for step in flows
)
flow_hash = canonical_hash(flow_payload)
draft["canonical_flow_id"] = f"flow-{flow_hash[:12]}"
draft["canonical_flow_hash"] = flow_hash
```

Propagate the same fields into generated scenario, Use Case, Activity and Message projections in `mbse_semantics.py`/`mbse_modeling.py`. Do not recompute different hashes from rendered SVG or ordering that can change per view.

- [ ] **Step 4: Implement `evaluate_mbse_acceptance()`**

The function must:

1. collect accepted requirement IDs;
2. verify every projected reference points to a known requirement and every trace endpoint exists;
3. compare canonical flow IDs/hashes across Use Case, Activity and Message collections;
4. require non-empty Use Case, Activity and Sequence projections;
5. deep-copy the state, edit one message using current revision, verify revision change and targeted stale set, then retry with the old revision and require `ContractViolation`;
6. return deterministic metrics and diagnostics without writing through a repository.

Use the existing `apply_mbse_edit()` and `model_impact` functions rather than duplicating stale propagation.

- [ ] **Step 5: Combine MBSE metrics with gold formal status**

When a v3 gold has `mbse_expectations`, `run_customer_acceptance()` must include `mbse_metrics` and make top-level `formal_status == "passed"` only when both extraction/detail gates and MBSE expectations pass. Smoke status continues to use executable presence checks.

- [ ] **Step 6: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_mbse_acceptance.py tests/application/test_mbse_modeling.py tests/application/test_mbse_semantics.py tests/application/test_acceptance_harness.py -q
git add src/rflp_lite/application/mbse_acceptance.py src/rflp_lite/application/use_case_modeling.py src/rflp_lite/application/mbse_semantics.py src/rflp_lite/application/mbse_modeling.py src/rflp_lite/application/acceptance_harness.py tests/application/test_mbse_acceptance.py tests/application/test_acceptance_harness.py
git commit -m "feat: add formal MBSE flow acceptance metrics"
```

---

### Task 4: 2.1 总体布局证据清单

**Files:**

- Create: `src/rflp_lite/application/layout_evidence.py`
- Modify: `src/rflp_lite/application/concept_design_service.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/concept-design.html`
- Create: `tests/application/test_layout_evidence.py`

**Interfaces:**

- Consumes: `LayoutCandidate`, all candidates, validated concept pack and similarity matches.
- Produces: `build_layout_manifest(pack, candidate, candidates) -> dict[str, object]` and `layout_manifests` in concept run payloads.

- [ ] **Step 1: Write failing manifest tests**

```python
def test_layout_manifest_declares_conceptual_svg_and_hashes():
    pack, candidates = fixture_candidates()
    manifest = build_layout_manifest(pack, candidates[0], candidates)
    assert manifest["representation_kind"] == "conceptual_2d_svg"
    assert manifest["views"] == ["top", "side"]
    assert manifest["candidate_id"] == candidates[0].id
    assert manifest["svg_hash"]
    assert manifest["manifest_hash"] == canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"})


def test_layout_manifest_reports_pairwise_distance_and_constraint_margins():
    pack, candidates = fixture_candidates()
    manifest = build_layout_manifest(pack, candidates[0], candidates)
    assert manifest["minimum_pairwise_distance"] >= 0.08
    assert manifest["hard_constraint_margins"]
    assert manifest["reference_scheme_ids"]
```

- [ ] **Step 2: Run focused tests and verify failure**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_layout_evidence.py -q
```

Expected: FAIL because no manifest builder exists.

- [ ] **Step 3: Implement deterministic manifest construction**

Use only candidate and pack data; never add wall-clock time or random values:

```python
def build_layout_manifest(pack, candidate, candidates):
    distances = [
        candidate_distance(pack, candidate, other)
        for other in candidates
        if other.id != candidate.id
    ]
    body = {
        "candidate_id": candidate.id,
        "representation_kind": "conceptual_2d_svg",
        "views": ["top", "side"],
        "unit_system": "SI",
        "reference_scheme_ids": list(candidate.reference_ids),
        "similarity_matches": [to_primitive(item) for item in candidate.similarity_matches],
        "parameter_differences": [to_primitive(item) for item in candidate.parameter_sources],
        "hard_constraint_margins": [
            {"id": item.constraint_id, "margin": item.margin, "passed": item.passed}
            for item in candidate.constraints if item.severity == "hard"
        ],
        "minimum_pairwise_distance": min(distances) if distances else 1.0,
        "generator_id": str(pack.get("id_prefix", "layout-generator")),
        "generator_version": candidate.generator_version,
        "seed": candidate.seed,
        "input_hash": candidate.input_hash,
        "svg_hash": canonical_hash(candidate.svg),
    }
    return {**body, "manifest_hash": canonical_hash(body)}
```

- [ ] **Step 4: Add manifests to concept results and persistence-compatible conversion**

Add `layout_manifests: tuple[dict[str, object], ...] = ()` at the end of `ConceptRunResult`. Generate one manifest per candidate before calculating the run result hash, include manifests in the result hash, and make `concept_run_from_payload()` default to an empty tuple for old records.

- [ ] **Step 5: Expose evidence without changing routes**

Add `layout_manifests` to the existing concept run API response and show in the existing concept page:

```html
<p>表示类型：{{ manifest.representation_kind }} · 视图：{{ manifest.views|join(', ') }} · SVG 哈希：{{ manifest.svg_hash }}</p>
```

Display an explicit Chinese notice: “参数化二维概念布局草图，不是三维 CAD”。Keep candidate review forms and URLs unchanged.

- [ ] **Step 6: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_layout_evidence.py tests/application/test_concept_design_service.py tests/interface/web/test_api_v1.py tests/interface/web/test_pages.py -q
git add src/rflp_lite/application/layout_evidence.py src/rflp_lite/application/concept_design_service.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/concept-design.html tests/application/test_layout_evidence.py
git commit -m "feat: add auditable concept layout manifests"
```

---

### Task 5: 2.1 可执行验收增加候选差异、表示类型和追溯门禁

**Files:**

- Modify: `src/rflp_lite/application/concept_acceptance.py`
- Modify: `tests/application/test_concept_acceptance.py`
- Modify: `README.md`

**Interfaces:**

- Consumes: Task 4 manifests and existing `run_concept_design()` result.
- Produces: additional acceptance checks without changing `status=passed` software smoke semantics or `formal_status=development_only` for the development profile.

- [ ] **Step 1: Write failing acceptance checks**

```python
def test_concept_acceptance_checks_diversity_manifest_and_representation():
    report = run_concept_acceptance(PACK, SCHEMES, ENVELOPE, DEVELOPMENT_PROFILE)
    assert report["checks"]["2.1.candidate_diversity"] is True
    assert report["checks"]["2.1.layout_manifest"] is True
    assert report["checks"]["2.1.conceptual_representation"] is True
    assert report["checks"]["2.1.source_trace"] is True
```

- [ ] **Step 2: Run the test to verify failure**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_concept_acceptance.py -q
```

Expected: FAIL because the report has no manifest or diversity checks.

- [ ] **Step 3: Implement checks**

For every candidate, require a valid manifest hash, `representation_kind == "conceptual_2d_svg"`, non-empty reference IDs, and hard margins. For every candidate pair, call `candidate_distance(pack, left, right)` and require it to be at least the pack's `generation.minimum_distance`. Add the deterministic check to `checks` and include failing candidate IDs in diagnostics.

- [ ] **Step 4: Preserve formal boundary in report and docs**

Keep development profile behavior:

```python
report["status"] = "passed" if all(checks.values()) else "failed"
report["formal_status"] = (
    first.formal_status if first.formal_status == "passed" else "development_only"
)
```

Document that these checks prove software orchestration, not engineering validity of the low-order models.

- [ ] **Step 5: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_concept_acceptance.py tests/application/test_layout_generation.py tests/application/test_layout_evidence.py -q
git add src/rflp_lite/application/concept_acceptance.py tests/application/test_concept_acceptance.py README.md
git commit -m "test: harden concept layout acceptance evidence"
```

---

### Task 6: 2.2 评估器批准证据契约

**Files:**

- Create: `src/rflp_lite/application/evaluator_approval.py`
- Modify: `src/rflp_lite/domain/concept_design.py`
- Modify: `src/rflp_lite/application/discipline_batch.py`
- Modify: `src/rflp_lite/adapters/disciplines.py`
- Modify: `src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json`
- Create: `tests/application/test_evaluator_approval.py`
- Modify: `tests/application/test_discipline_batch.py`

**Interfaces:**

- Consumes: registered adapter metadata, evaluator profile, candidate parameters and discipline result.
- Produces:
  - `validate_approval_profile(payload: object) -> dict[str, object]`
  - `adapter_implementation_hash(adapter: object) -> str`
  - `formal_approval_for(adapter, discipline, profile, parameters) -> ApprovalDecision`

- [ ] **Step 1: Write failing approval tests**

```python
def test_formal_approval_requires_version_hash_domain_dataset_and_human_basis():
    adapter = ApprovedTestAdapter()
    profile = {
        "id": "customer-v1",
        "version": 1,
        "approvals": {
            adapter.id: {
                "adapter_version": adapter.version,
                "implementation_hash": adapter.implementation_hash,
                "source_kind": "customer_solver",
                "validity_domain": {"mass_kg": {"minimum": 100, "maximum": 2000}},
                "validation_dataset_id": "gold-aero-1",
                "validation_dataset_version": "1",
                "validation_dataset_hash": "dataset-hash",
                "error_metrics": {"lift_to_drag_rmse": 0.02},
                "acceptance_limits": {"lift_to_drag_rmse": 0.05},
                "approved_for_formal": True,
                "approved_by": "customer",
                "approved_at": "2026-09-01T00:00:00Z",
                "basis": "customer validation report",
            }
        },
    }
    decision = formal_approval_for(adapter, {"id": "aerodynamics"}, profile, {"mass_kg": 500})
    assert decision.approved is True


def test_changed_implementation_hash_or_out_of_domain_is_development():
    adapter = ApprovedTestAdapter()
    profile = complete_profile_for(adapter)
    changed = replace(adapter, implementation_hash="changed")
    assert formal_approval_for(changed, {"id": "aerodynamics"}, profile, {"mass_kg": 500}).approved is False
    assert formal_approval_for(adapter, {"id": "aerodynamics"}, profile, {"mass_kg": 5000}).approved is False
```

The test module defines the reusable deterministic fixtures used by Tasks 6–7. `ApprovedTestAdapter` is a frozen dataclass with fields `id`, `version`, `source_kind`, and `implementation_hash`; its `evaluate(candidate, profile)` method delegates to a built-in calculator and replaces the returned adapter metadata. `complete_profile_for(adapter)` returns the complete approval payload shown above. `make_candidate_and_pack()` reuses the existing fixed-wing fixture, and `run_batch_with_profile(profile)` calls `evaluate_candidates()` with a temporary in-memory store. `dataclasses.replace()` is used only on this fixture, never on a production adapter with runtime state.

- [ ] **Step 2: Run focused tests and verify failure**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_evaluator_approval.py -q
```

Expected: FAIL because profile validation currently accepts only adapter version and boolean approval.

- [ ] **Step 3: Implement approval validation**

Require each approval entry to contain non-empty `adapter_version`, `implementation_hash`, `source_kind`, `validity_domain`, `validation_dataset_id`, `validation_dataset_version`, `validation_dataset_hash`, `error_metrics`, `acceptance_limits`, `approved_for_formal`, `approved_by`, `approved_at`, and `basis`. Validate numeric error values against numeric limits and ensure every validity bound has minimum and maximum.

Add a deterministic adapter hash contract. Built-in adapters declare a stable `implementation_hash` derived from their algorithm/version constant; test adapters declare it explicitly. Do not hash memory addresses or file paths.

- [ ] **Step 4: Extend `DisciplineEvaluation` compatibly**

Append defaulted fields to the frozen dataclass:

```python
implementation_hash: str = ""
approval_profile_hash: str = ""
approval_diagnostics: tuple[str, ...] = ()
```

Update `_payload_evaluation()` and serialization conversions with empty defaults for old persisted rows.

- [ ] **Step 5: Add the development profile and adapter metadata**

Keep `development-evaluator-profile.json` as:

```json
{"id": "development-v1", "version": 1, "approvals": {}}
```

Built-in adapters must expose `id`, `version`, `source_kind`, and `implementation_hash`, but no approval entry. Therefore they remain development evidence.

- [ ] **Step 6: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_evaluator_approval.py tests/application/test_discipline_batch.py tests/adapters/test_disciplines.py -q
git add src/rflp_lite/application/evaluator_approval.py src/rflp_lite/domain/concept_design.py src/rflp_lite/application/discipline_batch.py src/rflp_lite/adapters/disciplines.py src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json tests/application/test_evaluator_approval.py tests/application/test_discipline_batch.py
git commit -m "feat: require auditable evaluator approval evidence"
```

---

### Task 7: 2.2 正式状态、缓存和优化证据收口

**Files:**

- Modify: `src/rflp_lite/application/discipline_batch.py`
- Modify: `src/rflp_lite/application/concept_design_service.py`
- Modify: `src/rflp_lite/application/concept_acceptance.py`
- Modify: `tests/application/test_discipline_batch.py`
- Modify: `tests/application/test_concept_design_service.py`
- Modify: `tests/application/test_concept_acceptance.py`

**Interfaces:**

- Consumes: Task 6 `ApprovalDecision` and extended `DisciplineEvaluation`.
- Produces: formal evidence only for fully approved, in-domain, error-compliant evaluations; development evidence for all built-ins and incomplete approvals.

- [ ] **Step 1: Write failing cache and gate tests**

Use the `make_candidate_and_pack()` and `run_batch_with_profile()` fixtures defined in Task 6; `evaluate_one()` is a small test helper that returns the first evaluation from that batch, while the two profile helpers clone the complete profile and alter only the approval dataset hash or adapter approval set. `run_with_one_development_evaluation()` executes the normal concept service with the development profile; `run_with_three_approved_test_adapters()` injects three `ApprovedTestAdapter` instances and a complete profile into the same service, so these tests exercise only the formal gate and not a production claim.

```python
def test_cache_key_changes_when_implementation_or_approval_hash_changes():
    first = evaluate_one(profile=complete_profile_for(ApprovedTestAdapter()))
    second = evaluate_one(profile=profile_with_changed_approval_dataset())
    assert first.evaluation.input_hash != second.evaluation.input_hash


def test_all_three_formal_disciplines_are_required_for_formal_concept_run():
    result = run_with_one_development_evaluation()
    assert result.formal_status == "development"


def test_complete_approved_adapter_profile_can_formal_pass_in_test_only():
    result = run_with_three_approved_test_adapters()
    assert result.formal_status == "passed"
```

- [ ] **Step 2: Run tests to verify the current weak gate**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_discipline_batch.py tests/application/test_concept_design_service.py -q
```

Expected: new tests fail because cache keys do not include implementation/approval hashes and formal status only checks the existing evidence string.

- [ ] **Step 3: Strengthen evaluation execution and cache keys**

In `evaluate_candidates()`:

1. compute `implementation_hash = adapter_implementation_hash(selected)`;
2. compute `approval_profile_hash = canonical_hash(profile)`;
3. include both values and the validity-domain hash in the cache key;
4. attach them to each `DisciplineEvaluation`;
5. call `formal_approval_for()` after successful evaluation and preserve its diagnostics;
6. mark `evidence_status = "formal"` only when the decision is approved.

Cached results must be rechecked against the current approval profile and adapter metadata before being returned as formal. A cache hit with changed approval evidence becomes development or is recomputed.

- [ ] **Step 4: Tighten concept formal status**

In `run_concept_design()`, set formal status to passed only if every evaluation is succeeded/cached, every evaluation has `evidence_status == "formal"`, every candidate has complete formal discipline coverage, and the optimization run evidence status is formal. Preserve `development` for built-in profiles.

- [ ] **Step 5: Expand concept acceptance report**

Add checks:

```python
"2.2.formal_evidence_consistent": all(
    item.evidence_status == "formal"
    for item in first.evaluations
    if first.formal_status == "passed"
),
"2.2.cache_identity": first.run_hash == second.run_hash,
"2.2.approval_diagnostics_present": all(
    isinstance(item.approval_diagnostics, tuple)
    for item in first.evaluations
),
```

- [ ] **Step 6: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/application/test_discipline_batch.py tests/application/test_concept_design_service.py tests/application/test_concept_acceptance.py -q
git add src/rflp_lite/application/discipline_batch.py src/rflp_lite/application/concept_design_service.py src/rflp_lite/application/concept_acceptance.py tests/application/test_discipline_batch.py tests/application/test_concept_design_service.py tests/application/test_concept_acceptance.py
git commit -m "fix: enforce formal multidisciplinary evidence gates"
```

---

### Task 8: 页面/API/文档和兼容性接入

**Files:**

- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/concept-design.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-review.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `tests/interface/web/test_api_v1.py`
- Modify: `tests/interface/web/test_pages.py`

**Interfaces:**

- Consumes: new acceptance, MBSE metrics, layout manifests and evaluator diagnostics.
- Produces: additive API/page fields and honest Chinese labels while preserving existing routes and POST/303 behavior.

- [ ] **Step 1: Write failing presentation tests**

```python
def test_concept_page_exposes_representation_and_formal_evidence(client):
    response = client.get("/w/demo/concept-design?run_id=run-1")
    assert "参数化二维概念布局草图，不是三维 CAD" in response.text
    assert "formal_status" in response.text


def test_concept_api_contains_manifests_and_approval_diagnostics(client):
    payload = client.get("/api/v1/workspaces/demo/concept-runs/run-1").json()
    assert "layout_manifests" in payload["run"]
    assert "approval_diagnostics" in payload["run"]["evaluations"][0]
```

- [ ] **Step 2: Run page/API tests and verify missing fields**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/interface/web/test_api_v1.py tests/interface/web/test_pages.py -q
```

- [ ] **Step 3: Add additive API fields and page sections**

Expose `layout_manifests`, `mbse_metrics`, `gold_contract_status`, `formal_failures`, and evaluation approval diagnostics in existing response objects. Do not remove or rename `status`, `formal_status`, `candidates`, `evaluations`, `trace_links`, or existing routes.

In the concept page, show manifest representation, source schemes, minimum pairwise distance, hard constraint margins, and evidence state. In the requirements review page, keep the existing attribute/constraint review cards and add formal gold diagnostics only when present. In scenario/MBSE pages, show retrieval and canonical consistency diagnostics only when present.

- [ ] **Step 4: Update documentation**

Update the root README and `docs/DEVELOPMENT_STATUS.md` to say:

- requirements formal acceptance uses complete gold v3 and source anchors;
- 2.1 outputs conceptual 2D SVG manifests;
- 2.2 built-in low-order evaluators remain development-only;
- no 3.x work is included in this release.

- [ ] **Step 5: Run tests and commit**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest tests/interface/web/test_api_v1.py tests/interface/web/test_pages.py tests/application/test_acceptance_harness.py tests/application/test_concept_acceptance.py -q
git add src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/concept-design.html src/rflp_lite/interface/web/templates/requirements-review.html src/rflp_lite/interface/web/templates/requirements-scenarios.html README.md docs/DEVELOPMENT_STATUS.md tests/interface/web/test_api_v1.py tests/interface/web/test_pages.py
git commit -m "feat: expose acceptance and concept evidence in UI"
```

---

### Task 9: 全量门禁、文档自审和最终提交

**Files:**

- Modify only files needed to resolve test or schema failures from Tasks 1–8.
- Do not add package archives, root reference documents or generated databases.

**Interfaces:**

- Consumes: all prior task outputs.
- Produces: a clean, tested branch with honest 1.1/1.2/2.1/2.2 acceptance and no 3.x claims.

- [ ] **Step 1: Run focused acceptance commands**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/rflp acceptance --requirements src/rflp_lite/resources/examples/customer-acceptance/customer-requirements.txt --gold src/rflp_lite/resources/examples/customer-acceptance/requirements-gold-v3.json
.venv/bin/rflp concept acceptance --pack src/rflp_lite/resources/domain-packs/fixed-wing-v1.json --schemes src/rflp_lite/resources/examples/concept-design/fixed-wing-schemes.json --envelope src/rflp_lite/resources/examples/concept-design/fixed-wing-envelope.json --evaluator-profile src/rflp_lite/resources/examples/concept-design/development-evaluator-profile.json
```

Expected:

- requirements smoke and formal status both pass on the complete v3 fixture;
- concept software status passes;
- concept formal status remains `development_only`.

- [ ] **Step 2: Run full test and static gates**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-codex-empty-test-config .venv/bin/python -m pytest -q
python3 -m compileall -q src tests
.venv/bin/python -m pytest tests/architecture -q
```

Expected: all tests pass; only the existing Starlette/httpx deprecation warning may remain.

- [ ] **Step 3: Inspect compatibility and repository scope**

```bash
git diff --check HEAD~8..HEAD
git status --short
git diff --name-only HEAD~8..HEAD | rg '(^|/)(release|\.venv|.*\.db$)' && exit 1 || true
```

Confirm old v1/v2 gold tests, legacy six-block calls, concept routes, API fields, and migration tests still pass. Confirm no archive or reference binary is staged.

- [ ] **Step 4: Self-review formal claims**

Search the changed docs and code for `3.1`, `3.2`, `3.3`, `formal_status`, `development_only`, and `conceptual_2d_svg`. Every statement about 2.2 must distinguish software orchestration from engineering validity; every statement about 3.x must say not implemented.

- [ ] **Step 5: Commit any final test-only/doc corrections**

```bash
# If a correction was required, repeat the explicit git add command from its Task 1–8 section.
git commit -m "chore: close acceptance hardening regression gates"
```

- [ ] **Step 6: Final handoff**

Report the final commit IDs, full test command and result, requirement-level statuses, the gold source-anchor fix, and the explicit remaining boundary that 3.1–3.3 are not implemented. Do not claim formal 2.2 completion while the evaluator profile is development-only.
