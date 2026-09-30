# Typed Impact Plan Implementation Plan

> **For agentic workers:** Execute this plan inline in the current session, task-by-task, with a focused test cycle after each task.

**Goal:** Make ModelGraph changes produce a deterministic, revision-bound impact plan that drives targeted downstream RFLP/V&V re-analysis and is visible in the API and workbench.

**Architecture:** Add a side-effect-free `TypedImpactPlanner` in the methodology layer. It traverses only allowlisted typed graph relations, returns an immutable `ImpactPlan`, and becomes the single source for Controller task selection, review re-analysis requests, and generation-stage selection. Keep the existing stage executor, patch compiler, review protections, and ModelGraph as the mutation and semantic boundaries.

**Tech Stack:** Python 3.12, dataclasses, FastAPI, Jinja2, pytest, Ruff, `ModelGraph`, existing `VerticalStage` catalog, deterministic `VerticalRuleRuntime` and `StructuredModelRuntime` test doubles.

## Global Constraints

- Do not start or call a local model service; all verification uses deterministic offline runtimes.
- ModelGraph remains the semantic source of truth; SysML remains an interchange projection.
- Do not introduce an asynchronous queue or a second mutation path.
- Do not overwrite accepted, locked, or `user_modified` entities during re-analysis.
- Keep existing API fields and current Controller, continuation, V&V, and SysML round-trip behavior compatible.
- Bound and deterministically sort impact entities and paths before returning them.

## File Map

- Create `src/rflp_lite/methodology/impact.py`: immutable impact path/plan contracts and typed graph traversal.
- Modify `src/rflp_lite/methodology/engine.py`: replace the private undirected walk with the planner and retain the existing tuple-returning compatibility wrapper.
- Modify `src/rflp_lite/application/model_generation.py`: expose the plan, use its selected stages, and return revision-bound before/after impact metadata.
- Modify `src/rflp_lite/application/review_service.py`: use the same planner for re-analysis requests.
- Modify `src/rflp_lite/interface/web/resource_api.py`: add the read-only impact endpoint and attach impact data to edit responses.
- Modify `src/rflp_lite/interface/web/templates/requirement-detail.html`: present a compact impact summary after edits/re-analysis.
- Create `tests/methodology/test_impact.py`: unit-test typed traversal, stage selection, bounds, and disconnected nodes.
- Modify `tests/methodology/test_engine.py`: protect compatibility and relation-path behavior.
- Modify `tests/application/test_model_generation.py`: verify targeted re-analysis metadata and user-protection behavior.
- Modify `tests/interface/web/test_vertical_generation_api.py`: verify endpoint and edit-response contracts.
- Modify `README.md` and `docs/CURRENT_ARCHITECTURE.md`: document the impact loop.

### Task 1: Add the typed impact contract and failing tests

**Files:**
- Create: `src/rflp_lite/methodology/impact.py`
- Create: `tests/methodology/test_impact.py`

**Interfaces:**
- Consumes: `ModelGraph`, `EntityKind`, `EntityStatus`, `RelationPredicate`, `VerticalStage`, `vertical_stage_specs`, and `stage_required_kinds`.
- Produces: `ImpactPath`, `ImpactPlan`, and `TypedImpactPlanner.plan(graph, changed_entity_ids, max_entities=96, max_paths=24)`.

- [ ] **Step 1: Write the failing unit tests**

```python
import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import ModelGraph, Relation
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.domain.errors import NotFoundError
from rflp_lite.methodology.impact import TypedImpactPlanner


def _rflp_graph() -> tuple[ModelGraph, dict[str, object]]:
    requirement = make_entity(EntityKind.REQUIREMENT, "续航约束", status=EntityStatus.VALIDATED)
    function = make_entity(EntityKind.FUNCTION, "管理能量", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "能量控制器", status=EntityStatus.VALIDATED)
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "计算平台", status=EntityStatus.VALIDATED)
    verification = make_entity(EntityKind.VERIFICATION_CASE, "验证续航", status=EntityStatus.VALIDATED)
    validation = make_entity(EntityKind.VALIDATION_CASE, "确认任务续航", status=EntityStatus.VALIDATED)
    disconnected = make_entity(EntityKind.FUNCTION, "无关功能", status=EntityStatus.VALIDATED)
    graph = ModelGraph(
        "p1",
        (requirement, function, logical, physical, verification, validation, disconnected),
        (
            Relation("r-f", requirement.id, RelationPredicate.SATISFIED_BY, function.id),
            Relation("f-l", function.id, RelationPredicate.ALLOCATED_TO, logical.id),
            Relation("l-p", logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
            Relation("r-v", requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
            Relation("r-va", requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
        ),
        revision=7,
    )

    return graph, {
        "requirement": requirement,
        "function": function,
        "logical": logical,
        "physical": physical,
        "verification": verification,
        "validation": validation,
        "disconnected": disconnected,
    }


def test_requirement_impact_follows_typed_rflp_and_vv_edges_but_not_disconnected_nodes():
    graph, entities = _rflp_graph()
    requirement = entities["requirement"]
    plan = TypedImpactPlanner().plan(graph, (requirement.id,))

    assert set(plan.impacted_entity_ids) == {
        entities["requirement"].id, entities["function"].id,
        entities["logical"].id, entities["physical"].id,
        entities["verification"].id, entities["validation"].id,
    }
    assert entities["disconnected"].id not in plan.impacted_entity_ids
    assert plan.selected_stages == ("requirements", "functional", "logical", "physical", "assurance")
    assert plan.verification_case_ids == (entities["verification"].id,)
    assert plan.validation_case_ids == (entities["validation"].id,)
    assert any("satisfiedBy" in path.predicates for path in plan.impact_paths)


def test_function_and_physical_changes_start_at_their_earliest_vertical_stage():
    graph, entities = _rflp_graph()
    function_plan = TypedImpactPlanner().plan(graph, (entities["function"].id,))
    physical_plan = TypedImpactPlanner().plan(graph, (entities["physical"].id,))

    assert function_plan.selected_stages == ("functional", "logical", "physical", "assurance")
    assert physical_plan.selected_stages == ("physical", "assurance")


def test_unknown_seed_is_rejected_and_paths_are_bounded():
    graph, entities = _rflp_graph()
    planner = TypedImpactPlanner()

    with pytest.raises(NotFoundError):
        planner.plan(graph, ("missing-entity",))
    assert len(planner.plan(graph, (entities["requirement"].id,), max_paths=1).impact_paths) <= 1
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/pytest tests/methodology/test_impact.py -q`

Expected: FAIL because `rflp_lite.methodology.impact` and `TypedImpactPlanner` do not exist.

- [ ] **Step 3: Implement the immutable contracts and traversal**

Implement these exact public shapes:

```python
@dataclass(frozen=True, slots=True)
class ImpactPath:
    entity_ids: tuple[str, ...]
    predicates: tuple[str, ...]
    directions: tuple[str, ...]

    def as_dict(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class ImpactPlan:
    project_id: str
    revision: int
    snapshot_hash: str
    trigger_entity_ids: tuple[str, ...]
    trigger_kinds: tuple[str, ...]
    impacted_entity_ids: tuple[str, ...]
    impacted_stages: tuple[str, ...]
    selected_stages: tuple[str, ...]
    recommended_tasks: tuple[str, ...]
    verification_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    impact_paths: tuple[ImpactPath, ...]
    status: str
    reason: str

    def as_dict(self) -> Mapping[str, object]: ...


class TypedImpactPlanner:
    def plan(
        self,
        graph: ModelGraph,
        changed_entity_ids: Sequence[str],
        *,
        max_entities: int = 96,
        max_paths: int = 24,
    ) -> ImpactPlan: ...
```

Use active entities only (`REJECTED` and `DEPRECATED` are excluded), reject an unknown seed with `NotFoundError`, walk both directions over the explicit impact predicate allowlist, retain the relation value and direction for every hop, stop at `max_entities`, and sort IDs/paths deterministically. Map the earliest changed kind through `vertical_stage_index_for_kind` and `vertical_stage_specs`; select that stage and every later stage. Derive V&V IDs by entity kind and derive task names from one module-level kind-to-task map. A valid seed with no neighbors still returns a non-empty plan for its own stage.

- [ ] **Step 4: Run focused tests and lint**

Run: `./.venv/bin/pytest tests/methodology/test_impact.py -q && ./.venv/bin/python -m ruff check src/rflp_lite/methodology/impact.py tests/methodology/test_impact.py`

Expected: all focused tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit the planner**

```bash
git add src/rflp_lite/methodology/impact.py tests/methodology/test_impact.py
git commit -m "feat: add typed model impact planner"
```

### Task 2: Replace internal impact routing and integrate targeted generation

**Files:**
- Modify: `src/rflp_lite/methodology/engine.py`
- Modify: `src/rflp_lite/application/model_generation.py`
- Modify: `src/rflp_lite/application/review_service.py`
- Test: `tests/methodology/test_engine.py`
- Test: `tests/application/test_model_generation.py`

**Interfaces:**
- Consumes: `TypedImpactPlanner.plan` and `ImpactPlan.as_dict`.
- Produces: `ModelGenerationService.impact_plan(project_id, changed_entity_ids) -> ImpactPlan`; `_reanalysis_payload` fields `impact`, `before_traceability`, `after_traceability`, and `impacted_vv_case_ids`.

- [ ] **Step 1: Add compatibility and metadata tests**

```python
def test_engine_impact_wrapper_uses_typed_paths():
    graph = _graph()
    report = MethodologyEngine().analyze(
        graph,
        changed_entity_ids=(next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT).id,),
    )
    assert report.impacted_entity_ids
    assert report.impact_paths


def test_targeted_reanalysis_returns_before_after_traceability_and_vv_impact(tmp_path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")
    generated = services.generation("robot").generate("robot", requirement_text="系统应支持人工接管")
    requirement = next(item for item in services.model("robot").graph("robot").entities if item.kind is EntityKind.REQUIREMENT)

    result = services.generation("robot").reanalyze("robot", requirement.id, expected_revision=generated.revision)

    assert result["before_traceability"]
    assert result["after_traceability"]
    assert result["impact"]["revision"] == result["trigger_revision"]
    assert set(result["impacted_vv_case_ids"]) >= set(
        item.id for item in services.model("robot").graph("robot").entities
        if item.kind in {EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE}
    )
```

- [ ] **Step 2: Run the focused tests to verify the new assertions fail**

Run: `./.venv/bin/pytest tests/methodology/test_engine.py tests/application/test_model_generation.py -q -k 'typed_paths or before_after_traceability'`

Expected: FAIL because the current report uses the old private walk and re-analysis payload does not contain the new fields.

- [ ] **Step 3: Integrate the planner without creating a second execution path**

Import `TypedImpactPlanner` into `engine.py`, replace the body of the private `_impact` compatibility method with the planner result, and keep its return tuple as:

```python
return (
    plan.impacted_entity_ids,
    plan.impacted_stages,
    plan.recommended_tasks,
    tuple(path.entity_ids for path in plan.impact_paths),
)
```

In `ModelGenerationService`, add:

```python
def impact_plan(
    self,
    project_id: str,
    changed_entity_ids: Sequence[str],
) -> ImpactPlan:
    return TypedImpactPlanner().plan(
        self.repository.load_graph(project_id),
        tuple(changed_entity_ids),
    )
```

At the start of `reanalyze`, capture `before_graph` and `impact = self.impact_plan(...)`; select stages from `impact.selected_stages` using `stage_spec` instead of recalculating a separate kind-based route. After execution, capture `after_graph` and include both traceability snapshots, `impact.as_dict()`, and the union of impacted verification/validation IDs in `_reanalysis_payload`. Keep the existing expected-revision check before any write.

In `ReviewService.request_reanalysis`, call `TypedImpactPlanner().plan(graph, (entity_id,))`; use `impact.recommended_tasks` and include `impact.as_dict()` plus `selected_stages`. Retain the existing deterministic Methodology report and Controller response for compatibility.

- [ ] **Step 4: Run focused application tests and lint**

Run: `./.venv/bin/pytest tests/methodology/test_engine.py tests/application/test_model_generation.py -q && ./.venv/bin/python -m ruff check src/rflp_lite/methodology/engine.py src/rflp_lite/application/model_generation.py src/rflp_lite/application/review_service.py tests/methodology/test_engine.py tests/application/test_model_generation.py`

Expected: all selected tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit application integration**

```bash
git add src/rflp_lite/methodology/engine.py src/rflp_lite/application/model_generation.py src/rflp_lite/application/review_service.py tests/methodology/test_engine.py tests/application/test_model_generation.py
git commit -m "feat: route reanalysis through typed impact"
```

### Task 3: Expose impact in the API and workbench

**Files:**
- Modify: `src/rflp_lite/interface/web/resource_api.py`
- Modify: `src/rflp_lite/interface/web/templates/requirement-detail.html`
- Test: `tests/interface/web/test_vertical_generation_api.py`

**Interfaces:**
- Consumes: `ModelGenerationService.impact_plan`, existing review edit responses, and current revision helpers.
- Produces: `GET /projects/{project_id}/entities/{entity_id}/impact`; edit responses with `impact` and `controller` fields.

- [ ] **Step 1: Write endpoint and response tests**

```python
def test_entity_impact_endpoint_is_revision_bound(tmp_path):
    client = _client(tmp_path)
    client.post("/projects", json={"id": "p1"})
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    requirement_id = next(
        item["id"] for item in client.get("/projects/p1/model").json()["entities"]
        if item["kind"] == "requirement"
    )

    response = client.get(f"/projects/p1/entities/{requirement_id}/impact")

    assert response.status_code == 200
    payload = response.json()
    assert payload["impact"]["revision"] == generated["revision"]
    assert payload["impact"]["selected_stages"] == [
        "requirements", "functional", "logical", "physical", "assurance"
    ]


def test_edit_response_contains_next_impact_plan(tmp_path):
    client = _client(tmp_path)
    client.post("/projects", json={"id": "p1"})
    generated = client.post(
        "/projects/p1/analysis",
        json={"mode": "generate", "requirement_text": "系统应支持人工接管"},
    ).json()["run"]
    requirement_id = next(
        item["id"] for item in client.get("/projects/p1/model").json()["entities"]
        if item["kind"] == "requirement"
    )

    response = client.post(
        f"/projects/p1/entities/{requirement_id}/edit",
        json={"expected_revision": generated["revision"], "statement": "系统应支持人工接管并记录响应时间"},
    )

    assert response.status_code == 200
    assert response.json()["impact"]["revision"] == response.json()["revision"]["sequence"]
    assert response.json()["controller"]["status"] in {"needs_action", "complete"}
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `./.venv/bin/pytest tests/interface/web/test_vertical_generation_api.py -q -k 'impact_endpoint or edit_response'`

Expected: FAIL because the endpoint is not registered and edit responses do not carry impact metadata.

- [ ] **Step 3: Implement the endpoint and response decoration**

Add the route immediately after the existing entity listing route:

```python
@resource_api.get("/projects/{project_id}/entities/{entity_id}/impact")
def get_entity_impact(request: Request, project_id: str, entity_id: str):
    try:
        generation = _services(request).generation(project_id)
        impact = generation.impact_plan(project_id, (entity_id,))
        controller = generation.controller_plan(
            project_id, changed_entity_ids=(entity_id,)
        )
        return {"status": "ok", "impact": impact.as_dict(), "controller": controller}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)
```

In `_run_review_command`, after an `edit` succeeds, calculate the same plan against the returned current revision and return it alongside the existing `review` and `revision` fields. Do not calculate it for actions that do not change content. In `requirement-detail.html`, add a hidden `impact-feedback` callout. On a successful edit response, render `selected_stages`, V&V case count, and the Controller next task before reloading; on a re-analysis response, render its impact summary as well. Keep all existing buttons and reload behavior intact.

- [ ] **Step 4: Run API tests, template checks, and lint**

Run: `./.venv/bin/pytest tests/interface/web/test_vertical_generation_api.py tests/interface/web/test_review_actions.py -q && ./.venv/bin/python -m ruff check src/rflp_lite/interface/web/resource_api.py tests/interface/web/test_vertical_generation_api.py`

Expected: all selected tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 5: Commit API/UI integration**

```bash
git add src/rflp_lite/interface/web/resource_api.py src/rflp_lite/interface/web/templates/requirement-detail.html tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: expose model change impact"
```

### Task 4: Document, run the full gate, and push

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Test: all existing tests and the full verification script

**Interfaces:**
- Consumes: completed `ImpactPlan` API and UI behavior.
- Produces: documented local iteration workflow and a clean GitHub branch.

- [ ] **Step 1: Add concise product documentation**

Document the user flow in `README.md` and the architecture boundary in `docs/CURRENT_ARCHITECTURE.md`:

```text
User edit → revision-bound typed impact plan → accept/lock → targeted downstream RFLP/V&V re-analysis → before/after traceability.
```

State explicitly that impact planning is deterministic and does not invoke a local model.

- [ ] **Step 2: Run the complete verification gate**

Run: `./.venv/bin/python scripts/verify_full.py`

Expected: compile succeeds, pytest reaches 100% with no failures, architecture metrics stay within `architecture_budget.json`, Ruff passes, and import-boundary checks report `0 broken`.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check && git status --short --branch && git diff HEAD~3 --stat`

Expected: no whitespace errors; only the planned files are changed; no local model process or provider call has been started.

- [ ] **Step 4: Commit documentation and push**

```bash
git add README.md docs/CURRENT_ARCHITECTURE.md
git commit -m "docs: document typed iteration loop"
git push origin codex/web-audit-2026-08-18
```

- [ ] **Step 5: Confirm branch synchronization**

Run: `git status --short --branch && git log -4 --oneline`

Expected: the branch is clean and its upstream is synchronized with the pushed commits.
