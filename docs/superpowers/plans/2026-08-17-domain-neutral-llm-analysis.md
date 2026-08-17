# Domain-Neutral LLM Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every project analyze its own arbitrary-domain requirements through one project-scoped LLM request, preserve rich links among requirements inside that project, and prevent all cross-project references or data reuse.

**Architecture:** Keep one SQLite workbench per managed workspace and add an explicit `project_scope` guard at the WebFacade save/load boundary. Add a domain-neutral project-analysis adapter that sends only the current project's source and manual context, normalizes one structured LLM response into the existing workbench/discovery shape, and drives scenario plus RFLP generation. Preserve the existing domain-pack pipeline only for explicit legacy/advanced operations.

**Tech Stack:** Python 3.11+, FastAPI/Starlette, SQLite, Jinja2, pytest, existing OpenAI-compatible `GenerativeModel` port, deterministic SVG renderer.

## Global Constraints

- The project is the isolation boundary: no stakeholder, scenario, requirement, RFLP node, relation, or audit record may be read from or referenced across workspaces.
- Multiple requirements inside one project must be linkable through stakeholder, scenario, R/F/L/P, interface, and traceability relations.
- The default automatic flow must not call `urban-medical-aam-v1`, `common-v1`, `seed_domain_pack_workbench`, or any other domain pack.
- The default automatic flow uses one domain-neutral LLM request; a JSON repair retry is allowed only when the provider returns invalid JSON.
- LLM failure or absence must never inject fallback aviation, medical, or generic domain entities.
- Manual stakeholders and manual scenarios are preserved across automatic re-analysis.
- Existing explicit domain-pack discovery endpoints remain available and are not changed into the default project-analysis path.
- Do not stage or overwrite unrelated pre-existing worktree changes.

---

## Task 1: Add project-scope binding and cross-reference validation

**Files:**
- Create: `src/rflp_lite/application/project_scope.py`
- Modify: `src/rflp_lite/application/workbench_schema.py`
- Modify: `src/rflp_lite/application/web_facade.py:requirements` and `_save_requirements`
- Test: `tests/application/test_project_scope.py`
- Test: `tests/application/test_web_facade.py`

**Interfaces:**
- Produces `bind_project_scope(state: dict[str, object], workspace_name: str) -> dict[str, object]`.
- Produces `validate_project_scope(state: dict[str, object], workspace_name: str) -> None`.
- Produces `validate_project_references(state: dict[str, object]) -> None`.

- [ ] **Step 1: Write failing scope tests**

Add `tests/application/test_project_scope.py`:

```python
import pytest

from rflp_lite.application.project_scope import (
    bind_project_scope,
    validate_project_references,
    validate_project_scope,
)
from rflp_lite.domain.errors import ContractViolation


def test_binding_is_stable_and_records_workspace():
    state = {"document_regions": [{"id": "region-1", "text": "设计一款牙刷"}]}

    bound = bind_project_scope(state, "toothbrush")

    assert bound["project_scope"]["workspace"] == "toothbrush"
    assert bound["project_scope"]["input_hash"]


def test_scope_rejects_state_from_another_workspace():
    state = bind_project_scope({"document_regions": []}, "aircar")

    with pytest.raises(ContractViolation, match="项目作用域"):
        validate_project_scope(state, "toothbrush")


def test_scope_rejects_requirement_reference_outside_current_state():
    state = {
        "claims": [{"id": "req-local"}],
        "scenarios": [{"id": "scenario-1", "requirement_ids": ["req-foreign"]}],
    }

    with pytest.raises(ContractViolation, match="跨项目|不存在"):
        validate_project_references(state)
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/test_project_scope.py
```

Expected: FAIL because `project_scope.py` and the three functions do not exist.

- [ ] **Step 3: Implement scope binding and reference validation**

Create `project_scope.py` with deterministic input hashing and local-reference checks:

```python
from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _clone(state: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(state))


def bind_project_scope(state: dict[str, object], workspace_name: str) -> dict[str, object]:
    result = _clone(state)
    regions = result.get("document_regions") or result.get("spans") or []
    source = tuple(
        (str(item.get("id", "")), str(item.get("text", "")))
        for item in regions
        if isinstance(item, dict)
    )
    result["project_scope"] = {
        "workspace": workspace_name,
        "input_hash": canonical_hash(source),
    }
    return result


def validate_project_scope(state: dict[str, object], workspace_name: str) -> None:
    scope = state.get("project_scope")
    if not isinstance(scope, dict) or not str(scope.get("workspace", "")):
        return
    if str(scope["workspace"]) != workspace_name:
        raise ContractViolation("项目作用域不匹配，禁止跨项目读取或保存")


def validate_project_references(state: dict[str, object]) -> None:
    claim_ids = {str(item.get("id")) for item in state.get("claims", ()) if isinstance(item, dict)}
    element_ids = {
        str(item.get("id"))
        for item in (state.get("rflp") or {}).get("elements", ())
        if isinstance(item, dict)
    }
    known_ids = claim_ids | element_ids
    for scenario in state.get("scenarios", ()):
        if not isinstance(scenario, dict):
            continue
        unknown = set(str(value) for value in scenario.get("requirement_ids", ())) - claim_ids
        if unknown:
            raise ContractViolation(f"场景引用了当前项目不存在的需求: {', '.join(sorted(unknown))}")
    rflp = state.get("rflp") or {}
    for relation in rflp.get("relations", ()) if isinstance(rflp, dict) else ():
        if not isinstance(relation, dict):
            continue
        endpoints = {str(relation.get("source_id", "")), str(relation.get("target_id", ""))}
        if not endpoints <= known_ids:
            raise ContractViolation("RFLP 关系包含当前项目之外或不存在的对象")
    for link in state.get("trace_links", ()):
        if not isinstance(link, dict):
            continue
        endpoints = {str(link.get("source_id", "")), str(link.get("target_id", ""))}
        if not endpoints <= known_ids:
            raise ContractViolation("追溯关系包含当前项目之外或不存在的对象")
```

Add `project_scope: {}` to the schema defaults and call `bind_project_scope` after migration for legacy states. Call `validate_project_scope` and `validate_project_references` in `_save_requirements` before opening the write transaction. For legacy states missing a scope, bind them to the workspace currently loading them and save the migrated state once.

- [ ] **Step 4: Run scope, facade, and migration tests**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/test_project_scope.py tests/application/test_web_facade.py tests/application/test_workbench_schema.py
```

Expected: PASS, with legacy workbench states receiving the current workspace scope.

- [ ] **Step 5: Commit the scoped changes**

Review the staged diff so only the new scope module, schema change, facade hunks, and tests are staged. Then run:

```bash
git diff --cached --check
git commit -m "feat: enforce workspace-scoped requirement links"
```

---

## Task 2: Build the domain-neutral one-request LLM contract

**Files:**
- Create: `src/rflp_lite/application/intelligence/project_analysis.py`
- Modify: `src/rflp_lite/application/intelligence/service.py` only for shared diagnostics/helpers if needed
- Test: `tests/application/intelligence/test_project_analysis.py`

**Interfaces:**
- Produces `build_project_analysis_request(state: dict[str, object]) -> GenerationRequest`.
- Produces `apply_project_analysis(state: dict[str, object], response: GenerationResponse) -> dict[str, object]`.
- Produces `mark_llm_waiting(state: dict[str, object], message: str) -> dict[str, object]`.
- Internal helpers have exact signatures `merge_auto_items(existing: object, incoming: list[dict[str, object]]) -> list[dict[str, object]]`, `preserve_manual_and_replace_auto(existing: object, incoming: list[dict[str, object]], input_hash: str) -> list[dict[str, object]]`, and `build_project_graph(candidate_items: list[dict[str, object]]) -> dict[str, object]`.

- [ ] **Step 1: Write a fixture model and failing contract tests**

Use a fake model that records requests and returns a toothbrush response. Assert that the request has one lens, no `pack_id`, no `urban-medical-aam-v1`, and that the normalized result contains only the response's project-scoped objects.

```python
from rflp_lite.application.intelligence.project_analysis import (
    apply_project_analysis,
    build_project_analysis_request,
)
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


def test_request_is_one_domain_neutral_payload():
    state = {
        "project_scope": {"workspace": "toothbrush", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "设计一款医用安全电动牙刷"}],
        "claims": [{"id": "claim-1", "object": "满足安全使用"}],
        "stakeholders": [],
        "scenarios": [],
    }

    request = build_project_analysis_request(state)

    assert request.lens_id == "project_analysis"
    assert len(request.user_payload["input_regions"]) == 1
    assert "pack_id" not in request.user_payload
    assert "urban-medical-aam-v1" not in str(request.user_payload)
    assert "飞行汽车" not in request.system_prompt


def test_response_creates_domain_objects_and_rflp_architecture():
    payload = {
        "system": {"name": "医用安全电动牙刷", "domain": "医疗器械", "mission": "安全清洁"},
        "stakeholders": [{"id": "s-user", "name": "患者", "category": "end_user", "goals": ["安全使用"]}],
        "concerns": [{"id": "c-safety", "name": "口腔安全", "stakeholder_id": "s-user"}],
        "needs": [{"id": "n-safe", "statement": "患者需要安全清洁", "stakeholder_id": "s-user", "concern_id": "c-safety"}],
        "requirements": [{"id": "r-safe", "statement": "系统应限制刷牙压力", "subject": "系统", "predicate": "应", "source_type": "inferred"}],
        "scenarios": [{"id": "sc-normal", "title": "正常刷牙", "scenario_type": "normal", "actors": ["患者"], "steps": ["启动", "刷牙"], "expected_outcomes": ["安全完成"], "requirement_ids": ["r-safe"]}],
        "architecture": {"functions": [{"id": "f-pressure", "name": "压力控制", "requirement_ids": ["r-safe"]}], "logical_components": [{"id": "l-control", "name": "控制逻辑", "requirement_ids": ["r-safe"]}], "physical_components": [{"id": "p-sensor", "name": "压力传感器", "requirement_ids": ["r-safe"]}], "interfaces": [], "relations": []},
        "open_questions": [],
    }
    response = GenerationResponse("project_analysis", payload, canonical_hash({}), canonical_hash(payload), False)

    result = apply_project_analysis({"project_scope": {"workspace": "toothbrush", "input_hash": "input-1"}, "claims": [], "stakeholders": [], "concerns": [], "needs": [], "structured_requirements": [], "scenarios": [], "discovery": {}}, response)

    assert result["system_context"]["domain"] == "医疗器械"
    assert result["stakeholders"][0]["name"] == "患者"
    assert result["scenarios"][0]["producer"] == "llm"
    assert result["discovery"]["architecture"]["functions"]
```

- [ ] **Step 2: Run the contract tests and verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/intelligence/test_project_analysis.py
```

Expected: FAIL because the project-analysis module and mapping functions do not exist.

- [ ] **Step 3: Implement the request schema and bounded normalizer**

Define a single `GenerationRequest` whose `user_payload` contains only `project_scope`, `input_regions`, accepted/current requirement summaries, manual stakeholder summaries, and manual scenario summaries. Use a schema with `system`, `stakeholders`, `concerns`, `needs`, `requirements`, `scenarios`, `architecture`, `open_questions`, and `diagnostics`. Enforce limits of 12 stakeholders, 24 concerns, 24 needs, 24 requirements, 16 scenarios, 48 architecture nodes, and 96 relations.

Normalize each LLM object with deterministic IDs derived from `(workspace, input_hash, section, model_id)`, set `producer="llm"` and `status="accepted"` for the automatic flow, and preserve `source_region_ids`, `confidence`, `assumptions`, and `rationale`. Reject or omit unknown relation endpoints and requirement IDs that are not in the normalized current project set. Store an accepted discovery candidate set with `pack_id="llm-project-analysis"` as a protocol marker only; never call a pack loader or pack validator.

Map the response into the existing workbench fields. The three helpers named in the Interfaces section must clone their inputs, preserve `producer="user"` records, replace only `producer="llm"` records whose `analysis_input_hash` matches the current input, and sort by stable ID:

```python
result["system_context"] = normalized_system
result["stakeholders"] = merge_auto_items(result.get("stakeholders", ()), stakeholders)
result["concerns"] = merge_auto_items(result.get("concerns", ()), concerns)
result["needs"] = merge_auto_items(result.get("needs", ()), needs)
result["structured_requirements"] = merge_auto_items(result.get("structured_requirements", ()), requirements)
result["scenarios"] = preserve_manual_and_replace_auto(result.get("scenarios", ()), scenarios, input_hash)
result["discovery"] = {
    **existing_discovery,
    "candidate_sets": [{"lens_id": "project_analysis", "items": candidate_items}],
    "accepted_graph": build_project_graph(candidate_items),
    "architecture": normalized_architecture,
    "revision": int(existing_discovery.get("revision", 0)) + 1,
}
```

For no model or model failure, `mark_llm_waiting` must leave user/rule content untouched, clear only stale automatic items from the current input hash, set `auto_analysis.status="waiting_for_llm"`, and append a diagnostic without adding any default stakeholder, scenario, or architecture node.

- [ ] **Step 4: Run the project-analysis tests**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/intelligence/test_project_analysis.py tests/application/intelligence/test_expansion.py
```

Expected: PASS for the new one-request contract and PASS for the unchanged explicit pack expansion tests.

- [ ] **Step 5: Commit the analysis contract**

```bash
git diff --cached --check
git commit -m "feat: add domain-neutral project analysis contract"
```

---

## Task 3: Replace the default WebFacade flow and keep project data isolated

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py:_intelligence_service`, `_auto_complete_requirements`, `analyze_requirements`, `prepare_requirement_scenarios`
- Modify: `src/rflp_lite/application/requirements_workbench.py` only for automatic-item/input-hash helpers
- Modify: `src/rflp_lite/application/scenarios.py` only for domain-neutral scenario type labels and replacement metadata
- Test: `tests/interface/web/test_auto_requirements.py`
- Test: `tests/application/test_web_facade.py`
- Test: `tests/interface/web/test_pages.py`

**Interfaces:**
- The default submit path calls `build_project_analysis_request` exactly once through an active OpenAI-compatible model.
- Explicit `draft_discovery`, `review_discovery`, `finalize_discovery`, and explicit pack diagram routes continue to use `IntelligenceService(pack, model)` unchanged.

- [ ] **Step 1: Add failing two-workspace and no-default-pack tests**

Create two fake responses: an aircar response containing `飞行员`, and a toothbrush response containing `患者`, `牙刷使用者`, and `压力传感器`. Submit each to a separate workspace through the same facade. Assert each state has only its own response entities and the recorded request count is one per workspace. Add a failure-model test asserting no scenarios are created from the fixed AAM matrix and `auto_analysis.status == "waiting_for_llm"`.

```python
def test_default_submit_isolated_by_workspace_and_domain(monkeypatch, tmp_path):
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("aircar")
    facade.create_workspace("toothbrush")
    model = FixtureProjectAnalysisModel({"aircar": aircar_response(), "toothbrush": toothbrush_response()})
    monkeypatch.setattr(facade, "_project_analysis_model", lambda: model)

    facade.analyze_requirements("aircar", "requirements.txt", "设计医疗飞行汽车".encode(), merge=False)
    facade.analyze_requirements("toothbrush", "requirements.txt", "设计医用安全电动牙刷".encode(), merge=False)

    aircar = facade.requirements("aircar")
    toothbrush = facade.requirements("toothbrush")
    assert {item["name"] for item in aircar["stakeholders"]} == {"飞行员"}
    assert {item["name"] for item in toothbrush["stakeholders"]} == {"患者", "牙刷使用者"}
    assert "飞行员" not in str(toothbrush)
    assert model.calls == ["aircar", "toothbrush"]
```

- [ ] **Step 2: Run the integration tests and verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q tests/interface/web/test_auto_requirements.py tests/application/test_web_facade.py
```

Expected: FAIL because the current path calls the fixed `urban-medical-aam-v1` pack and the old multi-lens/16-row scenario matrix.

- [ ] **Step 3: Route default analysis through the project-analysis model**

Factor model configuration into:

```python
def _project_analysis_model(self) -> OpenAICompatibleModel | None:
    config = self.llm.active_config()
    if config is None or (str(config.get("kind", "remote")) == "remote" and not str(config.get("api_key", ""))):
        return None
    return OpenAICompatibleModel(self._normalized_llm_config(config))
```

Replace `_auto_complete_requirements` with the following orchestration order:

```python
def _auto_complete_requirements(self, state: dict[str, object]) -> dict[str, object]:
    model = self._project_analysis_model()
    if model is None:
        return mark_llm_waiting(state, "当前未配置可用 LLM，未生成领域推断结果")
    try:
        response = model.complete_json(build_project_analysis_request(state))
        result = apply_project_analysis(state, response)
        result = confirm_requirements(result)
        result = generate_model(result)
        result, baseline = approve_workbench_baseline(result)
        result["baseline"]["approval_mode"] = "automatic-submission"
        result = generate_mbse_revision(result)
        result["auto_analysis"]["status"] = "completed"
        return result
    except (AdapterFailure, ContractViolation, InvariantViolation) as exc:
        return mark_llm_waiting(state, str(exc))
```

Do not call `seed_domain_pack_workbench`, `auto_accept_and_bridge_discovery`, `generate_scenario_matrix`, or `_discovery_pack` from this default path. Update `prepare_requirement_scenarios` so it returns already generated project scenarios; when none exist and the state is `waiting_for_llm`, it returns the state without invoking a fixed pack. Keep explicit pack routes unchanged.

- [ ] **Step 4: Bind and validate state at every web save/load boundary**

In `analyze_requirements`, bind the state to `workspace_name` before automatic analysis. In `requirements`, migrate, bind missing legacy scope, and validate the loaded scope before returning. In `_save_requirements`, call scope and reference validation after `refresh_traceability` and before `repository.save_workbench`. Ensure `auto_analysis` stores `workspace` and `input_hash` so a later automatic response cannot be applied to a different project.

- [ ] **Step 5: Update scenario labels and UI status behavior**

Map the new scenario types with this template branch in `requirements-scenarios.html`:

```jinja2
{% if scenario.scenario_type == 'boundary' %}边界场景
{% elif scenario.scenario_type == 'failure' %}故障场景
{% elif scenario.scenario_type == 'recovery' %}恢复 / 降级场景
{% elif scenario.scenario_type == 'misuse' %}误操作 / 滥用场景
{% else %}正常场景{% endif %}
```

In `requirements-input.html`, render “等待 LLM 分析” for `waiting_for_llm` instead of “自动分析已完成”, and keep the diagnostic text and manual input links visible.

- [ ] **Step 6: Run integration and page tests**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260817-empty ./.venv/bin/python -m pytest -q tests/interface/web/test_auto_requirements.py tests/application/test_web_facade.py tests/interface/web/test_pages.py
```

Expected: PASS; explicit discovery tests may continue using their pack fixtures, while default submit tests assert domain-neutral results.

- [ ] **Step 7: Commit the default-flow changes**

Stage only the reviewed hunks in the listed files and commit:

```bash
git diff --cached --check
git commit -m "feat: isolate default project analysis by workspace"
```

---

## Task 4: Enrich RFLP synthesis with LLM architecture and traceability

**Files:**
- Modify: `src/rflp_lite/application/synthesize.py:synthesize_rflp`
- Modify: `src/rflp_lite/application/requirements_workbench.py:generate_model` and `render_rflp_svg`
- Test: `tests/application/test_synthesize.py`
- Test: `tests/application/test_requirements_workbench.py`

**Interfaces:**
- Changes `synthesize_rflp(claims)` to `synthesize_rflp(claims, architecture: dict[str, object] | None = None)`; the one-argument call remains valid for legacy callers.
- `generate_model` passes `state["discovery"]["architecture"]` to the synthesizer.
- Produces RFLP elements with `kind`, `attributes`, `source_requirement_ids`, and `status` values suitable for SVG and export.

- [ ] **Step 1: Write failing rich-RFLP tests**

Add a test with two requirements and architecture nodes for two functions, one logical component, two physical components, an interface, and relations. Assert that the output contains more than one function/logical/physical node, has `satisfiedBy`, `allocatedTo`, `realizedBy`, and interface relations, and that every relation endpoint belongs to the current model.

```python
def test_llm_architecture_expands_rflp_and_keeps_requirement_traceability():
    claims = (claim("r1", "限制压力"), claim("r2", "记录使用数据"))
    architecture = {
        "functions": [
            {"id": "f-pressure", "name": "压力控制", "requirement_ids": ["r1"]},
            {"id": "f-record", "name": "使用记录", "requirement_ids": ["r2"]},
        ],
        "logical_components": [{"id": "l-controller", "name": "控制逻辑", "requirement_ids": ["r1", "r2"]}],
        "physical_components": [{"id": "p-sensor", "name": "压力传感器", "requirement_ids": ["r1"]}, {"id": "p-memory", "name": "存储模块", "requirement_ids": ["r2"]}],
        "interfaces": [{"id": "i-data", "name": "传感器数据接口", "source_id": "p-sensor", "target_id": "l-controller"}],
        "relations": [],
    }

    elements, relations = synthesize_rflp(claims, architecture)

    assert {item.name for item in elements if item.layer == "F"} == {"压力控制", "使用记录"}
    assert {item.predicate for item in relations} >= {"satisfiedBy", "allocatedTo", "realizedBy", "exchanges"}
    ids = {item.id for item in elements}
    assert all(item.source_id in ids and item.target_id in ids for item in relations)
```

- [ ] **Step 2: Run the RFLP tests and verify they fail**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/test_synthesize.py tests/application/test_requirements_workbench.py -k rflp
```

Expected: FAIL because synthesis currently creates one function/logical node per claim and ignores architecture input.

- [ ] **Step 3: Implement architecture-aware synthesis**

Use stable IDs based on `(layer, architecture_id, project_scope.input_hash)` and convert LLM nodes to `ModelElement` values. Store all non-display fields as sorted `attributes`, including `source_requirement_ids`, `description`, `responsibilities`, `interfaces`, and `status`. Map architecture relations only when both endpoints are present. Add `satisfiedBy`, `allocatedTo`, and `realizedBy` edges for every accepted requirement path. When an architecture section is absent, add one `needs-analysis` node for each missing layer rather than naming a fake `Python Service` or another fixed implementation.

Update `generate_model` as follows:

```python
architecture = {}
discovery = result.get("discovery")
if isinstance(discovery, dict) and isinstance(discovery.get("architecture"), dict):
    architecture = discovery["architecture"]
elements, relations = synthesize_rflp(tuple(claims), architecture)
```

Add `rflp["analysis_source"] = "llm"` when architecture nodes are present and append a diagnostic when a `needs-analysis` placeholder is used.

- [ ] **Step 4: Improve SVG node and relation presentation**

In `render_rflp_svg`, add `data-kind`, `data-status`, and `data-source-requirements` attributes to each node; display the element kind and one short responsibility/interface summary under the name; draw the relation predicate at the curve midpoint. Keep the existing R/F/L/P columns and deterministic ordering. Increase the card height only from actual node counts so a larger graph remains readable.

- [ ] **Step 5: Run RFLP and export regressions**

Run:

```bash
./.venv/bin/python -m pytest -q tests/application/test_synthesize.py tests/application/test_requirements_workbench.py tests/application/test_project_bridge.py tests/interface/test_cli.py
```

Expected: PASS; legacy one-argument synthesis remains deterministic, and new architecture tests show richer nodes and trace links.

- [ ] **Step 6: Commit the RFLP changes**

```bash
git diff --cached --check
git commit -m "feat: enrich rflp with project architecture links"
```

---

## Task 5: Update project-facing copy, documentation, and compatibility tests

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-graph.html`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Test: `tests/interface/web/test_pages.py`
- Test: `tests/interface/web/test_api_v1.py`

- [ ] **Step 1: Add failing page assertions**

Assert that a waiting-for-LLM page says “等待 LLM 分析” and does not say “自动分析已完成”; assert that a rich RFLP page exposes function/logical/physical counts, relation labels, and the project scope marker; assert that scenario cards render the new scenario types.

- [ ] **Step 2: Implement the page copy and graph metadata**

Keep all links under `/w/{workspace_name}/...`, show the current project name next to automatic-analysis status, and show an explicit warning when results are waiting for LLM. Add this summary above the SVG and keep manual scenario controls unchanged:

```jinja2
<div class="metric-row">
  <article><span>当前项目</span><strong>{{ workspace.name }}</strong></article>
  <article><span>RFLP 节点</span><strong>{{ state.rflp.elements|length }}</strong></article>
  <article><span>RFLP 关系</span><strong>{{ state.rflp.relations|length }}</strong></article>
</div>
```

- [ ] **Step 3: Document the isolation rule and analysis behavior**

Document that a project is the data boundary, requirements inside one project can be chained, and domain packs are opt-in only. Include the no-LLM behavior and the fact that LLM output is a candidate model normalized into the workbench.

- [ ] **Step 4: Run page/API regression tests**

Run:

```bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260817-empty ./.venv/bin/python -m pytest -q tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/interface/web/test_discovery.py
```

Expected: PASS; legacy explicit discovery pages still render their pack-backed coverage views.

- [ ] **Step 5: Commit UI and documentation changes**

```bash
git diff --cached --check
git commit -m "docs: describe project-scoped domain-neutral analysis"
```

---

## Task 6: Full verification and handoff

**Files:**
- Test: all existing tests under `tests/`

- [ ] **Step 1: Run the targeted feature suite**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260817-empty ./.venv/bin/python -m pytest -q \
  tests/application/test_project_scope.py \
  tests/application/intelligence/test_project_analysis.py \
  tests/interface/web/test_auto_requirements.py \
  tests/application/test_synthesize.py \
  tests/application/test_requirements_workbench.py \
  tests/interface/web/test_pages.py
```

Expected: PASS with no real Ollama/network call.

- [ ] **Step 2: Run the full suite and static diff checks**

```bash
RFLP_CONFIG_DIR=/tmp/rflp-lite-test-config-20260817-empty ./.venv/bin/python -m pytest -q
git diff --check
```

Expected: all tests pass; only the repository's existing Starlette/httpx deprecation warning may remain.

- [ ] **Step 3: Verify the running local app**

Start or restart the local server with the current worktree, then check:

```bash
curl -fsS http://127.0.0.1:8000/ | rg "项目管理"
curl -fsS http://127.0.0.1:8000/w/toothbrush/requirements/input | rg "需求输入|项目"
curl -fsS http://127.0.0.1:8000/w/toothbrush/requirements/graph | rg "RFLP|项目作用域"
```

Expected: each URL renders only its own workspace and no default domain-pack text appears in the automatic-analysis status.

- [ ] **Step 4: Review staged scope before any implementation commit**

Run:

```bash
git status --short
git diff --stat
```

Do not stage unrelated documents, generated assets, or pre-existing changes in files touched by this feature. If the worktree contains mixed hunks, leave implementation uncommitted and report the exact files and tests instead of committing unrelated changes.
