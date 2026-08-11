# AI4MBSE Intelligent Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 RFLP-Lite 中增加一条从一句话或零散需求出发、可审核地补全利益相关方/场景/能力/需求/架构，并从统一语义图生成确定性 MBSE 图的低耦合链路。

**Architecture:** 保留现有 Workspace、SQLite、审核、追溯、RFLP 和 Web/CLI 底座。新增稳定候选信封、声明式 MBSE 领域包、分阶段智能发现流水线、覆盖审计、审核桥接和与渲染器无关的 `DiagramSpec`；应用层只依赖端口和领域对象，OpenAI-compatible 模型及 SVG 渲染器位于适配器层。

**Tech Stack:** Python 3.11+、标准库 dataclasses/json/hashlib/urllib、现有 FastAPI/Jinja2/SQLite、可选 jsonschema、pytest/Hypothesis/Import Linter、确定性 SVG。

## Global Constraints

- 继续复用当前仓库，不新建重复项目。
- 不继续扩大 `requirements_workbench.py`、`web_facade.py` 和 `routes.py` 的职责；新业务逻辑进入独立文件。
- 不新增强制运行时依赖；JSON Schema 校验沿用 `.[schema]` 可选依赖。
- 不引入微服务、消息队列、前端构建链、通用工作流引擎或向量数据库。
- 核心字段稳定；领域字段、场景维度、覆盖规则和图形分组由版本化领域包声明。
- 大模型只产生 `candidate`、`assumed`、`unknown` 和澄清问题；不能批准需求、场景、架构或 Baseline。
- 图形只能读取已接受语义元素；所有图都由同一语义图构建，禁止各图独立调用大模型。
- 默认本地部署；API Key 不得进入页面、数据库、日志、运行清单或导出文件。
- 相同已接受模型、领域包版本、主题版本和布局参数必须生成字节稳定的 SVG。
- 现有 v2 工作区、RFLP、MBSE、场景、SysML-lite 和 SVG 行为必须保持兼容。
- 当前工作区已有未提交用户改动；执行时必须使用隔离 worktree，且不得带入或覆盖主工作区的未提交文件。

## File Map

| Area | Files | Responsibility |
|---|---|---|
| Domain | `domain/discovery.py`, `domain/diagram_spec.py` | 稳定候选信封、来源、覆盖状态和渲染无关图形契约 |
| Ports | `ports/generative_model.py`, `ports/diagram_renderer.py` | 可替换大模型与图形渲染接口 |
| Pack | `application/mbse_domain_packs.py`, `schemas/mbse-domain-pack.schema.json`, `resources/domain-packs/*.json` | 领域包加载、校验、版本和城市医疗飞行汽车知识框架 |
| Intelligence | `application/intelligence/*.py` | 输入、扩展、规范化、覆盖、审核、桥接与门面 |
| Diagrams | `application/diagrams/*.py` | 从已接受语义图构建 `DiagramSpec` 并调用渲染端口 |
| Adapters | `adapters/openai_compatible_model.py`, `adapters/deterministic_svg_renderer.py` | OpenAI-compatible JSON 调用与 SVG 实现 |
| Interface | `interface/web/discovery_routes.py`, `interface/web/discovery_api.py`, `interface/web/templates/requirements-discovery.html`, `interface/cli.py` | 薄 Web/API/CLI 入口 |
| Migration | `application/workbench_schema.py` | v2→v3 无损迁移和 discovery 默认状态 |
| Verification | `tests/domain`, `tests/application`, `tests/adapters`, `tests/interface`, `tests/e2e` | 分层契约、回归和城市医疗飞行汽车验收 |

## Execution Preflight

- [ ] Use the required execution sub-skill to create an isolated worktree on branch `codex/intelligent-mbse-discovery`; do not execute this plan in the dirty main worktree.
- [ ] Install the editable development environment in that worktree:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,schema,web]'
```

- [ ] Verify the approved design commit and baseline gates before changing code:

```bash
git show --stat --oneline 5fa4a5c
.venv/bin/python -m pytest tests/application/test_workbench_schema.py tests/application/test_mbse_modeling.py tests/application/test_requirements_flow.py -v
.venv/bin/lint-imports
```

Expected: commit `5fa4a5c` is present; selected tests and current import contracts pass. If the clean worktree baseline fails, record the failure and stop before Task 1.

---

## Increment 1 — Semantic Core and Domain Pack

### Task 1: Add immutable candidate and provenance contracts

**Files:**
- Create: `src/rflp_lite/domain/discovery.py`
- Create: `tests/domain/test_discovery.py`

**Interfaces:**
- Consumes: `canonical_hash(value: Any) -> str`, `canonical_json(value: Any) -> str`.
- Produces: `ProvenanceRef`, `CandidateEnvelope.create`, `CandidateEnvelope.as_dict` and constants `SOURCE_TYPES`, `REVIEW_STATUSES`, `COVERAGE_STATUSES`.

- [ ] **Step 1: Write the failing domain tests**

```python
from dataclasses import FrozenInstanceError

import pytest

from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef


def test_candidate_identity_is_deterministic_and_source_aware():
    source = ProvenanceRef("explicit", "region-1", "用户原文")
    first = CandidateEnvelope.create(
        element_type="stakeholder",
        pack_id="urban-medical-aam-v1",
        payload={"name": "急救医生", "category": "medical_staff"},
        provenance=(source,),
        producer="rule",
    )
    second = CandidateEnvelope.create(
        element_type="stakeholder",
        pack_id="urban-medical-aam-v1",
        payload={"category": "medical_staff", "name": "急救医生"},
        provenance=(source,),
        producer="rule",
    )
    assert first == second
    assert first.id.startswith("candidate-")
    assert first.as_dict()["payload"]["name"] == "急救医生"


def test_candidate_rejects_unknown_source_and_is_immutable():
    with pytest.raises(ValueError, match="source_type"):
        ProvenanceRef("guess", "region-1")
    item = CandidateEnvelope.create(
        element_type="mission",
        pack_id="urban-medical-aam-v1",
        payload={"name": "城市医疗运输"},
        provenance=(ProvenanceRef("inferred", "lens-mission"),),
        producer="llm",
    )
    with pytest.raises(FrozenInstanceError):
        item.status = "accepted"


def test_candidate_confidence_is_bounded():
    with pytest.raises(ValueError, match="confidence"):
        CandidateEnvelope.create(
            element_type="risk",
            pack_id="urban-medical-aam-v1",
            payload={"name": "低能见度"},
            provenance=(ProvenanceRef("inferred", "lens-risk"),),
            producer="llm",
            confidence=1.2,
        )
```

- [ ] **Step 2: Run the tests and verify the contract is absent**

Run: `.venv/bin/python -m pytest tests/domain/test_discovery.py -v`

Expected: collection fails with `ModuleNotFoundError: No module named 'rflp_lite.domain.discovery'`.

- [ ] **Step 3: Implement the immutable contracts**

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json


SOURCE_TYPES = frozenset({"explicit", "derived", "inferred", "assumed", "external_reference"})
REVIEW_STATUSES = frozenset({"candidate", "accepted", "rejected", "stale"})
COVERAGE_STATUSES = frozenset({"covered", "candidate", "unknown", "not_applicable"})


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    source_type: str
    source_id: str
    rationale: str = ""

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError("invalid source_type")
        if not self.source_id.strip():
            raise ValueError("source_id is required")


@dataclass(frozen=True, slots=True)
class CandidateEnvelope:
    id: str
    element_type: str
    schema_version: int
    pack_id: str
    status: str
    payload_json: str
    provenance: tuple[ProvenanceRef, ...]
    assumptions: tuple[str, ...]
    confidence: float
    producer: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        element_type: str,
        pack_id: str,
        payload: Mapping[str, object],
        provenance: tuple[ProvenanceRef, ...],
        producer: str,
        assumptions: tuple[str, ...] = (),
        confidence: float = 1.0,
        schema_version: int = 1,
        status: str = "candidate",
    ) -> "CandidateEnvelope":
        if not element_type.strip() or not pack_id.strip() or not producer.strip():
            raise ValueError("element_type, pack_id and producer are required")
        if not provenance:
            raise ValueError("provenance is required")
        if status not in REVIEW_STATUSES:
            raise ValueError("invalid status")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        normalized_payload = json.loads(canonical_json(dict(payload)))
        content_hash = canonical_hash((element_type, normalized_payload))
        identity = (
            pack_id,
            element_type,
            normalized_payload,
            tuple((item.source_type, item.source_id) for item in provenance),
        )
        return cls(
            id=f"candidate-{canonical_hash(identity)[:16]}",
            element_type=element_type,
            schema_version=int(schema_version),
            pack_id=pack_id,
            status=status,
            payload_json=canonical_json(normalized_payload),
            provenance=provenance,
            assumptions=tuple(str(item) for item in assumptions),
            confidence=float(confidence),
            producer=producer,
            content_hash=content_hash,
        )

    @property
    def payload(self) -> dict[str, object]:
        return json.loads(self.payload_json)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "element_type": self.element_type,
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "status": self.status,
            "payload": self.payload,
            "provenance": [
                {
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "rationale": item.rationale,
                }
                for item in self.provenance
            ],
            "assumptions": list(self.assumptions),
            "confidence": self.confidence,
            "producer": self.producer,
            "content_hash": self.content_hash,
        }
```

- [ ] **Step 4: Run the domain tests**

Run: `.venv/bin/python -m pytest tests/domain/test_discovery.py -v`

Expected: `3 passed`.

- [ ] **Step 5: Commit the semantic core**

```bash
git add src/rflp_lite/domain/discovery.py tests/domain/test_discovery.py
git commit -m "feat: add discovery candidate contracts"
```

### Task 2: Add versioned MBSE domain-pack validation and the urban medical AAM pack

**Files:**
- Create: `schemas/mbse-domain-pack.schema.json`
- Create: `src/rflp_lite/resources/schemas/mbse-domain-pack.schema.json`
- Create: `src/rflp_lite/resources/domain-packs/mbse-common-v1.json`
- Create: `src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json`
- Create: `src/rflp_lite/application/mbse_domain_packs.py`
- Create: `tests/application/test_mbse_domain_packs.py`

**Interfaces:**
- Consumes: `resource_path(relative: str) -> Path`, `validate_json(instance, schema_path)`.
- Produces: `load_mbse_domain_pack(path: Path) -> dict[str, object]`, `validate_candidate_payload(pack, element_type, payload) -> dict[str, object]`, `mbse_domain_pack_hash(pack) -> str`.

- [ ] **Step 1: Write failing pack tests**

```python
from pathlib import Path

import pytest

from rflp_lite.application.mbse_domain_packs import (
    load_mbse_domain_pack,
    mbse_domain_pack_hash,
    validate_candidate_payload,
)
from rflp_lite.domain.errors import ContractViolation


PACK = Path("src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json")


def test_urban_medical_pack_declares_required_analysis_lenses():
    pack = load_mbse_domain_pack(PACK)
    common = load_mbse_domain_pack(Path("src/rflp_lite/resources/domain-packs/mbse-common-v1.json"))
    assert pack["id"] == "urban-medical-aam-v1"
    assert pack["element_schemas"] == common["element_schemas"]
    assert {item["id"] for item in pack["stakeholder_lenses"]} >= {
        "medical", "operations", "regulatory", "public_environment"
    }
    assert {item["id"] for item in pack["scenario_dimensions"]} >= {
        "weather", "visibility", "mission_phase", "system_state", "medical_urgency"
    }
    assert mbse_domain_pack_hash(pack) == mbse_domain_pack_hash(load_mbse_domain_pack(PACK))


def test_stakeholder_payload_requires_category_goals_and_interactions():
    pack = load_mbse_domain_pack(PACK)
    accepted = validate_candidate_payload(
        pack,
        "stakeholder",
        {
            "name": "急救医生",
            "category": "medical",
            "goals": ["稳定患者状态"],
            "interactions": ["提交医疗任务"],
        },
    )
    assert accepted["name"] == "急救医生"
    with pytest.raises(ContractViolation, match="stakeholder"):
        validate_candidate_payload(pack, "stakeholder", {"name": "急救医生"})


def test_pack_rejects_executable_or_core_overrides(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(
        '{"id":"bad","version":1,"display_name":"bad","core_overrides":["status"],'
        '"element_schemas":{},"stakeholder_lenses":[],"lifecycle_phases":[],'
        '"scenario_dimensions":[],"coverage_rules":[],"prompt_fragments":{},"diagram_groups":{}}',
        encoding="utf-8",
    )
    with pytest.raises(ContractViolation, match="core_overrides"):
        load_mbse_domain_pack(path)
```

- [ ] **Step 2: Run tests and verify missing modules/resources**

Run: `.venv/bin/python -m pytest tests/application/test_mbse_domain_packs.py -v`

Expected: collection fails because `rflp_lite.application.mbse_domain_packs` does not exist.

- [ ] **Step 3: Create the pack schema and keep source/wheel copies identical**

Create both schema files with the same JSON document. The schema must require these exact top-level keys: `id`, `version`, `display_name`, `element_schemas`, `stakeholder_lenses`, `lifecycle_phases`, `scenario_dimensions`, `coverage_rules`, `prompt_fragments`, `diagram_groups`; set `additionalProperties` to `false`; define each lens/dimension/rule as an object with a required stable `id`; and define `core_overrides` with `maxItems: 0` so any override is rejected.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://rflp-lite.local/schemas/mbse-domain-pack.schema.json",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "id",
    "version",
    "display_name",
    "element_schemas",
    "stakeholder_lenses",
    "lifecycle_phases",
    "scenario_dimensions",
    "coverage_rules",
    "prompt_fragments",
    "diagram_groups"
  ],
  "properties": {
    "id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{0,79}$"},
    "version": {"type": "integer", "minimum": 1},
    "display_name": {"type": "string", "minLength": 1},
    "description": {"type": "string"},
    "core_overrides": {"type": "array", "maxItems": 0},
    "element_schemas": {
      "type": "object",
      "minProperties": 1,
      "additionalProperties": {"type": "object"}
    },
    "stakeholder_lenses": {
      "type": "array",
      "items": {"$ref": "#/$defs/namedItem"}
    },
    "lifecycle_phases": {
      "type": "array",
      "items": {"$ref": "#/$defs/namedItem"}
    },
    "scenario_dimensions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "label", "values"],
        "properties": {
          "id": {"type": "string", "minLength": 1},
          "label": {"type": "string", "minLength": 1},
          "values": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": true
          }
        }
      }
    },
    "coverage_rules": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["id", "source", "priority"],
        "properties": {
          "id": {"type": "string", "minLength": 1},
          "source": {
            "enum": ["stakeholder_lenses", "lifecycle_phases", "scenario_dimensions"]
          },
          "priority": {"enum": ["high", "medium", "low"]}
        }
      }
    },
    "prompt_fragments": {
      "type": "object",
      "additionalProperties": {"type": "string"}
    },
    "diagram_groups": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "required": ["label", "order"],
        "properties": {
          "label": {"type": "string", "minLength": 1},
          "order": {"type": "integer", "minimum": 0}
        }
      }
    }
  },
  "$defs": {
    "namedItem": {
      "type": "object",
      "additionalProperties": false,
      "required": ["id", "label"],
      "properties": {
        "id": {"type": "string", "minLength": 1},
        "label": {"type": "string", "minLength": 1}
      }
    }
  }
}
```

Add this exact parity assertion to the pack test file:

```python
def test_source_and_packaged_schema_are_identical():
    assert Path("schemas/mbse-domain-pack.schema.json").read_bytes() == Path(
        "src/rflp_lite/resources/schemas/mbse-domain-pack.schema.json"
    ).read_bytes()
```

- [ ] **Step 4: Create the common and urban-medical packs**

The common pack provides element schemas for the complete first-version element set. Copy the same `element_schemas` object into the urban-medical pack; the test above prevents the two schema catalogs from drifting:

```json
[
  "mission",
  "system_boundary",
  "stakeholder",
  "concern",
  "need",
  "exchange_flow",
  "lifecycle_phase",
  "transition",
  "use_case",
  "operational_scenario",
  "capability",
  "requirement",
  "function",
  "functional_flow",
  "functional_scenario",
  "logical_component",
  "physical_block",
  "interface",
  "solution_candidate",
  "risk",
  "clarification_question"
]
```

For every element schema use `type: object`, `additionalProperties: true`, and require `name`. Require these additional fields exactly:

```json
{
  "stakeholder": ["category", "goals", "interactions"],
  "exchange_flow": ["source", "target", "flow_type"],
  "operational_scenario": ["actors", "preconditions", "trigger", "steps", "expected_outcomes", "scenario_type"],
  "capability": ["verb", "object"],
  "requirement": ["statement", "requirement_type", "verification_method"],
  "function": ["inputs", "outputs"],
  "logical_component": ["responsibilities"],
  "physical_block": ["realizes"],
  "clarification_question": ["question", "reason"]
}
```

The urban-medical pack must declare these stakeholder lenses:

```json
[
  {"id":"patients_passengers","label":"患者与乘员"},
  {"id":"medical","label":"医疗人员与医疗机构"},
  {"id":"operations","label":"驾驶、调度与运营"},
  {"id":"manufacturing_maintenance","label":"制造、供应与维修"},
  {"id":"vertiport","label":"起降与地面基础设施"},
  {"id":"air_traffic","label":"空中交通与其他空域使用者"},
  {"id":"road_traffic","label":"道路交通与地面公众"},
  {"id":"communications_navigation","label":"通信、导航与气象服务"},
  {"id":"energy","label":"能源与充电服务"},
  {"id":"emergency_response","label":"消防、救援与事故调查"},
  {"id":"regulatory","label":"民航、医疗、交通与地方监管"},
  {"id":"insurance_legal","label":"保险、法律与责任主体"},
  {"id":"cybersecurity_privacy","label":"网络安全与数据隐私"},
  {"id":"public_environment","label":"居民、噪声、生态与环境"}
]
```

It must declare lifecycle phases `concept`, `manufacturing`, `deployment`, `mission_planning`, `takeoff`, `cruise`, `landing`, `charging`, `maintenance`, `emergency`, `retirement`; scenario dimensions `weather`, `visibility`, `time`, `geography`, `mission_phase`, `system_state`, `medical_urgency`, `human_factor`, `external_event`, `lifecycle`; and high-priority coverage rules for every stakeholder lens, lifecycle phase, and scenario dimension. Values must include rain/heavy-rain/fog/thunderstorm/wind/icing, day/night, urban-canyon/mountain/coastal, normal/degraded/emergency, stable/urgent/critical, communication-loss/GNSS-loss/landing-site-unavailable.

- [ ] **Step 5: Implement strict loading and payload validation**

```python
from __future__ import annotations

import json
from pathlib import Path

from rflp_lite.application.resources import resource_path
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.validation import validate_json


PACK_SCHEMA = resource_path("schemas/mbse-domain-pack.schema.json")


def load_mbse_domain_pack(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractViolation(f"invalid MBSE domain pack: {path.name}") from exc
    validate_json(payload, PACK_SCHEMA)
    if payload.get("core_overrides"):
        raise ContractViolation("MBSE domain pack cannot define core_overrides")
    return json.loads(canonical_json(payload))


def mbse_domain_pack_hash(pack: object) -> str:
    return canonical_hash(pack)


def validate_candidate_payload(
    pack: dict[str, object], element_type: str, payload: object
) -> dict[str, object]:
    schemas = pack.get("element_schemas", {})
    if not isinstance(schemas, dict) or element_type not in schemas:
        raise ContractViolation(f"unsupported element type: {element_type}")
    if not isinstance(payload, dict):
        raise ContractViolation(f"{element_type} payload must be an object")
    schema = schemas[element_type]
    if not isinstance(schema, dict):
        raise ContractViolation(f"{element_type} schema must be an object")
    try:
        import jsonschema
    except ImportError as exc:
        raise ContractViolation("jsonschema extra is required for MBSE discovery") from exc
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "$"
        raise ContractViolation(
            f"{element_type} payload validation failed at {location}: {exc.message}"
        ) from exc
    return json.loads(canonical_json(payload))
```

- [ ] **Step 6: Verify the new schema and packs are already covered by wheel package data**

Confirm these existing package data patterns remain present under `rflp_lite` in `pyproject.toml`:

```toml
"resources/schemas/*.json",
"resources/domain-packs/*.json",
```

No `pyproject.toml` edit is expected in this task. Do not add a runtime dependency. Keep `jsonschema>=4.23` in the existing `schema` optional extra.

- [ ] **Step 7: Validate packs and run tests**

Run:

```bash
.venv/bin/check-jsonschema --schemafile schemas/mbse-domain-pack.schema.json src/rflp_lite/resources/domain-packs/mbse-common-v1.json src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json
.venv/bin/python -m pytest tests/application/test_mbse_domain_packs.py -v
```

Expected: schema command exits `0`; pack tests report `4 passed`.

- [ ] **Step 8: Commit domain-pack support**

```bash
git add schemas/mbse-domain-pack.schema.json src/rflp_lite/resources/schemas/mbse-domain-pack.schema.json src/rflp_lite/resources/domain-packs/mbse-common-v1.json src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json src/rflp_lite/application/mbse_domain_packs.py tests/application/test_mbse_domain_packs.py
git commit -m "feat: add MBSE discovery domain packs"
```

### Task 3: Migrate the workbench to schema v3 without changing legacy outputs

**Files:**
- Modify: `src/rflp_lite/application/workbench_schema.py`
- Modify: `tests/application/test_workbench_schema.py`

**Interfaces:**
- Consumes: existing `migrate_workbench_state(state)`.
- Produces: `WORKBENCH_SCHEMA_VERSION = 3`, `empty_discovery_state() -> dict[str, object]`, and a non-mutating v2→v3 migration.

- [ ] **Step 1: Replace the migration tests with v3 expectations while retaining the future-version test**

```python
import pytest

from rflp_lite.application.workbench_schema import (
    empty_discovery_state,
    migrate_workbench_state,
)
from rflp_lite.domain.errors import ContractViolation


def test_migrate_legacy_state_adds_v3_fields_regions_and_discovery():
    source = {"schema_version": 1, "spans": [{"id": "s1", "text": "原文"}]}
    state = migrate_workbench_state(source)
    assert source["schema_version"] == 1
    assert state["schema_version"] == 3
    assert state["document_regions"][0]["id"] == "s1"
    assert state["structured_requirements"] == []
    assert state["discovery"] == empty_discovery_state()


def test_migrate_v2_preserves_existing_model_and_adds_empty_discovery():
    state = migrate_workbench_state({"schema_version": 2, "mbse": {"revision": "old"}})
    assert state["mbse"] == {"revision": "old"}
    assert state["discovery"]["candidate_sets"] == []


def test_future_schema_is_rejected():
    with pytest.raises(ContractViolation, match="unsupported workbench schema"):
        migrate_workbench_state({"schema_version": 99})
```

- [ ] **Step 2: Run the migration tests and verify v2 behavior fails**

Run: `.venv/bin/python -m pytest tests/application/test_workbench_schema.py -v`

Expected: failures show schema version `2` and missing `discovery`.

- [ ] **Step 3: Implement the v3 discovery fragment**

```python
WORKBENCH_SCHEMA_VERSION = 3

_DISCOVERY_DEFAULTS: dict[str, object] = {
    "intake": {},
    "candidate_sets": [],
    "coverage": {},
    "accepted_graph": {"elements": [], "relations": []},
    "diagram_specs": [],
    "diagnostics": [],
    "revision": 0,
}


def empty_discovery_state() -> dict[str, object]:
    return json.loads(canonical_json(_DISCOVERY_DEFAULTS))
```

Add `"discovery": _DISCOVERY_DEFAULTS` to the existing defaults and keep the existing span→document-region migration. The migrator must clone input with `canonical_json`, reject versions above `3`, set `schema_version` to `3`, and only fill missing/`None` values.

- [ ] **Step 4: Run migration and legacy MBSE tests**

Run:

```bash
.venv/bin/python -m pytest tests/application/test_workbench_schema.py tests/application/test_mbse_modeling.py tests/application/test_requirements_flow.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the schema migration**

```bash
git add src/rflp_lite/application/workbench_schema.py tests/application/test_workbench_schema.py
git commit -m "feat: add discovery state to workbench v3"
```

---

## Increment 2 — Intelligent Expansion and Coverage

### Task 4: Introduce the generative-model port and OpenAI-compatible JSON adapter

**Files:**
- Create: `src/rflp_lite/ports/generative_model.py`
- Create: `src/rflp_lite/adapters/openai_compatible_model.py`
- Create: `tests/adapters/test_openai_compatible_model.py`

**Interfaces:**
- Consumes: existing `chat_completion(config, messages, max_tokens=None) -> str`.
- Produces: `GenerationRequest`, `GenerationResponse`, `GenerativeModel.complete_json(request)`, `OpenAICompatibleModel`.

- [ ] **Step 1: Write failing adapter and import-boundary tests**

```python
import pytest

from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationRequest


def request() -> GenerationRequest:
    return GenerationRequest(
        lens_id="stakeholders",
        system_prompt="只返回 JSON",
        user_payload={"mission": "城市医疗运输"},
        response_schema={"type": "object"},
        max_tokens=1200,
    )


def test_adapter_parses_json_and_records_hashes():
    calls = []

    def complete(config, messages, *, max_tokens=None):
        calls.append((config, messages, max_tokens))
        return '{"items":[]}'

    model = OpenAICompatibleModel({"model": "local"}, complete=complete)
    result = model.complete_json(request())
    assert result.payload == {"items": []}
    assert result.input_hash
    assert result.output_hash
    assert result.model_id == "local"
    assert result.duration_ms >= 0
    assert calls[0][2] == 1200


def test_adapter_repairs_invalid_json_once():
    answers = iter(("not-json", '{"items":[]}'))
    model = OpenAICompatibleModel(
        {"model": "local"},
        complete=lambda *_args, **_kwargs: next(answers),
    )
    assert model.complete_json(request()).payload == {"items": []}


def test_adapter_fails_without_mutating_application_state():
    model = OpenAICompatibleModel(
        {"model": "local"},
        complete=lambda *_args, **_kwargs: "not-json",
    )
    with pytest.raises(AdapterFailure, match="JSON"):
        model.complete_json(request())
```

- [ ] **Step 2: Run tests and verify missing port/adapter**

Run: `.venv/bin/python -m pytest tests/adapters/test_openai_compatible_model.py -v`

Expected: collection fails with missing modules.

- [ ] **Step 3: Define the port types**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    lens_id: str
    system_prompt: str
    user_payload: dict[str, object]
    response_schema: dict[str, object]
    max_tokens: int = 2000


@dataclass(frozen=True, slots=True)
class GenerationResponse:
    lens_id: str
    payload: dict[str, object]
    input_hash: str
    output_hash: str
    repaired: bool
    provider_id: str = ""
    model_id: str = ""
    template_version: str = "v1"
    duration_ms: int = 0
    status: str = "completed"


class GenerativeModel(Protocol):
    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError
```

- [ ] **Step 4: Implement the adapter with exactly one repair attempt**

```python
from __future__ import annotations

import json
import time
from collections.abc import Callable

from rflp_lite.adapters.llm_client import chat_completion
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationRequest, GenerationResponse


class OpenAICompatibleModel:
    def __init__(
        self,
        config: dict[str, object],
        *,
        complete: Callable[..., str] = chat_completion,
    ) -> None:
        self._config = dict(config)
        self._complete = complete

    def complete_json(self, request: GenerationRequest) -> GenerationResponse:
        started = time.monotonic()
        messages = [
            {"role": "system", "content": request.system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "input": request.user_payload,
                        "response_schema": request.response_schema,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            },
        ]
        raw = self._complete(self._config, messages, max_tokens=request.max_tokens)
        repaired = False
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            repaired = True
            repair_messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "上一个响应不是合法 JSON。只返回满足 schema 的 JSON 对象。"},
            ]
            repaired_raw = self._complete(
                self._config, repair_messages, max_tokens=request.max_tokens
            )
            try:
                payload = json.loads(repaired_raw)
                raw = repaired_raw
            except json.JSONDecodeError as exc:
                raise AdapterFailure("LLM response is not valid JSON after one repair") from exc
        if not isinstance(payload, dict):
            raise AdapterFailure("LLM JSON response must be an object")
        return GenerationResponse(
            lens_id=request.lens_id,
            payload=payload,
            input_hash=canonical_hash((request.lens_id, request.user_payload, request.response_schema)),
            output_hash=canonical_hash(payload),
            repaired=repaired,
            provider_id=str(self._config.get("id", self._config.get("label", "openai-compatible"))),
            model_id=str(self._config.get("model", "")),
            template_version="v1",
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            status="completed",
        )
```

- [ ] **Step 5: Run adapter tests**

Run:

```bash
.venv/bin/python -m pytest tests/adapters/test_openai_compatible_model.py -v
```

Expected: adapter tests report `3 passed`.

- [ ] **Step 6: Commit the model boundary**

```bash
git add src/rflp_lite/ports/generative_model.py src/rflp_lite/adapters/openai_compatible_model.py tests/adapters/test_openai_compatible_model.py
git commit -m "feat: add generative model port"
```

### Task 5: Build a deterministic seed model from minimum input

**Files:**
- Create: `src/rflp_lite/application/intelligence/__init__.py`
- Create: `src/rflp_lite/application/intelligence/intake.py`
- Create: `tests/application/intelligence/test_intake.py`

**Interfaces:**
- Consumes: migrated workbench `document_regions`/`spans`, a validated domain pack.
- Produces: `build_seed_model(state, pack) -> dict[str, object]`, `attach_seed_model(state, pack) -> dict[str, object]`.

- [ ] **Step 1: Write failing minimum-input tests**

```python
from rflp_lite.application.intelligence.intake import attach_seed_model, build_seed_model


PACK = {"id": "urban-medical-aam-v1", "display_name": "城市医疗飞行汽车"}


def test_one_sentence_builds_a_named_seed_and_preserves_source():
    state = {
        "schema_version": 3,
        "document_regions": [
            {
                "id": "region-1",
                "artifact_id": "artifact-1",
                "text": "设计一款城市医疗用途的飞行汽车",
            }
        ],
        "discovery": {"intake": {}, "revision": 0},
    }
    seed = build_seed_model(state, PACK)
    assert seed["system_name"] == "城市医疗用途的飞行汽车"
    assert seed["application_type"] == "城市医疗"
    assert seed["source_region_ids"] == ["region-1"]
    assert "operating_boundary" in seed["unknowns"]


def test_attach_seed_increments_discovery_revision_without_mutating_input():
    source = {
        "document_regions": [{"id": "r1", "text": "城市医疗飞行汽车"}],
        "discovery": {"intake": {}, "revision": 0},
    }
    updated = attach_seed_model(source, PACK)
    assert source["discovery"]["revision"] == 0
    assert updated["discovery"]["revision"] == 1
    assert updated["discovery"]["intake"]["seed_hash"]
```

- [ ] **Step 2: Run tests and verify the intake module is absent**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_intake.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement seed extraction with explicit unknowns**

```python
from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _regions(state: dict[str, object]) -> list[dict[str, object]]:
    values = state.get("document_regions") or state.get("spans") or []
    return [item for item in values if isinstance(item, dict) and str(item.get("text", "")).strip()]


def build_seed_model(
    state: dict[str, object], pack: dict[str, object]
) -> dict[str, object]:
    regions = _regions(state)
    if not regions:
        raise ContractViolation("discovery requires at least one non-empty input region")
    text = "\n".join(str(item["text"]).strip() for item in regions)
    application_type = "城市医疗" if "城市" in text and "医疗" in text else "未分类应用"
    if "飞行汽车" in text:
        system_name = "城市医疗用途的飞行汽车" if application_type == "城市医疗" else "飞行汽车"
    else:
        system_name = str(pack.get("display_name", "待定义系统"))
    seed = {
        "system_name": system_name,
        "application_type": application_type,
        "mission_statement": text,
        "source_region_ids": [str(item.get("id", "")) for item in regions],
        "explicit_constraints": [],
        "unknowns": [
            "operating_boundary",
            "target_users",
            "regulatory_jurisdiction",
            "performance_envelope",
            "acceptance_criteria",
        ],
        "pack_id": str(pack["id"]),
    }
    return {**seed, "seed_hash": canonical_hash(seed)}


def attach_seed_model(
    state: dict[str, object], pack: dict[str, object]
) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    discovery = result.setdefault("discovery", {})
    discovery["intake"] = build_seed_model(result, pack)
    discovery["revision"] = int(discovery.get("revision", 0)) + 1
    return result
```

- [ ] **Step 4: Run intake and migration tests**

Run:

```bash
.venv/bin/python -m pytest tests/application/intelligence/test_intake.py tests/application/test_workbench_schema.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit minimum-input intake**

```bash
git add src/rflp_lite/application/intelligence/__init__.py src/rflp_lite/application/intelligence/intake.py tests/application/intelligence/test_intake.py
git commit -m "feat: build discovery seed from sparse input"
```

### Task 6: Run schema-constrained, multi-lens expansion

**Files:**
- Create: `src/rflp_lite/application/intelligence/expansion.py`
- Create: `tests/application/intelligence/test_expansion.py`

**Interfaces:**
- Consumes: `GenerativeModel`, `GenerationRequest`, `CandidateEnvelope.create`, `validate_candidate_payload`, and `state["discovery"]["intake"]`.
- Produces: `build_generation_requests(seed, pack) -> tuple[GenerationRequest, ...]`, `expand_candidates(state, pack, model) -> dict[str, object]`.

- [ ] **Step 1: Write failing multi-lens tests with a deterministic fake model**

```python
from rflp_lite.application.intelligence.expansion import expand_candidates
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


class FakeModel:
    def __init__(self):
        self.lenses = []

    def complete_json(self, request):
        self.lenses.append(request.lens_id)
        element_types = {
            "stakeholders": "stakeholder",
            "environment": "system_boundary",
            "lifecycle_use_cases": "lifecycle_phase",
            "scenarios": "operational_scenario",
            "capabilities_requirements": "capability",
            "functions": "function",
            "components_solutions": "logical_component",
            "risks_questions": "risk",
        }
        payloads = {
            "stakeholders": {"name": "急救医生", "category": "medical", "goals": ["稳定患者状态"], "interactions": ["提交医疗任务"]},
            "environment": {"name": "城市医疗飞行汽车边界"},
            "lifecycle_use_cases": {"name": "起飞", "phase_id": "takeoff"},
            "scenarios": {"name": "低能见度转运", "actors": ["急救医生"], "preconditions": ["患者已登机"], "trigger": "收到转运任务", "steps": ["起飞", "巡航", "降落"], "expected_outcomes": ["患者送达"], "scenario_type": "degraded"},
            "capabilities_requirements": {"name": "医疗转运", "verb": "运输", "object": "患者"},
            "functions": {"name": "规划航路", "inputs": ["任务"], "outputs": ["航路"]},
            "components_solutions": {"name": "任务计算机", "responsibilities": ["规划航路"]},
            "risks_questions": {"name": "低能见度运行风险"},
        }
        item = {
            "element_type": element_types[request.lens_id],
            "payload": payloads[request.lens_id],
            "source_type": "inferred",
            "source_id": f"lens-{request.lens_id}",
            "rationale": "领域分析",
            "confidence": 0.72,
            "assumptions": [],
        }
        payload = {"items": [item]}
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
        )


def pack():
    schemas = {
        "stakeholder": {"required": ["name", "category", "goals", "interactions"]},
        "system_boundary": {"required": ["name"]},
        "lifecycle_phase": {"required": ["name", "phase_id"]},
        "operational_scenario": {"required": ["name", "actors", "preconditions", "trigger", "steps", "expected_outcomes", "scenario_type"]},
        "capability": {"required": ["name", "verb", "object"]},
        "function": {"required": ["name", "inputs", "outputs"]},
        "logical_component": {"required": ["name", "responsibilities"]},
        "risk": {"required": ["name"]},
    }
    return {
        "id": "urban-medical-aam-v1",
        "element_schemas": schemas,
        "prompt_fragments": {name: name for name in (
            "stakeholders", "environment", "lifecycle_use_cases", "scenarios",
            "capabilities_requirements", "functions", "components_solutions", "risks_questions"
        )},
    }


def state():
    return {
        "discovery": {
            "intake": {"system_name": "城市医疗用途的飞行汽车", "seed_hash": "seed-1"},
            "candidate_sets": [],
            "diagnostics": [],
            "revision": 1,
        }
    }


def test_expansion_runs_all_lenses_and_keeps_llm_items_as_candidates():
    model = FakeModel()
    result = expand_candidates(state(), pack(), model)
    assert model.lenses == [
        "stakeholders", "environment", "lifecycle_use_cases", "scenarios",
        "capabilities_requirements", "functions", "components_solutions", "risks_questions"
    ]
    items = [item for group in result["discovery"]["candidate_sets"] for item in group["items"]]
    assert items
    assert all(item["status"] == "candidate" for item in items)
    assert all(item["producer"] == "llm" for item in items)


def test_expansion_is_atomic_when_a_lens_returns_an_invalid_payload():
    class InvalidModel(FakeModel):
        def complete_json(self, request):
            response = super().complete_json(request)
            if request.lens_id == "stakeholders":
                response.payload["items"][0]["payload"] = {"name": "缺少字段"}
            return response

    original = state()
    try:
        expand_candidates(original, pack(), InvalidModel())
    except Exception:
        pass
    assert original["discovery"]["candidate_sets"] == []
```

- [ ] **Step 2: Run tests and verify the expansion module is absent**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_expansion.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement fixed pass boundaries and schema-constrained requests**

```python
from __future__ import annotations

import json

from rflp_lite.application.mbse_domain_packs import validate_candidate_payload
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationRequest, GenerativeModel


LENSES = (
    ("stakeholders", ("stakeholder", "concern", "need")),
    ("environment", ("exchange_flow", "system_boundary")),
    ("lifecycle_use_cases", ("lifecycle_phase", "transition", "use_case")),
    ("scenarios", ("operational_scenario",)),
    ("capabilities_requirements", ("capability", "requirement")),
    ("functions", ("function", "functional_flow", "functional_scenario")),
    ("components_solutions", ("logical_component", "physical_block", "interface", "solution_candidate")),
    ("risks_questions", ("risk", "clarification_question")),
)


def build_generation_requests(
    seed: dict[str, object], pack: dict[str, object]
) -> tuple[GenerationRequest, ...]:
    prompts = pack.get("prompt_fragments", {})
    schemas = pack.get("element_schemas", {})
    requests = []
    for lens_id, allowed_types in LENSES:
        requests.append(
            GenerationRequest(
                lens_id=lens_id,
                system_prompt=(
                    "你是系统工程候选生成器。只返回 JSON；不得批准候选；"
                    "每项必须给出 element_type、payload、source_type、source_id、rationale、confidence、assumptions。"
                    + str(prompts.get(lens_id, ""))
                ),
                user_payload={
                    "seed": seed,
                    "allowed_element_types": list(allowed_types),
                },
                response_schema={
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {"type": "array"},
                        "element_schemas": {
                            key: schemas[key] for key in allowed_types if key in schemas
                        },
                    },
                },
                max_tokens=3000,
            )
        )
    return tuple(requests)


def expand_candidates(
    state: dict[str, object],
    pack: dict[str, object],
    model: GenerativeModel,
) -> dict[str, object]:
    discovery = state.get("discovery")
    if not isinstance(discovery, dict) or not isinstance(discovery.get("intake"), dict):
        raise ContractViolation("build the discovery seed before expansion")
    pending_sets = []
    allowed_by_lens = {lens_id: frozenset(types) for lens_id, types in LENSES}
    for request in build_generation_requests(discovery["intake"], pack):
        response = model.complete_json(request)
        raw_items = response.payload.get("items")
        if not isinstance(raw_items, list):
            raise ContractViolation(f"{request.lens_id} response requires items array")
        items = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                raise ContractViolation(f"{request.lens_id} items must be objects")
            element_type = str(raw.get("element_type", ""))
            if element_type not in allowed_by_lens[request.lens_id]:
                raise ContractViolation(f"{request.lens_id} returned unsupported {element_type}")
            payload = validate_candidate_payload(pack, element_type, raw.get("payload"))
            source_type = str(raw.get("source_type", "inferred"))
            item = CandidateEnvelope.create(
                element_type=element_type,
                pack_id=str(pack["id"]),
                payload=payload,
                provenance=(
                    ProvenanceRef(
                        source_type,
                        str(raw.get("source_id", f"lens-{request.lens_id}")),
                        str(raw.get("rationale", "")),
                    ),
                ),
                producer="llm",
                assumptions=tuple(str(value) for value in raw.get("assumptions", ())),
                confidence=float(raw.get("confidence", 0.5)),
            )
            items.append(item.as_dict())
        pending_sets.append(
            {
                "lens_id": request.lens_id,
                "input_hash": response.input_hash,
                "output_hash": response.output_hash,
                "repaired": response.repaired,
                "provider_id": response.provider_id,
                "model_id": response.model_id,
                "template_version": response.template_version,
                "duration_ms": response.duration_ms,
                "status": response.status,
                "items": sorted(items, key=lambda item: str(item["id"])),
            }
        )
    result = json.loads(canonical_json(state))
    result["discovery"]["candidate_sets"] = pending_sets
    result["discovery"]["revision"] = int(discovery.get("revision", 0)) + 1
    return result
```

- [ ] **Step 4: Run expansion, pack and import-boundary tests**

Run:

```bash
.venv/bin/python -m pytest tests/application/intelligence/test_expansion.py tests/application/test_mbse_domain_packs.py -v
.venv/bin/lint-imports
```

Expected: selected tests and Import Linter pass.

- [ ] **Step 5: Commit the multi-lens pipeline**

```bash
git add src/rflp_lite/application/intelligence/expansion.py tests/application/intelligence/test_expansion.py
git commit -m "feat: generate MBSE candidates by analysis lens"
```

### Task 7: Normalize candidates and surface duplicates and conflicts

**Files:**
- Create: `src/rflp_lite/application/intelligence/normalization.py`
- Create: `tests/application/intelligence/test_normalization.py`

**Interfaces:**
- Consumes: `state["discovery"]["candidate_sets"]`.
- Produces: `normalize_candidate_sets(state) -> dict[str, object]`, normalized `candidate_sets`, `merge_suggestions`, and diagnostics with codes `duplicate_merged`, `possible_duplicate`, `candidate_conflict`.

- [ ] **Step 1: Write failing normalization tests**

```python
from copy import deepcopy

from rflp_lite.application.intelligence.normalization import normalize_candidate_sets


def candidate(identifier, content_hash, name, category="medical", status="candidate"):
    return {
        "id": identifier,
        "element_type": "stakeholder",
        "content_hash": content_hash,
        "status": status,
        "payload": {
            "name": name,
            "category": category,
            "goals": ["目标"],
            "interactions": ["交互"],
        },
        "provenance": [],
    }


def test_exact_duplicates_merge_but_near_duplicates_only_suggest():
    state = {
        "discovery": {
            "candidate_sets": [
                {"lens_id": "a", "items": [candidate("c1", "same", "急救医生")]},
                {"lens_id": "b", "items": [
                    candidate("c2", "same", "急救医生"),
                    candidate("c3", "different", " 急救医生 "),
                ]},
            ],
            "diagnostics": [],
            "revision": 1,
        }
    }
    source = deepcopy(state)
    result = normalize_candidate_sets(state)
    items = [item for group in result["discovery"]["candidate_sets"] for item in group["items"]]
    assert len([item for item in items if item["content_hash"] == "same"]) == 1
    assert result["discovery"]["merge_suggestions"] == [
        {"left_id": "c1", "right_id": "c3", "reason": "normalized-name-match"}
    ]
    assert state == source


def test_same_type_and_name_with_different_payload_is_a_conflict():
    state = {
        "discovery": {
            "candidate_sets": [{"lens_id": "a", "items": [
                candidate("c1", "h1", "监管机构", "regulatory"),
                candidate("c2", "h2", "监管机构", "operations"),
            ]}],
            "diagnostics": [],
            "revision": 1,
        }
    }
    result = normalize_candidate_sets(state)
    assert any(item["code"] == "candidate_conflict" for item in result["discovery"]["diagnostics"])
```

- [ ] **Step 2: Run tests and verify the module is absent**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_normalization.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement deterministic normalization**

Implement `normalize_candidate_sets` with these exact rules:

1. Clone with `json.loads(canonical_json(state))`.
2. Traverse candidate sets in `lens_id`, then candidate `id` order.
3. Keep the first item for each `(element_type, content_hash)` and append later provenance entries to it.
4. Compare remaining items by `(element_type, normalized_name)`, where `normalized_name = " ".join(name.casefold().split())`.
5. If normalized names match and payloads differ only in surrounding whitespace, add one `possible_duplicate` merge suggestion and do not merge.
6. If normalized names match and any non-name payload value differs, append a `candidate_conflict` diagnostic containing both IDs.
7. Increment discovery revision once and never modify accepted Baseline fields.

Use this exact public signature:

```python
def normalize_candidate_sets(state: dict[str, object]) -> dict[str, object]:
    """Return a cloned state with deterministic duplicate handling and diagnostics."""
```

- [ ] **Step 4: Run normalization and canonicalization tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_normalization.py tests/domain/test_canonical.py -v`

Expected: all selected tests pass.

- [ ] **Step 5: Commit normalization**

```bash
git add src/rflp_lite/application/intelligence/normalization.py tests/application/intelligence/test_normalization.py
git commit -m "feat: normalize discovery candidates"
```

### Task 8: Build a bounded coverage matrix and perform one targeted gap-fill pass

**Files:**
- Create: `src/rflp_lite/application/intelligence/coverage.py`
- Create: `tests/application/intelligence/test_coverage.py`

**Interfaces:**
- Consumes: validated pack, normalized candidates, `GenerativeModel`.
- Produces: `evaluate_coverage(state, pack) -> dict[str, object]`, `fill_high_priority_gaps(state, pack, model) -> dict[str, object]`.

- [ ] **Step 1: Write failing coverage tests**

```python
from rflp_lite.application.intelligence.coverage import evaluate_coverage, fill_high_priority_gaps
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


PACK = {
    "id": "urban-medical-aam-v1",
    "stakeholder_lenses": [
        {"id": "medical", "label": "医疗"},
        {"id": "regulatory", "label": "监管"},
    ],
    "lifecycle_phases": [{"id": "takeoff", "label": "起飞"}],
    "scenario_dimensions": [
        {"id": "weather", "label": "天气", "values": ["rain", "fog"]},
    ],
    "coverage_rules": [
        {"id": "stakeholder-lenses", "source": "stakeholder_lenses", "priority": "high"},
        {"id": "lifecycle-phases", "source": "lifecycle_phases", "priority": "high"},
        {"id": "scenario-dimensions", "source": "scenario_dimensions", "priority": "high"},
    ],
    "element_schemas": {"stakeholder": {"required": ["name", "category", "goals", "interactions"]}},
}


def test_coverage_assigns_every_cell_a_known_status():
    state = {
        "discovery": {
            "candidate_sets": [{"lens_id": "stakeholders", "items": [{
                "id": "c1", "element_type": "stakeholder", "status": "candidate",
                "payload": {"name": "医生", "category": "medical", "goals": ["救治"], "interactions": ["下达任务"]},
            }]}],
            "coverage": {}, "revision": 1,
        }
    }
    result = evaluate_coverage(state, PACK)
    cells = result["discovery"]["coverage"]["cells"]
    assert cells
    assert {cell["status"] for cell in cells} <= {"covered", "candidate", "unknown", "not_applicable"}
    assert any(cell["key"] == "stakeholder-lenses/regulatory" and cell["status"] == "unknown" for cell in cells)


def test_gap_fill_calls_model_once_and_marks_attempt():
    class GapModel:
        def __init__(self):
            self.calls = 0

        def complete_json(self, request):
            self.calls += 1
            payload = {"items": []}
            return GenerationResponse(request.lens_id, payload, canonical_hash(request.user_payload), canonical_hash(payload), False)

    state = evaluate_coverage({"discovery": {"candidate_sets": [], "coverage": {}, "revision": 1}}, PACK)
    model = GapModel()
    first = fill_high_priority_gaps(state, PACK, model)
    second = fill_high_priority_gaps(first, PACK, model)
    assert model.calls == 1
    assert second["discovery"]["coverage"]["gap_fill_attempted"] is True
```

- [ ] **Step 2: Run tests and verify the coverage module is absent**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_coverage.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement bounded coverage evaluation**

Use one cell per declared stakeholder lens, lifecycle phase, and scenario dimension value. Do not create a cross-product. Determine status as follows:

```python
def coverage_status(matches: list[dict[str, object]]) -> str:
    if any(item.get("status") == "accepted" for item in matches):
        return "covered"
    if matches:
        return "candidate"
    return "unknown"
```

Match stakeholder cells to `stakeholder.payload.category`; lifecycle cells to `lifecycle_phase.payload.phase_id`; scenario cells to `operational_scenario.payload.contexts[dimension_id]`. Apply an explicit waiver from `coverage.waivers[cell_key]` as `not_applicable`. Sort cells by `rule_id`, `key` and store `summary` counts for all four statuses.

- [ ] **Step 4: Implement exactly one targeted gap-fill request**

`fill_high_priority_gaps` must:

1. Return unchanged state if `gap_fill_attempted` is already true.
2. Select only `unknown` cells whose rule priority is `high`.
3. Send one `GenerationRequest` with lens ID `coverage_gap_fill`, the seed model, and the selected cells.
4. Validate each returned candidate using the same helper used by Task 6.
5. Append a candidate set with `lens_id=coverage_gap_fill`, set `gap_fill_attempted=true`, reevaluate coverage, and keep unresolved cells as `unknown`.
6. If the model raises `AdapterFailure`, append diagnostic code `coverage_gap_fill_failed`, set `gap_fill_attempted=true`, and preserve all existing candidates.

- [ ] **Step 5: Run coverage and expansion tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_coverage.py tests/application/intelligence/test_expansion.py -v`

Expected: all selected tests pass.

- [ ] **Step 6: Commit coverage analysis**

```bash
git add src/rflp_lite/application/intelligence/coverage.py tests/application/intelligence/test_coverage.py
git commit -m "feat: audit discovery coverage"
```

---

## Increment 3 — Review Gate and Legacy Bridge

### Task 9: Add revision-safe candidate review and downstream invalidation

**Files:**
- Create: `src/rflp_lite/application/intelligence/review.py`
- Create: `tests/application/intelligence/test_review.py`

**Interfaces:**
- Consumes: normalized candidate dictionaries and discovery revision.
- Produces: `review_candidate(state, candidate_id, decision, expected_revision)`, `edit_candidate(state, candidate_id, payload, expected_revision, pack)`.

- [ ] **Step 1: Write failing review tests**

```python
import pytest

from rflp_lite.application.intelligence.review import edit_candidate, review_candidate
from rflp_lite.domain.errors import ContractViolation


def state():
    return {
        "discovery": {
            "revision": 4,
            "candidate_sets": [{"lens_id": "test", "items": [
                {"id": "parent", "element_type": "capability", "status": "candidate", "payload": {"name": "医疗运输", "verb": "运输", "object": "患者"}, "provenance": [{"source_type": "inferred", "source_id": "lens-capability", "rationale": "能力分析"}]},
                {"id": "child", "element_type": "requirement", "status": "accepted", "payload": {"name": "响应要求", "statement": "系统应响应任务", "requirement_type": "operational", "verification_method": "test"}, "provenance": [{"source_type": "derived", "source_id": "parent", "rationale": "细化"}]},
            ]}],
            "review_history": [],
        }
    }


def test_review_requires_current_revision_and_records_history():
    with pytest.raises(ContractViolation, match="stale"):
        review_candidate(state(), "parent", "accepted", expected_revision=3)
    result = review_candidate(state(), "parent", "accepted", expected_revision=4)
    assert result["discovery"]["revision"] == 5
    assert result["discovery"]["candidate_sets"][0]["items"][0]["status"] == "accepted"
    assert result["discovery"]["review_history"][-1]["decision"] == "accepted"


def test_edit_returns_descendants_to_stale():
    pack = {"element_schemas": {"capability": {"required": ["name", "verb", "object"]}}}
    result = edit_candidate(
        state(), "parent", {"name": "紧急医疗运输", "verb": "运输", "object": "危重患者"}, 4, pack
    )
    items = {item["id"]: item for item in result["discovery"]["candidate_sets"][0]["items"]}
    assert items["parent"]["status"] == "accepted"
    assert items["child"]["status"] == "stale"
```

- [ ] **Step 2: Run tests and verify the review module is absent**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_review.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement the review state machine**

Implement exact decisions `accepted` and `rejected`; reject all other values. Locate exactly one candidate ID across all sets. For an accepted decision, require a non-empty provenance array. Append history with `candidate_id`, previous status, decision, old revision, new revision and `decision_hash=canonical_hash((candidate_id, previous_status, decision, old_revision, new_revision))`. Clone input before changing it.

Use these signatures:

```python
def review_candidate(
    state: dict[str, object],
    candidate_id: str,
    decision: str,
    expected_revision: int,
) -> dict[str, object]:
    """Accept or reject one current-revision candidate and append immutable history."""


def edit_candidate(
    state: dict[str, object],
    candidate_id: str,
    payload: dict[str, object],
    expected_revision: int,
    pack: dict[str, object],
) -> dict[str, object]:
    """Validate an edit, accept the edited item, and mark derived descendants stale."""
```

Descendant invalidation walks provenance links where `source_id` equals an edited or already invalidated candidate ID. It changes accepted/candidate descendants to `stale`, never changes rejected items, and records all invalidated IDs in the review event.

- [ ] **Step 4: Run review and scenario gate regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/application/intelligence/test_review.py tests/application/test_mbse_modeling.py tests/application/test_sequence_modeling.py -v
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the review gate**

```bash
git add src/rflp_lite/application/intelligence/review.py tests/application/intelligence/test_review.py
git commit -m "feat: review discovery candidates safely"
```

### Task 10: Build the accepted semantic graph and bridge reviewed elements to existing workbench structures

**Files:**
- Create: `src/rflp_lite/application/intelligence/bridge.py`
- Create: `tests/application/intelligence/test_bridge.py`

**Interfaces:**
- Consumes: accepted candidate dictionaries.
- Produces: `build_accepted_graph(state) -> dict[str, object]`, `bridge_discovery_to_workbench(state) -> dict[str, object]`.

- [ ] **Step 1: Write failing bridge tests**

```python
from rflp_lite.application.intelligence.bridge import (
    bridge_discovery_to_workbench,
    build_accepted_graph,
)


def item(identifier, element_type, payload, status="accepted"):
    return {
        "id": identifier,
        "element_type": element_type,
        "status": status,
        "payload": payload,
        "producer": "llm",
        "provenance": [{"source_type": "inferred", "source_id": "lens", "rationale": ""}],
    }


def state():
    return {
        "artifact": {"id": "artifact-1", "path": "input.txt", "sha256": "hash"},
        "document_regions": [{"id": "region-1", "text": "城市医疗飞行汽车"}],
        "stakeholders": [], "concerns": [], "needs": [], "structured_requirements": [], "scenarios": [],
        "discovery": {
            "candidate_sets": [{"lens_id": "test", "items": [
                item("s1", "stakeholder", {"name": "急救医生", "category": "medical", "goals": ["救治"], "interactions": ["下达任务"]}),
                item("r1", "requirement", {"name": "低能见度运行", "statement": "系统应在规定低能见度包线内安全运行", "requirement_type": "operational", "verification_method": "test", "source_region_id": "region-1", "relations": [{"predicate": "satisfiedBy", "target_id": "f1"}]}),
                item("f1", "function", {"name": "感知障碍物", "inputs": ["传感器数据"], "outputs": ["障碍物轨迹"]}),
                item("draft", "risk", {"name": "未确认风险"}, status="candidate"),
            ]}],
            "accepted_graph": {}, "revision": 7,
        },
    }


def test_accepted_graph_excludes_unreviewed_items_and_builds_relations():
    graph = build_accepted_graph(state())
    assert {element["id"] for element in graph["elements"]} == {"s1", "r1", "f1"}
    assert graph["relations"] == [
        {"source_id": "r1", "predicate": "satisfiedBy", "target_id": "f1"}
    ]


def test_bridge_populates_legacy_groups_without_approving_a_baseline():
    result = bridge_discovery_to_workbench(state())
    assert result["stakeholders"][0]["name"] == "急救医生"
    assert result["structured_requirements"][0]["statement"].startswith("系统应")
    assert result.get("baseline") is None
    assert result["discovery"]["accepted_graph"]["graph_hash"]
```

- [ ] **Step 2: Run tests and verify the bridge is absent**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_bridge.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement accepted-graph construction**

Build elements from candidates whose status is exactly `accepted`. Each element contains `id`, `kind=element_type`, `name=payload.name`, `status=accepted`, `attributes=payload`, `provenance` and `producer`. Read optional `payload.relations` and emit a relation only when its target is another accepted element. Sort elements by `(kind, name, id)` and relations by `(source_id, predicate, target_id)`. Add `graph_hash=canonical_hash({"elements": elements, "relations": relations})`.

- [ ] **Step 4: Implement the conservative legacy bridge**

Map accepted elements as follows:

| New type | Existing group | Required mapping |
|---|---|---|
| `stakeholder` | `stakeholders` | id, name, category, status, inferred=true, producer, provenance |
| `concern` | `concerns` | id, name/value, status, producer |
| `need` | `needs` | id, value/name, stakeholder_id, concern_ids, status, producer |
| `requirement` | `structured_requirements` | id, source_region_id, statement, subject, predicate, source_type, verification_method, status, producer |
| `operational_scenario` | `scenarios` | id, title, actors, preconditions, steps, expected_outcomes, faults, status, producer, requirement_ids |

The bridge must replace only records with the same ID, preserve unrelated manual/legacy records, update `discovery.accepted_graph`, increment discovery revision, clear `rflp`, `mbse`, `baseline` and `project` because their source model changed, and never invoke existing approval functions.

- [ ] **Step 5: Run bridge, workbench and traceability tests**

Run:

```bash
.venv/bin/python -m pytest tests/application/intelligence/test_bridge.py tests/application/test_traceability.py tests/application/test_requirements_workbench.py -v
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the compatibility bridge**

```bash
git add src/rflp_lite/application/intelligence/bridge.py tests/application/intelligence/test_bridge.py
git commit -m "feat: bridge reviewed discovery model"
```

---

## Increment 4 — Diagram Semantics and Deterministic SVG

### Task 11: Define renderer-independent diagram contracts

**Files:**
- Create: `src/rflp_lite/domain/diagram_spec.py`
- Create: `tests/domain/test_diagram_spec.py`

**Interfaces:**
- Consumes: canonical serialization helpers.
- Produces: `DiagramNode`, `DiagramEdge`, `DiagramGroup`, `DiagramSpec.create`, `DiagramSpec.as_dict`.

- [ ] **Step 1: Write failing diagram-contract tests**

```python
import pytest

from rflp_lite.domain.diagram_spec import (
    DiagramEdge,
    DiagramGroup,
    DiagramNode,
    DiagramSpec,
)


def test_diagram_spec_is_deterministic_and_keeps_source_ids():
    spec = DiagramSpec.create(
        diagram_type="environment",
        title="系统环境图",
        source_graph_hash="graph-1",
        groups=(DiagramGroup("system", "目标系统", 0),),
        nodes=(DiagramNode("s1", "飞行汽车", "system_boundary", "accepted", "system"),),
        edges=(),
    )
    assert spec.id.startswith("diagram-")
    assert spec.as_dict()["nodes"][0]["source_id"] == "s1"


def test_diagram_spec_rejects_duplicate_ids_and_dangling_edges():
    node = DiagramNode("s1", "系统", "system", "accepted")
    with pytest.raises(ValueError, match="unique"):
        DiagramSpec.create(
            diagram_type="environment",
            title="坏图",
            source_graph_hash="g",
            groups=(),
            nodes=(node, node),
            edges=(),
        )
    with pytest.raises(ValueError, match="reference"):
        DiagramSpec.create(
            diagram_type="environment",
            title="坏图",
            source_graph_hash="g",
            groups=(),
            nodes=(node,),
            edges=(DiagramEdge("e1", "s1", "missing", "flow"),),
        )
```

- [ ] **Step 2: Run tests and verify the diagram contract is absent**

Run: `.venv/bin/python -m pytest tests/domain/test_diagram_spec.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement immutable diagram value objects**

```python
from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash, to_primitive


@dataclass(frozen=True, slots=True)
class DiagramGroup:
    id: str
    label: str
    order: int


@dataclass(frozen=True, slots=True)
class DiagramNode:
    source_id: str
    label: str
    kind: str
    status: str
    group_id: str = ""
    parent_id: str = ""
    detail: str = ""
    order: int = 0


@dataclass(frozen=True, slots=True)
class DiagramEdge:
    id: str
    source_id: str
    target_id: str
    predicate: str
    label: str = ""
    order: int = 0


@dataclass(frozen=True, slots=True)
class DiagramSpec:
    id: str
    format: str
    version: int
    diagram_type: str
    title: str
    source_graph_hash: str
    groups: tuple[DiagramGroup, ...]
    nodes: tuple[DiagramNode, ...]
    edges: tuple[DiagramEdge, ...]
    warnings: tuple[str, ...] = ()
    theme: str = "cesam-light-v1"

    @classmethod
    def create(
        cls,
        *,
        diagram_type: str,
        title: str,
        source_graph_hash: str,
        groups: tuple[DiagramGroup, ...],
        nodes: tuple[DiagramNode, ...],
        edges: tuple[DiagramEdge, ...],
        warnings: tuple[str, ...] = (),
        theme: str = "cesam-light-v1",
    ) -> "DiagramSpec":
        node_ids = [item.source_id for item in nodes]
        group_ids = [item.id for item in groups]
        edge_ids = [item.id for item in edges]
        if len(node_ids) != len(set(node_ids)) or len(group_ids) != len(set(group_ids)) or len(edge_ids) != len(set(edge_ids)):
            raise ValueError("diagram IDs must be unique")
        known = set(node_ids)
        if any(item.source_id not in known or item.target_id not in known for item in edges):
            raise ValueError("diagram edge reference is invalid")
        if any(item.group_id and item.group_id not in set(group_ids) for item in nodes):
            raise ValueError("diagram group reference is invalid")
        if any(item.parent_id and item.parent_id not in known for item in nodes):
            raise ValueError("diagram parent reference is invalid")
        payload = {
            "diagram_type": diagram_type,
            "title": title,
            "source_graph_hash": source_graph_hash,
            "groups": groups,
            "nodes": nodes,
            "edges": edges,
            "theme": theme,
        }
        return cls(
            id=f"diagram-{canonical_hash(payload)[:16]}",
            format="ai4mbse/diagram-spec",
            version=1,
            diagram_type=diagram_type,
            title=title,
            source_graph_hash=source_graph_hash,
            groups=groups,
            nodes=nodes,
            edges=edges,
            warnings=warnings,
            theme=theme,
        )

    def as_dict(self) -> dict[str, object]:
        return to_primitive(self)
```

- [ ] **Step 4: Run diagram-domain tests**

Run: `.venv/bin/python -m pytest tests/domain/test_diagram_spec.py -v`

Expected: `2 passed`.

- [ ] **Step 5: Commit diagram contracts**

```bash
git add src/rflp_lite/domain/diagram_spec.py tests/domain/test_diagram_spec.py
git commit -m "feat: add MBSE diagram specifications"
```

### Task 12: Build all first-version diagram specifications from the accepted graph

**Files:**
- Create: `src/rflp_lite/application/diagrams/__init__.py`
- Create: `src/rflp_lite/application/diagrams/specifications.py`
- Create: `tests/application/diagrams/test_specifications.py`
- Modify: `.importlinter`

**Interfaces:**
- Consumes: `accepted_graph`, validated domain pack, Task 11 contracts.
- Produces: `DIAGRAM_TYPES`, `build_diagram_spec(graph, diagram_type, pack) -> DiagramSpec`, `split_diagram_spec(spec, max_nodes=40) -> tuple[DiagramSpec, ...]`.

- [ ] **Step 1: Write failing specification-builder tests**

```python
import pytest

from rflp_lite.application.diagrams.specifications import (
    DIAGRAM_TYPES,
    build_diagram_spec,
    split_diagram_spec,
)
from rflp_lite.domain.errors import ContractViolation


def graph():
    return {
        "graph_hash": "graph-1",
        "elements": [
            {"id": "system", "kind": "system_boundary", "name": "飞行汽车", "status": "accepted", "attributes": {}},
            {"id": "doctor", "kind": "stakeholder", "name": "急救医生", "status": "accepted", "attributes": {"category": "medical"}},
            {"id": "phase", "kind": "lifecycle_phase", "name": "起飞", "status": "accepted", "attributes": {"phase_id": "takeoff"}},
            {"id": "function", "kind": "function", "name": "感知障碍物", "status": "accepted", "attributes": {}},
            {"id": "draft", "kind": "risk", "name": "未确认", "status": "candidate", "attributes": {}},
        ],
        "relations": [
            {"source_id": "doctor", "predicate": "interactsWith", "target_id": "system"}
        ],
    }


def test_catalog_contains_every_design_diagram_type():
    assert DIAGRAM_TYPES == (
        "stakeholder_hierarchy", "environment", "requirements", "lifecycle",
        "operational_decomposition", "operational_sequence", "functional_decomposition",
        "functional_interaction", "functional_sequence", "logical_decomposition",
        "logical_interaction", "physical_allocation", "physical_interaction",
        "technical_requirements", "traceability",
    )


def test_environment_spec_uses_only_accepted_relevant_elements():
    spec = build_diagram_spec(graph(), "environment", {"diagram_groups": {}})
    assert {node.source_id for node in spec.nodes} == {"system", "doctor"}
    assert spec.edges[0].predicate == "interactsWith"


def test_unsupported_type_and_dense_diagram_are_handled_explicitly():
    with pytest.raises(ContractViolation, match="diagram type"):
        build_diagram_spec(graph(), "unknown", {"diagram_groups": {}})
    dense = graph()
    dense["elements"] = [
        {"id": f"n-{index}", "kind": "stakeholder", "name": f"角色 {index}", "status": "accepted", "attributes": {"category": "medical"}}
        for index in range(45)
    ]
    spec = build_diagram_spec(dense, "stakeholder_hierarchy", {"diagram_groups": {}})
    pages = split_diagram_spec(spec, max_nodes=40)
    assert len(pages) == 2
    assert all(len(page.nodes) <= 40 for page in pages)
```

- [ ] **Step 2: Run tests and verify the builder package is absent**

Run: `.venv/bin/python -m pytest tests/application/diagrams/test_specifications.py -v`

Expected: collection fails with missing module.

- [ ] **Step 3: Implement the diagram catalog and type filters**

Use this exact catalog and semantic filters:

```python
DIAGRAM_TYPES = (
    "stakeholder_hierarchy", "environment", "requirements", "lifecycle",
    "operational_decomposition", "operational_sequence", "functional_decomposition",
    "functional_interaction", "functional_sequence", "logical_decomposition",
    "logical_interaction", "physical_allocation", "physical_interaction",
    "technical_requirements", "traceability",
)

TYPE_FILTERS = {
    "stakeholder_hierarchy": {"stakeholder"},
    "environment": {"system_boundary", "stakeholder", "exchange_flow"},
    "requirements": {"concern", "need", "requirement"},
    "lifecycle": {"lifecycle_phase", "transition"},
    "operational_decomposition": {"use_case", "operational_scenario"},
    "operational_sequence": {"stakeholder", "operational_scenario", "exchange_flow"},
    "functional_decomposition": {"capability", "function"},
    "functional_interaction": {"function", "functional_flow"},
    "functional_sequence": {"function", "functional_scenario", "functional_flow"},
    "logical_decomposition": {"logical_component"},
    "logical_interaction": {"logical_component", "interface"},
    "physical_allocation": {"logical_component", "physical_block"},
    "physical_interaction": {"physical_block", "interface"},
    "technical_requirements": {"physical_block", "requirement"},
    "traceability": set(),
}
```

For `traceability`, include all accepted elements. For other types, include only the mapped kinds. Include a relation only if both endpoints are included. Use `attributes.parent_id` for node hierarchy, `attributes.category`/pack `diagram_groups` for grouping, and integer `attributes.order` for node order. Derive node detail from the first non-empty field among `statement`, `description`, `scenario_type`, `requirement_type`.

- [ ] **Step 4: Implement deterministic split behavior**

`split_diagram_spec` sorts groups by order/ID and nodes by group/kind/label/source ID. For `<= max_nodes`, return the original spec. Otherwise chunk nodes by `max_nodes`, keep only edges whose endpoints occur in the same chunk, append warning `图形已按 {max_nodes} 个节点拆分`, suffix titles with `（1/N）`, and create each page through `DiagramSpec.create` so IDs remain deterministic.

- [ ] **Step 5: Add and verify the new application import boundary**

Append to `.importlinter` after both application packages exist:

```ini
[importlinter:contract:intelligence-does-not-use-adapters]
name = Intelligence and diagrams use ports, not adapters
type = forbidden
source_modules =
    rflp_lite.application.intelligence
    rflp_lite.application.diagrams
forbidden_modules =
    rflp_lite.adapters
```

Run: `.venv/bin/lint-imports`

Expected: every import contract passes.

- [ ] **Step 6: Run diagram specification tests**

Run: `.venv/bin/python -m pytest tests/application/diagrams/test_specifications.py tests/domain/test_diagram_spec.py -v`

Expected: all selected tests pass.

- [ ] **Step 7: Commit semantic diagram builders**

```bash
git add src/rflp_lite/application/diagrams/__init__.py src/rflp_lite/application/diagrams/specifications.py tests/application/diagrams/test_specifications.py .importlinter
git commit -m "feat: build diagrams from accepted semantics"
```

### Task 13: Add the rendering port and a deterministic, escaped SVG adapter

**Files:**
- Create: `src/rflp_lite/ports/diagram_renderer.py`
- Create: `src/rflp_lite/adapters/deterministic_svg_renderer.py`
- Create: `tests/adapters/test_deterministic_svg_renderer.py`

**Interfaces:**
- Consumes: `DiagramSpec`.
- Produces: `RenderedDiagram`, `DiagramRenderer.render(spec)`, `DeterministicSvgRenderer.render(spec)`.

- [ ] **Step 1: Write failing renderer tests**

```python
from rflp_lite.adapters.deterministic_svg_renderer import DeterministicSvgRenderer
from rflp_lite.domain.diagram_spec import DiagramEdge, DiagramNode, DiagramSpec


def spec():
    return DiagramSpec.create(
        diagram_type="environment",
        title="环境 <图>",
        source_graph_hash="graph-1",
        groups=(),
        nodes=(
            DiagramNode("system", "飞行汽车", "system_boundary", "accepted"),
            DiagramNode("doctor", "急救医生", "stakeholder", "accepted"),
        ),
        edges=(DiagramEdge("edge-1", "doctor", "system", "interactsWith", "提交任务"),),
    )


def test_svg_is_stable_escaped_and_contains_traceable_ids():
    renderer = DeterministicSvgRenderer()
    first = renderer.render(spec())
    second = renderer.render(spec())
    assert first == second
    assert first.content_type == "image/svg+xml"
    assert "环境 &lt;图&gt;" in first.content.decode("utf-8")
    assert "环境 <图>" not in first.content.decode("utf-8")
    assert b'data-source-id="doctor"' in first.content
    assert b'marker-end="url(#arrow)"' in first.content


def test_svg_never_renders_nonaccepted_node_status():
    invalid = DiagramSpec.create(
        diagram_type="environment",
        title="非法",
        source_graph_hash="graph-1",
        groups=(),
        nodes=(DiagramNode("draft", "草稿", "stakeholder", "candidate"),),
        edges=(),
    )
    try:
        DeterministicSvgRenderer().render(invalid)
    except ValueError as exc:
        assert "accepted" in str(exc)
    else:
        raise AssertionError("candidate node was rendered")
```

- [ ] **Step 2: Run tests and verify the port/adapter is absent**

Run: `.venv/bin/python -m pytest tests/adapters/test_deterministic_svg_renderer.py -v`

Expected: collection fails with missing modules.

- [ ] **Step 3: Define the rendering port**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rflp_lite.domain.diagram_spec import DiagramSpec


@dataclass(frozen=True, slots=True)
class RenderedDiagram:
    diagram_id: str
    content_type: str
    extension: str
    content: bytes
    warnings: tuple[str, ...] = ()


class DiagramRenderer(Protocol):
    def render(self, spec: DiagramSpec) -> RenderedDiagram:
        raise NotImplementedError
```

- [ ] **Step 4: Implement deterministic layout and SVG generation**

Use these fixed values: canvas width `1200`, margin `36`, header height `72`, node width `220`, node height `64`, horizontal gap `36`, vertical gap `28`. Reject any node whose status is not `accepted`. Sort every input by stable IDs before layout and draw group backgrounds, then edges, then nodes.

Select the layout deterministically from this map:

```python
LAYOUT_BY_TYPE = {
    "stakeholder_hierarchy": "hierarchy",
    "environment": "network",
    "requirements": "hierarchy",
    "lifecycle": "state",
    "operational_decomposition": "hierarchy",
    "operational_sequence": "sequence",
    "functional_decomposition": "hierarchy",
    "functional_interaction": "network",
    "functional_sequence": "sequence",
    "logical_decomposition": "hierarchy",
    "logical_interaction": "network",
    "physical_allocation": "layers",
    "physical_interaction": "network",
    "technical_requirements": "hierarchy",
    "traceability": "layers",
}
```

- `hierarchy`: compute depth from `parent_id`; roots are depth 0; place each depth on one row and sort siblings by label/source ID.
- `network`: place groups in columns ordered by group order/ID; ungrouped system-boundary nodes occupy the center column; route edges with orthogonal two-segment paths.
- `state`: sort nodes by `DiagramNode.order`, then by label; place states left to right and wrap after four; transitions use edge order.
- `sequence`: place node/lifeline headers left to right; draw vertical dashed lifelines; place edges/messages from top to bottom by `DiagramEdge.order`; use a dashed arrow when predicate is `reply`.
- `layers`: rank kinds as requirement/need=0, capability/function=1, logical_component=2, physical_block=3; place each rank in a column and route all connectors behind nodes.

Use one `<marker id="arrow">`, escaped labels, and `data-source-id` on every node group. Hierarchy and layer connectors must never cross node rectangles; sequence labels are capped at 80 visible characters and all other node labels at 60, with the full escaped value in a `<title>` element.

The public implementation must end with:

```python
return RenderedDiagram(
    diagram_id=spec.id,
    content_type="image/svg+xml",
    extension="svg",
    content="".join(parts).encode("utf-8"),
    warnings=spec.warnings,
)
```

Use `html.escape(value, quote=True)` for all title, node, edge and group labels. Do not call the LLM and do not read workbench state in the renderer.

- [ ] **Step 5: Run renderer and existing sequence-renderer tests**

Run:

```bash
.venv/bin/python -m pytest tests/adapters/test_deterministic_svg_renderer.py tests/application/test_sequence_render.py -v
.venv/bin/lint-imports
```

Expected: all selected tests and Import Linter pass.

- [ ] **Step 6: Commit deterministic SVG rendering**

```bash
git add src/rflp_lite/ports/diagram_renderer.py src/rflp_lite/adapters/deterministic_svg_renderer.py tests/adapters/test_deterministic_svg_renderer.py
git commit -m "feat: render discovery diagrams as stable SVG"
```

---

## Increment 5 — Application Service, Interfaces, and Acceptance

### Task 14: Compose the discovery and diagram services without coupling application code to adapters

**Files:**
- Create: `src/rflp_lite/application/intelligence/service.py`
- Create: `src/rflp_lite/application/diagrams/service.py`
- Create: `tests/application/intelligence/test_service.py`
- Create: `tests/application/diagrams/test_service.py`

**Interfaces:**
- Consumes: Tasks 2–13 contracts.
- Produces: `IntelligenceService.draft`, `.review`, `.edit`, `.finalize`; `DiagramService.render_all`, `.render_one`.

- [ ] **Step 1: Write failing orchestration tests**

```python
import pytest

from rflp_lite.application.intelligence.service import IntelligenceService


@pytest.fixture
def valid_pack():
    return {
        "id": "urban-medical-aam-v1",
        "display_name": "城市医疗飞行汽车",
        "element_schemas": {},
        "stakeholder_lenses": [{"id": "medical", "label": "医疗"}],
        "lifecycle_phases": [{"id": "takeoff", "label": "起飞"}],
        "scenario_dimensions": [{"id": "weather", "label": "天气", "values": ["rain"]}],
        "coverage_rules": [
            {"id": "stakeholder-lenses", "source": "stakeholder_lenses", "priority": "high"},
            {"id": "lifecycle-phases", "source": "lifecycle_phases", "priority": "high"},
            {"id": "scenario-dimensions", "source": "scenario_dimensions", "priority": "high"},
        ],
        "prompt_fragments": {},
        "diagram_groups": {},
    }


@pytest.fixture
def sparse_state():
    return {
        "document_regions": [{"id": "region-1", "text": "设计一款城市医疗用途的飞行汽车"}],
        "discovery": {"intake": {}, "candidate_sets": [], "coverage": {}, "diagnostics": [], "revision": 0},
    }


@pytest.fixture
def expanded_state(sparse_state):
    state = sparse_state
    state["discovery"]["candidate_sets"] = [
        {"lens_id": "risks_questions", "items": [
            {"id": "risk-1", "element_type": "risk", "status": "candidate", "payload": {"name": "浓雾"}, "provenance": [{"source_type": "inferred", "source_id": "lens-risk"}]}
        ]}
    ]
    return state


def test_service_degrades_cleanly_without_a_model(valid_pack, sparse_state):
    result = IntelligenceService(valid_pack, model=None).draft(sparse_state)
    assert result["discovery"]["intake"]["system_name"]
    assert result["discovery"]["coverage"]["cells"]
    assert any(item["code"] == "generative_model_unavailable" for item in result["discovery"]["diagnostics"])
    assert result.get("baseline") is None


def test_service_finalization_requires_individual_review(valid_pack, expanded_state):
    service = IntelligenceService(valid_pack, model=None)
    result = service.finalize(expanded_state)
    assert result["discovery"]["accepted_graph"]["elements"] == []
    assert result.get("baseline") is None
```

In `tests/application/diagrams/test_service.py` add:

```python
import pytest

from rflp_lite.application.diagrams.service import DiagramService
from rflp_lite.ports.diagram_renderer import RenderedDiagram


class RecordingRenderer:
    def __init__(self):
        self.types = []

    def render(self, spec):
        self.types.append(spec.diagram_type)
        return RenderedDiagram(spec.id, "image/svg+xml", "svg", f"<svg>{spec.diagram_type}</svg>".encode("utf-8"))


@pytest.fixture
def valid_pack():
    return {"diagram_groups": {}}


@pytest.fixture
def accepted_graph():
    return {
        "graph_hash": "graph-1",
        "elements": [
            {"id": "system", "kind": "system_boundary", "name": "飞行汽车", "status": "accepted", "attributes": {}}
        ],
        "relations": [],
    }


def test_diagram_service_builds_then_renders_without_model_calls(accepted_graph, valid_pack):
    renderer = RecordingRenderer()
    results = DiagramService(renderer).render_all(accepted_graph, valid_pack)
    assert results
    assert renderer.types
    assert all(item.content.startswith(b"<svg>") for item in results)
```

- [ ] **Step 2: Run tests and verify services are absent**

Run:

```bash
.venv/bin/python -m pytest tests/application/intelligence/test_service.py tests/application/diagrams/test_service.py -v
```

Expected: collection fails with missing service modules.

- [ ] **Step 3: Implement the intelligence service pipeline**

```python
from __future__ import annotations

import json

from rflp_lite.application.intelligence.bridge import bridge_discovery_to_workbench
from rflp_lite.application.intelligence.coverage import evaluate_coverage, fill_high_priority_gaps
from rflp_lite.application.intelligence.expansion import expand_candidates
from rflp_lite.application.intelligence.intake import attach_seed_model
from rflp_lite.application.intelligence.normalization import normalize_candidate_sets
from rflp_lite.application.intelligence.review import edit_candidate, review_candidate
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerativeModel


class IntelligenceService:
    def __init__(self, pack: dict[str, object], model: GenerativeModel | None) -> None:
        self.pack = pack
        self.model = model

    def draft(self, state: dict[str, object]) -> dict[str, object]:
        result = attach_seed_model(state, self.pack)
        if self.model is None:
            result = json.loads(canonical_json(result))
            result["discovery"].setdefault("diagnostics", []).append(
                {"code": "generative_model_unavailable", "severity": "warning", "message": "大模型未配置，已保留领域包覆盖检查。"}
            )
            return evaluate_coverage(result, self.pack)
        try:
            result = expand_candidates(result, self.pack, self.model)
            result = normalize_candidate_sets(result)
            result = evaluate_coverage(result, self.pack)
            return fill_high_priority_gaps(result, self.pack, self.model)
        except AdapterFailure as exc:
            degraded = json.loads(canonical_json(result))
            degraded["discovery"].setdefault("diagnostics", []).append(
                {"code": "generative_model_failed", "severity": "warning", "message": str(exc)}
            )
            return evaluate_coverage(degraded, self.pack)

    def review(self, state, candidate_id, decision, expected_revision):
        return review_candidate(state, candidate_id, decision, expected_revision)

    def edit(self, state, candidate_id, payload, expected_revision):
        return edit_candidate(state, candidate_id, payload, expected_revision, self.pack)

    def finalize(self, state):
        return bridge_discovery_to_workbench(evaluate_coverage(state, self.pack))
```

- [ ] **Step 4: Implement the diagram service**

```python
from __future__ import annotations

from rflp_lite.application.diagrams.specifications import (
    DIAGRAM_TYPES,
    build_diagram_spec,
    split_diagram_spec,
)
from rflp_lite.ports.diagram_renderer import DiagramRenderer, RenderedDiagram


class DiagramService:
    def __init__(self, renderer: DiagramRenderer) -> None:
        self.renderer = renderer

    def render_one(
        self,
        graph: dict[str, object],
        pack: dict[str, object],
        diagram_type: str,
    ) -> tuple[RenderedDiagram, ...]:
        spec = build_diagram_spec(graph, diagram_type, pack)
        return tuple(
            self.renderer.render(page)
            for page in split_diagram_spec(spec, max_nodes=40)
        )

    def render_all(
        self,
        graph: dict[str, object],
        pack: dict[str, object],
    ) -> tuple[RenderedDiagram, ...]:
        rendered = []
        for diagram_type in DIAGRAM_TYPES:
            spec = build_diagram_spec(graph, diagram_type, pack)
            if not spec.nodes and not spec.edges:
                continue
            for page in split_diagram_spec(spec, max_nodes=40):
                rendered.append(self.renderer.render(page))
        return tuple(rendered)
```

The service depends only on `DiagramRenderer`; it must not import an adapter.

- [ ] **Step 5: Run service and import-contract tests**

Run:

```bash
.venv/bin/python -m pytest tests/application/intelligence/test_service.py tests/application/diagrams/test_service.py -v
.venv/bin/lint-imports
```

Expected: selected tests and Import Linter pass.

- [ ] **Step 6: Commit application services**

```bash
git add src/rflp_lite/application/intelligence/service.py src/rflp_lite/application/diagrams/service.py tests/application/intelligence/test_service.py tests/application/diagrams/test_service.py
git commit -m "feat: orchestrate discovery and diagrams"
```

### Task 15: Add thin Web, API and CLI entry points

**Files:**
- Create: `src/rflp_lite/interface/web/discovery_routes.py`
- Create: `src/rflp_lite/interface/web/discovery_api.py`
- Create: `src/rflp_lite/interface/web/templates/requirements-discovery.html`
- Modify: `src/rflp_lite/interface/web/app.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `src/rflp_lite/interface/web/templates/base.html`
- Modify: `tests/interface/web/test_app.py`
- Create: `tests/interface/web/test_discovery.py`
- Modify: `tests/interface/test_cli.py`

**Interfaces:**
- Consumes: `IntelligenceService`, `DiagramService`, existing workspace persistence and active LLM profile.
- Produces: `/w/{workspace}/requirements/discovery`, `/api/v1/workspaces/{workspace}/discovery/*`, and `rflp discover` commands.

- [ ] **Step 1: Write failing Web/API tests**

```python
def test_discovery_page_and_local_degraded_run(client, workspace):
    response = client.get(f"/w/{workspace}/requirements/discovery")
    assert response.status_code == 200
    assert "智能补全" in response.text
    run = client.post(
        f"/api/v1/workspaces/{workspace}/discovery/draft",
        json={"pack_id": "urban-medical-aam-v1"},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["discovery"]["intake"]
    assert any(item["code"] == "generative_model_unavailable" for item in payload["discovery"]["diagnostics"])


def test_review_endpoint_requires_revision(client, workspace_with_discovery):
    response = client.post(
        f"/api/v1/workspaces/{workspace_with_discovery}/discovery/review",
        json={"candidate_id": "candidate-1", "decision": "accepted", "expected_revision": 0, "pack_id": "urban-medical-aam-v1"},
    )
    assert response.status_code == 422
```

Use the existing `create_app(tmp_path / "workspaces", fixture_root)` fixture pattern from `tests/interface/web/test_app.py`; create workspaces and requirement input through existing routes rather than writing database files directly.

- [ ] **Step 2: Write failing CLI tests**

Add parser tests for:

```bash
rflp discover draft --workspace /tmp/rflp-discovery-test --pack urban-medical-aam-v1
rflp discover review --workspace /tmp/rflp-discovery-test --candidate-id candidate-0123456789abcdef --decision accepted --revision 4
rflp discover finalize --workspace /tmp/rflp-discovery-test --pack urban-medical-aam-v1
rflp discover export --workspace /tmp/rflp-discovery-test --pack urban-medical-aam-v1 --diagram environment
```

The draft command must return canonical JSON containing `status`, `revision`, `candidate_count`, `coverage`; export must write SVG to stdout and fail if no accepted graph exists.

- [ ] **Step 3: Run interface tests and verify routes/commands are absent**

Run:

```bash
.venv/bin/python -m pytest tests/interface/web/test_discovery.py tests/interface/test_cli.py -v
```

Expected: new routes return `404` and CLI parser rejects `discover`.

- [ ] **Step 4: Add thin composition methods to `WebFacade`**

Add these private helpers and public methods; import the referenced services/adapters at the top of `web_facade.py`:

```python
def _discovery_pack(self, pack_id: str) -> dict[str, object]:
    clean = pack_id.strip()
    if not clean or clean != Path(clean).name or "/" in clean or "\\" in clean:
        raise ContractViolation("invalid discovery pack ID")
    path = resource_path(f"domain-packs/{clean}.json")
    if not path.is_file():
        raise ContractViolation("discovery pack not found")
    return load_mbse_domain_pack(path)


def _intelligence_service(
    self, pack_id: str, *, allow_model: bool
) -> IntelligenceService:
    pack = self._discovery_pack(pack_id)
    config = self.llm.active_config() if allow_model else None
    model = OpenAICompatibleModel(config) if config is not None else None
    return IntelligenceService(pack, model)


def draft_discovery(self, workspace_name: str, pack_id: str) -> dict[str, object]:
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    state = self._intelligence_service(pack_id, allow_model=True).draft(current)
    return self._save_requirements(workspace_name, state, "discovery.drafted")


def review_discovery(
    self,
    workspace_name: str,
    candidate_id: str,
    decision: str,
    expected_revision: int,
    pack_id: str,
) -> dict[str, object]:
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    service = self._intelligence_service(pack_id, allow_model=False)
    state = service.review(current, candidate_id, decision, expected_revision)
    return self._save_requirements(workspace_name, state, "discovery.reviewed")


def edit_discovery(
    self,
    workspace_name: str,
    candidate_id: str,
    payload: dict[str, object],
    expected_revision: int,
    pack_id: str,
) -> dict[str, object]:
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    service = self._intelligence_service(pack_id, allow_model=False)
    state = service.edit(current, candidate_id, payload, expected_revision)
    return self._save_requirements(workspace_name, state, "discovery.edited")


def finalize_discovery(
    self, workspace_name: str, pack_id: str
) -> dict[str, object]:
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    state = self._intelligence_service(pack_id, allow_model=False).finalize(current)
    return self._save_requirements(workspace_name, state, "discovery.finalized")


def render_discovery_diagram(
    self, workspace_name: str, pack_id: str, diagram_type: str
) -> tuple[RenderedDiagram, ...]:
    current = self.requirements(workspace_name)
    if current is None:
        raise ContractViolation("requirements workbench is empty")
    graph = current.get("discovery", {}).get("accepted_graph", {})
    if not graph.get("elements"):
        raise ContractViolation("accepted discovery graph is empty")
    pack = self._discovery_pack(pack_id)
    return DiagramService(DeterministicSvgRenderer()).render_one(
        graph, pack, diagram_type
    )
```

Every state-changing method must call the existing `_save_requirements` once with audit events `discovery.drafted`, `discovery.reviewed`, `discovery.edited`, or `discovery.finalized`. Do not add inference logic to `WebFacade`.

- [ ] **Step 5: Add isolated Web and API routers**

`discovery_routes.py` provides GET page, POST draft/review/edit/finalize, and GET `diagram.svg?type={diagram_type}`; HTML routes let the existing app handlers render domain errors. `discovery_api.py` provides the equivalent JSON operations under `/api/v1`, catches the same `(ContractViolation, RflpError, OSError, ValueError)` tuple used by `api_v1.py`, and returns `_error(exc)` with status `422`. Include both routers in `create_app` next to existing routers.

Define the API helper locally to avoid importing a private function from `api_v1.py`:

```python
def _error(exc: Exception, status_code: int = 422) -> JSONResponse:
    return JSONResponse(
        {"status": "failed", "error": type(exc).__name__, "message": str(exc)},
        status_code=status_code,
    )
```

- [ ] **Step 6: Create the discovery template**

The template must show, in this order:

1. seed mission and unresolved unknowns;
2. pack ID/version and model/degraded status;
3. coverage summary and unknown high-priority cells;
4. candidate groups by lens with source type, confidence, rationale, assumptions and status;
5. individual accept/reject/edit controls containing the current discovery revision;
6. finalize button disabled when no candidate is accepted;
7. diagram cards linked to every `DIAGRAM_TYPES` value;
8. diagnostics with severity and code.

All visible inferred content must carry the label `AI 候选，需人工确认`. Do not add JavaScript or a new CSS framework; use existing Jinja, form POST and stylesheet classes.

- [ ] **Step 7: Add CLI composition and commands**

Add a `discover` parser with required subcommands shown in Step 2. Reuse existing repository/workbench load/save logic. For `draft`, use the active `LLMProfileService` configuration when available; otherwise run degraded mode. For `review` and `finalize`, never construct a model. For `export`, instantiate `DeterministicSvgRenderer` at the CLI composition boundary and write exactly one rendered page with `sys.stdout.buffer.write(rendered.content)`; if more pages exist, require `--page` with a 1-based index.

- [ ] **Step 8: Run Web/API/CLI and security tests**

Run:

```bash
.venv/bin/python -m pytest tests/interface/web/test_discovery.py tests/interface/web/test_app.py tests/interface/test_cli.py tests/application/test_llm_profiles.py -v
```

Expected: all selected tests pass; no API key appears in response bodies or saved workbench JSON.

- [ ] **Step 9: Commit interface integration**

```bash
git add src/rflp_lite/interface/web/discovery_routes.py src/rflp_lite/interface/web/discovery_api.py src/rflp_lite/interface/web/templates/requirements-discovery.html src/rflp_lite/interface/web/app.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/cli.py src/rflp_lite/interface/web/templates/base.html tests/interface/web/test_app.py tests/interface/web/test_discovery.py tests/interface/test_cli.py
git commit -m "feat: expose intelligent MBSE discovery"
```

### Task 16: Add the urban medical AAM acceptance harness, documentation, and full regression gate

**Files:**
- Create: `src/rflp_lite/resources/examples/discovery/urban-medical-aam-seed.txt`
- Create: `src/rflp_lite/resources/examples/discovery/urban-medical-aam-model-responses.json`
- Create: `tests/e2e/test_intelligent_discovery.py`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Create: `docs/verification/2026-08-11-intelligent-discovery.md`

**Interfaces:**
- Consumes: the complete implementation.
- Produces: deterministic acceptance fixture, reproducible commands, package data, verification record.

- [ ] **Step 1: Create deterministic acceptance fixtures**

The seed file contains exactly:

```text
设计一款城市医疗用途的飞行汽车。
```

The response fixture is a JSON object keyed by every Task 6 lens ID. Each lens contains at least one schema-valid item. Collectively it must include:

- stakeholders from every stakeholder lens category;
- lifecycle phases from concept through retirement;
- operational scenarios for normal, degraded, emergency and extreme weather modes;
- contexts covering rain, fog, thunderstorm, night, urban canyon, communication loss, GNSS loss and unavailable landing site;
- capabilities, operational/functional/technical requirements, functions, logical components and physical blocks;
- at least one contradiction and one clarification question;
- relations connecting stakeholder→need→requirement→function→logical component→physical block.

All fixture candidates use `source_type=inferred`, `producer=llm`, confidence between `0.5` and `0.9`, and non-empty rationale. The fixture contains no `accepted` status.

- [ ] **Step 2: Write the failing end-to-end acceptance test**

```python
import json
from copy import deepcopy
from pathlib import Path

from rflp_lite.adapters.deterministic_svg_renderer import DeterministicSvgRenderer
from rflp_lite.application.diagrams.service import DiagramService
from rflp_lite.application.intelligence.service import IntelligenceService
from rflp_lite.application.mbse_domain_packs import (
    load_mbse_domain_pack,
    validate_candidate_payload,
)
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact
from rflp_lite.application.workbench_schema import migrate_workbench_state
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


ROOT = Path("src/rflp_lite/resources/examples/discovery")
PACK_PATH = Path("src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json")


class FixtureModel:
    def __init__(self, responses):
        self.responses = responses

    def complete_json(self, request):
        payload = self.responses[request.lens_id]
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
        )


def build_fixture_run(tmp_path):
    seed = (ROOT / "urban-medical-aam-seed.txt").read_bytes()
    state = migrate_workbench_state(analyze_artifact("urban-medical-aam-seed.txt", seed))
    pack = load_mbse_domain_pack(PACK_PATH)
    responses = json.loads(
        (ROOT / "urban-medical-aam-model-responses.json").read_text(encoding="utf-8")
    )
    return state, pack, FixtureModel(responses)


def test_sparse_urban_medical_aam_reaches_reviewed_graph_and_diagrams(tmp_path):
    state, pack, model = build_fixture_run(tmp_path)
    service = IntelligenceService(pack, model)
    draft = service.draft(state)
    assert draft["discovery"]["intake"]["system_name"] == "城市医疗用途的飞行汽车"
    assert not any(cell["status"] not in {"covered", "candidate", "unknown", "not_applicable"} for cell in draft["discovery"]["coverage"]["cells"])
    assert all(
        item["status"] == "candidate"
        for group in draft["discovery"]["candidate_sets"]
        for item in group["items"]
    )

    reviewed = draft
    for group in list(reviewed["discovery"]["candidate_sets"]):
        for item in list(group["items"]):
            reviewed = service.review(
                reviewed,
                item["id"],
                "accepted",
                reviewed["discovery"]["revision"],
            )
    finalized = service.finalize(reviewed)
    graph = finalized["discovery"]["accepted_graph"]
    assert graph["elements"]
    assert graph["relations"]
    assert finalized.get("baseline") is None

    rendered = DiagramService(DeterministicSvgRenderer()).render_all(graph, pack)
    rendered_types = {item.diagram_id for item in rendered}
    assert rendered_types
    assert all(b"<svg" in item.content for item in rendered)
    assert all(b"data-source-id=" in item.content for item in rendered)


def test_legacy_bulk_accept_does_not_accept_discovery_inference(tmp_path):
    state, pack, model = build_fixture_run(tmp_path)
    draft = IntelligenceService(pack, model).draft(state)
    result = accept_traceable(draft)
    assert all(
        item["status"] == "candidate"
        for group in result["discovery"]["candidate_sets"]
        for item in group["items"]
    )


def test_every_required_coverage_cell_is_assessed(tmp_path):
    state, pack, model = build_fixture_run(tmp_path)
    draft = IntelligenceService(pack, model).draft(state)
    cells = draft["discovery"]["coverage"]["cells"]
    assert cells
    assert all(cell["status"] in {"covered", "candidate", "unknown", "not_applicable"} for cell in cells)


def test_pack_can_add_optional_stakeholder_field_without_python_change(tmp_path):
    _state, pack, _model = build_fixture_run(tmp_path)
    extended = deepcopy(pack)
    schema = extended["element_schemas"]["stakeholder"]
    schema.setdefault("properties", {})["flight_zone"] = {"type": "string"}
    payload = validate_candidate_payload(
        extended,
        "stakeholder",
        {
            "name": "起降场运营方",
            "category": "vertiport",
            "goals": ["保障周转"],
            "interactions": ["分配起降位"],
            "flight_zone": "urban-core",
        },
    )
    assert payload["flight_zone"] == "urban-core"


def test_v2_migration_preserves_existing_mbse():
    state = migrate_workbench_state({"schema_version": 2, "mbse": {"revision": "old"}})
    assert state["mbse"] == {"revision": "old"}
    assert state["schema_version"] == 3


def test_identical_accepted_graph_renders_identical_svg(tmp_path):
    state, pack, model = build_fixture_run(tmp_path)
    service = IntelligenceService(pack, model)
    reviewed = service.draft(state)
    for group in list(reviewed["discovery"]["candidate_sets"]):
        for item in list(group["items"]):
            reviewed = service.review(reviewed, item["id"], "accepted", reviewed["discovery"]["revision"])
    graph = service.finalize(reviewed)["discovery"]["accepted_graph"]
    diagram_service = DiagramService(DeterministicSvgRenderer())
    first = diagram_service.render_one(graph, pack, "environment")
    second = diagram_service.render_one(graph, pack, "environment")
    assert [item.content for item in first] == [item.content for item in second]
```

- [ ] **Step 3: Run the acceptance test**

Run: `.venv/bin/python -m pytest tests/e2e/test_intelligent_discovery.py -v`

Expected: all six end-to-end tests pass. If one fails, stop this task and return to the responsible earlier task; do not weaken review, provenance, coverage or determinism assertions in the acceptance test.

- [ ] **Step 4: Package discovery examples**

Add this package-data pattern to `pyproject.toml`:

```toml
"resources/examples/discovery/*",
```

- [ ] **Step 5: Document the user and operator workflow**

Add to README:

```bash
.venv/bin/rflp discover draft --workspace workspaces/medical-aam --pack urban-medical-aam-v1
.venv/bin/rflp discover review --workspace workspaces/medical-aam --candidate-id candidate-0123456789abcdef --decision accepted --revision 4
.venv/bin/rflp discover finalize --workspace workspaces/medical-aam --pack urban-medical-aam-v1
.venv/bin/rflp discover export --workspace workspaces/medical-aam --pack urban-medical-aam-v1 --diagram environment
```

Explain that AI outputs are candidates, `unknown` means assessed but unresolved, no Baseline is approved by discovery, and field/scenario changes belong in a versioned domain pack.

- [ ] **Step 6: Run focused quality gates**

Run:

```bash
.venv/bin/python -m pytest tests/domain/test_discovery.py tests/domain/test_diagram_spec.py tests/application/intelligence tests/application/diagrams tests/adapters/test_openai_compatible_model.py tests/adapters/test_deterministic_svg_renderer.py tests/interface/web/test_discovery.py tests/e2e/test_intelligent_discovery.py -v
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/mbse-domain-pack.schema.json src/rflp_lite/resources/domain-packs/mbse-common-v1.json src/rflp_lite/resources/domain-packs/urban-medical-aam-v1.json
```

Expected: all tests pass; Import Linter reports no broken contracts; both packs validate.

- [ ] **Step 7: Run the full regression suite and build artifacts**

Run:

```bash
.venv/bin/python -m pytest -v
.venv/bin/python -m build
```

Expected: full suite passes; wheel and source archive are created in `dist/`.

- [ ] **Step 8: Verify the built wheel in a fresh temporary environment**

Run:

```bash
verification_dir=$(mktemp -d '/tmp/rflp-discovery-verify.XXXXXX')
python3 -m venv "$verification_dir/venv"
"$verification_dir/venv/bin/python" -m pip install 'dist/rflp_lite-0.1.0-py3-none-any.whl[schema,web]'
"$verification_dir/venv/bin/rflp" --help
"$verification_dir/venv/bin/python" -c 'from rflp_lite.application.mbse_domain_packs import load_mbse_domain_pack; from rflp_lite.application.resources import resource_path; print(load_mbse_domain_pack(resource_path("domain-packs/urban-medical-aam-v1.json"))["id"])'
```

Expected: CLI help includes `discover`; the final command prints `urban-medical-aam-v1`.

- [ ] **Step 9: Record verification and commit the completed vertical slice**

The verification document records command, exit status, test count, package filenames, known non-goals and the fact that no formal engineering approval was produced.

```bash
git add src/rflp_lite/resources/examples/discovery/urban-medical-aam-seed.txt src/rflp_lite/resources/examples/discovery/urban-medical-aam-model-responses.json tests/e2e/test_intelligent_discovery.py pyproject.toml README.md docs/DEVELOPMENT_STATUS.md docs/verification/2026-08-11-intelligent-discovery.md
git commit -m "feat: complete intelligent MBSE discovery slice"
```

## Final Acceptance Checklist

- [ ] One sentence, multiple fragments, and existing document inputs all produce a seed model without losing provenance.
- [ ] Every pack-defined stakeholder lens, lifecycle phase and scenario dimension has an explicit coverage status.
- [ ] Normal, abnormal, extreme and failure scenarios are candidates with conditions, triggers, actors, steps and expected outcomes.
- [ ] Explicit, derived, inferred, assumed and external-reference sources remain distinguishable through export.
- [ ] No inferred or assumed item enters the accepted graph without an individual review event.
- [ ] Editing an accepted upstream candidate marks every derived descendant stale.
- [ ] Accepted semantics bridge to existing stakeholder/requirement/scenario structures without approving a Baseline.
- [ ] Every diagram reads one accepted graph, carries source IDs and produces deterministic escaped SVG.
- [ ] Dense diagrams split into an overview/page set instead of shrinking text.
- [ ] A new optional field, scenario value or diagram group can be added through a versioned pack without core Python edits.
- [ ] Replacing the LLM or SVG renderer requires only a new adapter and composition change.
- [ ] Existing v2 workspaces and legacy RFLP/MBSE/sequence behavior remain green.
- [ ] No API key appears in persisted or returned data.
- [ ] Full tests, import contracts, JSON schemas, package build and clean-wheel verification pass.
