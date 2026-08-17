# 分层领域包组合实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将领域包从单一窄场景 JSON 扩展为通用基础包、行业包、工程学科包和场景组合包，并让项目按组合配置加载可追溯的领域指导。

**Architecture:** 保留现有声明式 MBSE domain-pack JSON 和 `mbse_domain_packs.py` 加载器，新增一个纯函数式组合层负责规范化选择、递归展开 `extends`、合并覆盖字段、去重稳定实体并计算组合哈希。工作台保存 `base_pack_id`、`industry_pack_ids`、`discipline_pack_ids`、`overlay_pack_ids`，缺省始终使用 `common-v1`。

**Tech Stack:** Python 3.11+, JSON Schema, pytest, FastAPI/Jinja2, SQLite workbench JSON。

## Global Constraints

- `common-v1` 是所有项目的默认基础包；没有行业或学科覆盖时也必须产生可用的通用分析骨架。
- 首批行业包覆盖 `medical-v1`、`aviation-v1`、`automotive-v1`、`industrial-v1`、`energy-infrastructure-v1`、`software-data-v1`。
- 首批工程学科包覆盖 `mechanical-v1`、`electrical-v1`、`software-v1`、`control-v1`、`thermal-v1`、`safety-v1`、`manufacturing-v1`。
- 组合包不得覆盖核心身份、状态、来源、哈希和审计字段；父包内容必须可追溯。
- 不删除旧的 `urban-medical-aam-v1` 读取和 CLI/API 兼容入口。
- 不新增第三方运行时依赖；使用现有 JSON Schema 校验和 canonical hash。
- 所有新 ID、数组排序和组合哈希必须确定性稳定。

---

### Task 1: 定义组合配置和纯函数组合器

**Files:**
- Create: `src/rflp_lite/application/intelligence/pack_composition.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_config.py`
- Test: `tests/application/intelligence/test_pack_composition.py`
- Modify: `tests/application/intelligence/test_analysis_config.py`

**Interfaces:**
- Consumes: `load_mbse_domain_pack`, `canonical_hash`, existing `normalize_analysis_config` callers。
- Produces:
  - `normalize_pack_selection(value: object) -> dict[str, object]`
  - `compose_pack_selection(selection: dict[str, object]) -> dict[str, object]`
  - `pack_selection_hash(selection: dict[str, object]) -> str`

- [ ] **Step 1: Write failing tests**

```python
def test_missing_selection_defaults_to_common_pack():
    assert normalize_pack_selection(None) == {
        "base_pack_id": "common-v1",
        "industry_pack_ids": [],
        "discipline_pack_ids": [],
        "overlay_pack_ids": [],
    }

def test_composition_deduplicates_and_preserves_pack_order():
    result = compose_pack_selection({
        "base_pack_id": "common-v1",
        "industry_pack_ids": ["medical-v1", "aviation-v1"],
        "discipline_pack_ids": ["mechanical-v1", "electrical-v1"],
        "overlay_pack_ids": ["urban-medical-aam-v1"],
    })
    assert result["pack_ids"] == [
        "common-v1", "medical-v1", "aviation-v1",
        "mechanical-v1", "electrical-v1", "urban-medical-aam-v1",
    ]
    assert result["pack_hash"]

def test_selection_rejects_duplicate_ids_across_categories():
    with pytest.raises(ContractViolation, match="重复"):
        normalize_pack_selection({
            "industry_pack_ids": ["medical-v1"],
            "overlay_pack_ids": ["medical-v1"],
        })
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/intelligence/test_pack_composition.py tests/application/intelligence/test_analysis_config.py`

Expected: FAIL because the four-list selection contract and composition functions do not exist.

- [ ] **Step 3: Implement the normalized selection**

Use this contract in `analysis_config.py`:

```python
DEFAULT_ANALYSIS_CONFIG = {
    "base_pack_id": "common-v1",
    "industry_pack_ids": [],
    "discipline_pack_ids": [],
    "overlay_pack_ids": [],
    "provenance": {"source": "default", "reason": "common-mbse-pack"},
}
```

Normalize each list to unique strings, reject path traversal, reject duplicate IDs across lists, and validate that every ID is present in the packaged domain-pack directory.

- [ ] **Step 4: Implement deterministic composition**

`compose_pack_selection` must load packs in base → industry → discipline → overlay order, merge only declared extension fields, collect `pack_ids`, `pack_hashes`, `stakeholder_lenses`, `lifecycle_phases`, `scenario_dimensions`, `coverage_rules`, and `prompt_fragments`, and sort merged items by `(id, source_pack_id)`.

- [ ] **Step 5: Run the focused tests and verify pass**

Run: `./.venv/bin/python -m pytest -q tests/application/intelligence/test_pack_composition.py tests/application/intelligence/test_analysis_config.py`

Expected: PASS, including existing legacy tests updated to assert `base_pack_id == "common-v1"`.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/intelligence/pack_composition.py src/rflp_lite/application/intelligence/analysis_config.py tests/application/intelligence/test_pack_composition.py tests/application/intelligence/test_analysis_config.py
git commit -m "feat: add layered domain pack selection"
```

### Task 2: Extend the pack schema and loader for inheritance

**Files:**
- Modify: `schemas/mbse-domain-pack.schema.json`
- Modify: `src/rflp_lite/application/mbse_domain_packs.py`
- Test: `tests/application/test_mbse_domain_packs.py`
- Create: `tests/application/intelligence/test_pack_loader_composition.py`

**Interfaces:**
- Consumes: `PackSelection` normalized output from Task 1.
- Produces: `load_composed_pack(selection: dict[str, object]) -> dict[str, object]` with `pack_ids`, `pack_hashes`, `sources`, and merged guidance.

- [ ] **Step 1: Add failing inheritance tests**

Test that `extends` and `disciplines` are accepted, cycles are rejected, an unknown parent is rejected, and a composed pack records source IDs for each merged lens/rule.

- [ ] **Step 2: Run tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/test_mbse_domain_packs.py tests/application/intelligence/test_pack_loader_composition.py`

Expected: FAIL on the new inheritance and source-tracking assertions.

- [ ] **Step 3: Update the JSON Schema**

Add optional fields:

```json
"extends": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
"disciplines": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
"activation_terms": {"type": "array", "items": {"type": "string"}, "uniqueItems": true},
"mappings": {"type": "array", "items": {"type": "object"}}
```

Keep `core_overrides` forbidden.

- [ ] **Step 4: Implement cycle-safe recursive loading**

Add a private loader with `ancestors: tuple[str, ...]`; raise `ContractViolation` with the full cycle path on repetition. For each inherited pack, preserve `source_pack_id` on merged entries. Merge dictionaries recursively only for `prompt_fragments`; concatenate and stable-deduplicate declarative arrays.

- [ ] **Step 5: Run loader tests**

Run: `./.venv/bin/python -m pytest -q tests/application/test_mbse_domain_packs.py tests/application/intelligence/test_pack_loader_composition.py`

Expected: PASS with the existing `urban-medical-aam-v1` legacy pack unchanged.

- [ ] **Step 6: Commit**

```bash
git add schemas/mbse-domain-pack.schema.json src/rflp_lite/application/mbse_domain_packs.py tests/application/test_mbse_domain_packs.py tests/application/intelligence/test_pack_loader_composition.py
git commit -m "feat: compose domain packs with inheritance"
```

### Task 3: Add broad industry and discipline pack resources

**Files:**
- Create: `src/rflp_lite/resources/domain-packs/medical-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/aviation-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/automotive-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/industrial-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/energy-infrastructure-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/software-data-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/mechanical-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/electrical-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/software-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/control-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/thermal-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/safety-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/manufacturing-v1.json`
- Modify: `src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json`
- Test: `tests/application/intelligence/test_pack_catalog.py`

**Interfaces:**
- Consumes: `common-v1.json` field vocabulary and the existing medical pack as the reference shape.
- Produces: validated broad packs with reusable lenses, lifecycle phases, scenario dimensions, coverage rules, prompt fragments, and no project-specific final model.

- [ ] **Step 1: Write catalog tests**

```python
EXPECTED_PACKS = {
    "medical-v1", "aviation-v1", "automotive-v1", "industrial-v1",
    "energy-infrastructure-v1", "software-data-v1", "mechanical-v1",
    "electrical-v1", "software-v1", "control-v1", "thermal-v1",
    "safety-v1", "manufacturing-v1",
}

def test_broad_pack_catalog_is_available():
    packs = set(list_domain_packs())
    assert EXPECTED_PACKS <= packs

def test_each_broad_pack_has_reusable_coverage_contract():
    for pack_id in EXPECTED_PACKS:
        pack = load_domain_pack(pack_id)
        assert pack["stakeholder_lenses"]
        assert pack["coverage_rules"]
        assert pack["prompt_fragments"]
```

- [ ] **Step 2: Run the catalog tests and verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/intelligence/test_pack_catalog.py`

Expected: FAIL because the new pack files are absent.

- [ ] **Step 3: Create the broad pack resources**

Each pack must use the existing schema, declare `version: 1`, `core_overrides: []`, at least five stable lenses, lifecycle/scenario coverage, and prompt fragments that tell the model what to inspect without hardcoding a project result. Use `producer=domain-pack` only when the bridge materializes a seed into a workbench.

- [ ] **Step 4: Convert the medical AAM file into a thin composition overlay**

Move reusable medical actors and flight concepts into the new parent packs. Keep only AAM-specific mappings, flight/medical handoff phases, airspace and mission dimensions, and set:

```json
{
  "extends": ["medical-v1", "aviation-v1"],
  "disciplines": ["mechanical-v1", "electrical-v1", "control-v1", "safety-v1"]
}
```

Preserve the old IDs and `urban-medical-aam-v1` CLI behavior.

- [ ] **Step 5: Validate every resource and run tests**

Run: `./.venv/bin/python -m pytest -q tests/application/intelligence/test_pack_catalog.py tests/application/test_mbse_domain_packs.py tests/e2e/test_intelligent_discovery.py`

Expected: PASS and no existing discovery fixture changes except source-pack metadata.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/resources/domain-packs schemas/mbse-domain-pack.schema.json tests/application/intelligence/test_pack_catalog.py
git commit -m "feat: add broad industry and discipline packs"
```

### Task 4: Migrate workbench configuration and expose pack selection

**Files:**
- Modify: `src/rflp_lite/application/workbench_schema.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Test: `tests/application/test_workbench_schema.py`
- Modify: `tests/application/intelligence/test_analysis_config.py`
- Test: `tests/interface/web/test_analysis_config.py`

**Interfaces:**
- Consumes: `normalize_pack_selection` and `compose_pack_selection` from Task 1.
- Produces: API config fields `base_pack_id`, `industry_pack_ids`, `discipline_pack_ids`, `overlay_pack_ids`; UI controls with common-v1 selected by default.

- [ ] **Step 1: Add migration tests**

Assert that a missing or legacy `domain_pack_id` workbench gets `base_pack_id="common-v1"`; legacy `domain_pack_id="urban-medical-aam-v1"` becomes an overlay selection and does not silently become the base pack.

- [ ] **Step 2: Run migration tests to verify failure**

Run: `./.venv/bin/python -m pytest -q tests/application/test_workbench_schema.py tests/application/intelligence/test_analysis_config.py tests/interface/web/test_analysis_config.py`

Expected: FAIL on the new four-list fields.

- [ ] **Step 3: Implement migration and facade APIs**

Update `empty_workbench`, `_V2_DEFAULTS`, `analysis_config`, `save_analysis_config`, and `_project_analysis_config` to call `compose_pack_selection`. Keep a compatibility response field `domain_pack_id` only for clients that send or read it.

- [ ] **Step 4: Add the UI controls**

In `requirements-input.html`, add grouped multi-select controls for industry, discipline, and scenario overlays. Submit the config through the existing API before a new analysis request; show the resolved pack IDs and versions in the result summary.

- [ ] **Step 5: Run Web tests**

Run: `./.venv/bin/python -m pytest -q tests/application/test_workbench_schema.py tests/application/intelligence/test_analysis_config.py tests/interface/web/test_analysis_config.py tests/interface/web/test_auto_requirements.py`

Expected: PASS with common-v1 present in every new workbench.

- [ ] **Step 6: Commit**

```bash
git add src/rflp_lite/application/workbench_schema.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/templates/requirements-input.html tests/application/test_workbench_schema.py tests/application/intelligence/test_analysis_config.py tests/interface/web/test_analysis_config.py tests/interface/web/test_auto_requirements.py
git commit -m "feat: configure industry and discipline pack composition"
```

