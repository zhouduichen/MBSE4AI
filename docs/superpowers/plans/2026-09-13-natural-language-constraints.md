# 自然语言工程约束抽取实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans (recommended). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将自然语言中的显式工程约束转换为可追溯 canonical Requirement 数据，并使其沿 R→F→L→P 进入 Methodology 可行性分析。

**Architecture:** 在已有 `requirement_intake.py` 中增加纯函数 `extract_requirement_constraints`，只匹配受限指标、比较符、数值和单位并保存 provenance。ProjectService 和 ModelGenerationService 的新 Requirement 入口共享该函数；Physical fallback 继续消费 Requirement→Function→Logical 关系，并把 constraints/provenance 复制到物理候选。Methodology Engine 增加 `endurance_h` 可测量字段，仍区分数值冲突和 `needs_measurement`。

**Tech Stack:** Python 3.11+, `re`, typed ModelGraph, existing ProjectService/ModelGenerationService, MethodologyEngine, VerticalRuleRuntime, pytest.

## Global Constraints

- 只提取显式出现的指标、比较方向、数值和可识别单位；裸数字、普通编号、日期、小数/版本号不产生约束。
- 支持功耗、质量/重量、时延/延迟/响应时间、带宽、成本和续航/持续运行时间。
- 支持 `不超过/不大于/不高于/最多/≤/<=/<` 与 `不少于/不小于/不低于/至少/≥/>=`；输出 operator 只能是 `max` 或 `min`。
- canonical 单位为 W、kg、ms、Mbps、原成本值和 h；单位换算使用确定性因子。
- 同一指标同一方向的重复约束取最严格值；上下界同时存在时保留两者，冲突交给 Methodology/Controller。
- 已有显式 `constraints`、`limits` 和 provenance 不被输入 enrichment 覆盖；解析失败不阻塞 Requirement 创建。
- 不填充 Physical 实测值、不宣称可行、不绕过 Review/CAS/Compiler/Validator。
- 旧多需求、SysML、交付包、Controller iteration 和 23-task 兼容行为保持通过。

---

### Task 1: Add the canonical constraint parser

**Files:**
- Modify: `src/rflp_lite/application/requirement_intake.py`
- Test: `tests/application/test_requirement_intake.py`

**Interfaces:**
- Consumes: arbitrary `statement: str`.
- Produces: `extract_requirement_constraints(statement: str) -> Mapping[str, object]` with optional `constraints` mapping and `constraint_provenance` list.

- [ ] **Step 1: Write failing parser tests**

Add:

```python
from rflp_lite.application.requirement_intake import extract_requirement_constraints


def test_extracts_compound_chinese_constraints_and_normalizes_units():
    result = extract_requirement_constraints(
        "系统功耗不超过 50 W，质量不大于 2 kg，续航不少于 10 h"
    )

    assert result["constraints"] == {
        "max_power_w": 50.0,
        "max_mass_kg": 2.0,
        "min_endurance_h": 10.0,
    }
    assert [item["field"] for item in result["constraint_provenance"]] == [
        "power_w", "mass_kg", "endurance_h",
    ]


def test_extracts_english_comparators_and_converts_units():
    result = extract_requirement_constraints(
        "Power <= 0.5 kW; latency must be at most 2 s; bandwidth >= 1 Gbps"
    )

    assert result["constraints"] == {
        "max_power_w": 500.0,
        "max_latency_ms": 2000.0,
        "min_bandwidth_mbps": 1000.0,
    }


def test_keeps_strictest_duplicate_bound_and_preserves_both_directions():
    result = extract_requirement_constraints(
        "功耗不超过 80 W，功耗不超过 50 W，功耗不少于 10 W"
    )

    assert result["constraints"] == {
        "max_power_w": 50.0,
        "min_power_w": 10.0,
    }
    assert len(result["constraint_provenance"]) == 2


def test_does_not_infer_from_bare_numbers_or_version_text():
    assert extract_requirement_constraints("系统版本 2.0，支持 3 个用户") == {}
    assert extract_requirement_constraints("系统续航 10 小时") == {}
```

- [ ] **Step 2: Run parser tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/test_requirement_intake.py -q`

Expected: FAIL during collection because `extract_requirement_constraints` is not defined.

- [ ] **Step 3: Implement the restricted parser**

Add the following shape to `requirement_intake.py`:

```python
from collections.abc import Mapping

_NUMBER = r"(?P<value>\d+(?:\.\d+)?)"
_OPERATORS = r"(?P<operator>不超过|不大于|不高于|最多|小于等于|不少于|不小于|不低于|至少|大于等于|<=|>=|≤|≥|<|>)"
_METRICS = (
    ("power_w", ("功耗", "power", "power consumption"), (("kw", 1000.0), ("千瓦", 1000.0), ("w", 1.0), ("瓦", 1.0))),
    ("mass_kg", ("质量", "重量", "mass", "weight"), (("kg", 1.0), ("千克", 1.0), ("公斤", 1.0), ("g", 0.001), ("克", 0.001))),
    ("latency_ms", ("时延", "延迟", "响应时间", "latency", "response time"), (("ms", 1.0), ("毫秒", 1.0), ("s", 1000.0), ("秒", 1000.0))),
    ("bandwidth_mbps", ("带宽", "bandwidth"), (("gbps", 1000.0), ("gb/s", 1000.0), ("兆比特/秒", 1.0), ("mbps", 1.0))),
    ("cost", ("成本", "费用", "cost"), (("元", 1.0), ("人民币", 1.0), ("cny", 1.0), ("¥", 1.0), ("￥", 1.0))),
    ("endurance_h", ("续航", "持续运行时间", "运行时间", "endurance", "runtime", "operating time"), (("小时", 1.0), ("hour", 1.0), ("hours", 1.0), ("h", 1.0), ("分钟", 1 / 60.0), ("minute", 1 / 60.0), ("minutes", 1 / 60.0), ("min", 1 / 60.0))),
)


def extract_requirement_constraints(statement: str) -> Mapping[str, object]:
    candidates = []
    text = str(statement or "")
    for field, aliases, units in _METRICS:
        alias_pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
        unit_pattern = "|".join(re.escape(unit) for unit, _ in sorted(units, key=lambda item: len(item[0]), reverse=True))
        pattern = re.compile(
            rf"(?P<metric>{alias_pattern})\s*{_OPERATORS}\s*{_NUMBER}\s*(?P<unit>{unit_pattern})",
            re.IGNORECASE,
        )
        factors = {unit.lower(): factor for unit, factor in units}
        for match in pattern.finditer(text):
            operator = match.group("operator")
            direction = "max" if operator in {"不超过", "不大于", "不高于", "最多", "小于等于", "<=", "≤", "<"} else "min"
            unit = match.group("unit")
            value = float(match.group("value")) * factors[unit.lower()]
            candidates.append({
                "key": f"{direction}_{field}",
                "field": field,
                "operator": direction,
                "value": value,
                "unit": unit,
                "text": match.group(0),
            })
    selected = {}
    for candidate in candidates:
        current = selected.get(candidate["key"])
        if current is None or (
            candidate["operator"] == "max" and candidate["value"] < current["value"]
        ) or (
            candidate["operator"] == "min" and candidate["value"] > current["value"]
        ):
            selected[candidate["key"]] = candidate
    if not selected:
        return {}
    ordered = tuple(selected[key] for key in sorted(selected))
    return {
        "constraints": {item["key"]: item["value"] for item in ordered},
        "constraint_provenance": [
            {key: item[key] for key in ("field", "operator", "value", "unit", "text")}
            for item in ordered
        ],
    }
```

The implementation must make the cost unit optional only if the metric and comparator are explicit; all other metrics require a recognized unit. It must preserve the first selected provenance for equal duplicate values and return a deterministic key order.

- [ ] **Step 4: Run parser tests and lint**

Run: `./.venv/bin/pytest tests/application/test_requirement_intake.py -q` and `./.venv/bin/ruff check src/rflp_lite/application/requirement_intake.py tests/application/test_requirement_intake.py`

Expected: PASS.

- [ ] **Step 5: Commit the parser**

```bash
git add src/rflp_lite/application/requirement_intake.py tests/application/test_requirement_intake.py
git commit -m "feat: parse explicit engineering constraints"
```

### Task 2: Enrich both Requirement creation paths

**Files:**
- Modify: `src/rflp_lite/application/project_service.py:87-116`
- Modify: `src/rflp_lite/application/model_generation.py:790-845`
- Test: `tests/application/test_project_service.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: `extract_requirement_constraints(clean_statement)`.
- Produces: newly created Requirement payloads with the parser's `constraints` and `constraint_provenance`, while preserving existing fields and source IDs.

- [ ] **Step 1: Write failing application tests**

Add:

```python
def test_manual_requirement_entry_stores_structured_constraints(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.projects.add_requirement("robot", "系统功耗不超过 2 kW")

    assert result["requirement"]["payload"]["constraints"] == {"max_power_w": 2000.0}
    assert result["requirement"]["payload"]["constraint_provenance"][0]["unit"] == "kW"


def test_natural_language_generation_stores_constraint_provenance(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    services.generation("robot").generate(
        "robot", requirement_text="系统功耗不超过 50 W 且续航不少于 10 h"
    )
    requirement = next(
        item for item in services.model("robot").graph("robot").entities
        if item.kind is EntityKind.REQUIREMENT
    )

    assert requirement.payload["constraints"] == {
        "max_power_w": 50.0,
        "min_endurance_h": 10.0,
    }
    assert len(requirement.payload["constraint_provenance"]) == 2
```

- [ ] **Step 2: Run application tests and verify they fail**

Run: `./.venv/bin/pytest tests/application/test_project_service.py tests/application/test_model_generation.py -q -k constraint`

Expected: FAIL because the two creation paths do not call the parser.

- [ ] **Step 3: Integrate the shared parser without overwriting explicit fields**

Import `extract_requirement_constraints` in both application modules. In `ProjectService.add_requirement`, build the existing payload first and update it with the helper result. In `ModelGenerationService._ensure_input`, build the existing payload containing `statement`, `source`, `level`, `type`, `obligation` and `verification_method`, then update it with the helper result before passing it to `make_entity`. Do not update an existing Requirement merely because a later input statement parses differently.

- [ ] **Step 4: Run the application tests**

Run: `./.venv/bin/pytest tests/application/test_project_service.py tests/application/test_model_generation.py -q -k constraint`

Expected: PASS.

- [ ] **Step 5: Commit Requirement enrichment**

```bash
git add src/rflp_lite/application/project_service.py src/rflp_lite/application/model_generation.py tests/application/test_project_service.py tests/application/test_model_generation.py
git commit -m "feat: enrich requirements with parsed constraints"
```

### Task 3: Propagate endurance and provenance into physical analysis

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py:623-680`
- Modify: `src/rflp_lite/methodology/engine.py:15-19`
- Modify: `src/rflp_lite/resources/prompts/vertical/physical.v1.md`
- Test: `tests/methodology/test_engine.py`
- Test: `tests/e2e/test_vertical_model_generation.py`

**Interfaces:**
- Consumes: Requirement payload `constraints` and `constraint_provenance` reached through existing Requirement→Function→Logical relations.
- Produces: Physical payload `propagated_constraints`, `propagated_constraint_provenance`, `source_requirement_ids`, and `endurance_h`; Methodology compares `min_endurance_h` to `endurance_h`.

- [ ] **Step 1: Write failing physical and Methodology tests**

Add to `tests/methodology/test_engine.py`:

```python
def test_physical_analysis_detects_endurance_constraint_conflict():
    graph = _graph()
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)
    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    physical = make_entity(
        EntityKind.PHYSICAL_BLOCK,
        physical.meta.name,
        {**physical.payload, "endurance_h": 8},
        status=physical.meta.status,
    )
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        requirement.meta.name,
        {**requirement.payload, "constraints": {"min_endurance_h": 10}},
        status=requirement.meta.status,
    )
    graph = ModelGraph(
        graph.project_id,
        (requirement, *[item for item in graph.entities if item.id not in {physical.id, requirement.id}], physical),
        graph.relations,
        graph.revision,
    )

    report = MethodologyEngine().analyze(graph)

    assert any(item.code == "physical_constraint_conflict" for item in report.findings)
```

Add to `tests/e2e/test_vertical_model_generation.py`:

```python
def test_natural_language_constraints_reach_physical_candidate(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    services.generation("robot").generate(
        "robot", requirement_text="系统功耗不超过 50 W 且续航不少于 10 h"
    )
    graph = services.model("robot").graph("robot")
    physical = next(item for item in graph.entities if item.kind is EntityKind.PHYSICAL_BLOCK)

    assert physical.payload["propagated_constraints"] == {
        "max_power_w": 50.0,
        "min_endurance_h": 10.0,
    }
    assert physical.payload["source_requirement_ids"]
    assert physical.payload["endurance_h"] is None
    assert physical.payload["propagated_constraint_provenance"]
```

- [ ] **Step 2: Run the physical tests and verify they fail**

Run: `./.venv/bin/pytest tests/methodology/test_engine.py tests/e2e/test_vertical_model_generation.py -q -k 'endurance or natural_language_constraints'`

Expected: FAIL because `endurance_h` and physical provenance propagation do not exist.

- [ ] **Step 3: Add endurance as a measurable Physical field and propagate provenance**

Append `endurance_h` to `_PHYSICAL_FIELDS` in `methodology/engine.py`. Add `endurance_h: None` and `propagated_constraint_provenance: []` to the fallback `_physical_payload`. Collect each Requirement's list-valued `constraint_provenance` in deterministic Requirement-ID order. Keep existing `propagated_constraints` merge semantics and all unknown values unchanged.

Update `physical.v1.md` to mention `endurance_h` when a requirement contains endurance/runtime constraints and require the LLM to preserve constraint provenance where available.

- [ ] **Step 4: Run focused physical tests**

Run: `./.venv/bin/pytest tests/methodology/test_engine.py tests/e2e/test_vertical_model_generation.py -q -k 'endurance or natural_language_constraints'`

Expected: PASS.

- [ ] **Step 5: Commit Physical propagation**

```bash
git add src/rflp_lite/runtime/rule_based.py src/rflp_lite/methodology/engine.py src/rflp_lite/resources/prompts/vertical/physical.v1.md tests/methodology/test_engine.py tests/e2e/test_vertical_model_generation.py
git commit -m "feat: propagate constraints into physical analysis"
```

### Task 4: Document, verify, and push the constraint-aware product path

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/plans/2026-09-13-natural-language-constraints.md`

**Interfaces:**
- Consumes: parser, enriched Requirement, Physical propagation and Methodology behavior from Tasks 1–3.
- Produces: documented input-to-feasibility path and a verified pushed branch.

- [ ] **Step 1: Document constraint-aware generation**

State that explicit natural-language constraints are normalized at input, preserve provenance, flow through the RFLP graph, and remain measurable/Reviewable rather than being treated as automatic feasibility.

- [ ] **Step 2: Mark this plan complete and scan it**

Change implementation checkboxes to `[x]`. Run:

```bash
rg -n 'TODO|TBD|FIXME|Similar to Task|add appropriate' docs/superpowers/plans/2026-09-13-natural-language-constraints.md | rg -v 'rg -n'
```

Expected: no output.

- [ ] **Step 3: Run complete verification**

Run:

```bash
./.venv/bin/pytest -q
./.venv/bin/python scripts/verify_full.py
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/lint-imports
./.venv/bin/python scripts/architecture_metrics.py
git diff --check
```

Expected: every command exits 0, including the existing architecture budget.

- [ ] **Step 4: Commit and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/README.md docs/superpowers/plans/2026-09-13-natural-language-constraints.md
git commit -m "docs: record natural language constraint path"
git push origin codex/web-audit-2026-08-18
```
