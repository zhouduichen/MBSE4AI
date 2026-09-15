from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.vertical_generation import stage_task


def test_request_contains_actual_prompt_version_and_content_hash():
    task = task_catalog()[0]
    request = TaskExecutor(lambda request: None).request(
        task, ContextBuilder().build(ModelGraph("p1"), task), "v2.1"
    )

    assert request.prompt_text.startswith("# Role")
    assert request.prompt_version == "v1"
    assert request.prompt_hash
    assert request.output_contract["prompt_hash"] == request.prompt_hash


def test_prompt_hash_is_content_hash_not_template_id():
    from rflp_lite.domain.canonical import canonical_hash
    from rflp_lite.methodology.registries import PromptRegistry

    task = task_catalog()[0]
    executor = TaskExecutor(lambda request: None, prompt_registry=PromptRegistry({task.prompt_template_id: "# Role\ncustom"}))
    request = executor.request(task, ContextBuilder().build(ModelGraph("p1"), task), "v2.1")

    assert request.prompt_hash == canonical_hash(request.prompt_text)
    assert request.prompt_hash != canonical_hash(task.prompt_template_id)


def test_system_definition_schema_requires_update_for_existing_system():
    task = next(item for item in task_catalog() if item.id == "system_definition")
    system = make_entity(EntityKind.SYSTEM, "系统")
    request = TaskExecutor(lambda request: None).request(
        task,
        ContextBuilder().build(ModelGraph("p1", (system,)), task),
        "v2.1",
    )

    properties = request.output_contract["properties"]
    assert properties["entities"]["maxItems"] == 0
    assert properties["updates"]["minItems"] == 1
    assert properties["updates"]["maxItems"] == 1
    update = properties["updates"]["items"]
    assert update["properties"]["entity_id"] == {"const": system.id}
    assert update["properties"]["field_patch"]["required"] == ["payload"]
    assert properties["deprecations"]["maxItems"] == 0


def test_system_definition_schema_requires_one_entity_without_existing_system():
    task = next(item for item in task_catalog() if item.id == "system_definition")
    request = TaskExecutor(lambda request: None).request(
        task, ContextBuilder().build(ModelGraph("p1"), task), "v2.1"
    )

    properties = request.output_contract["properties"]
    assert properties["entities"]["minItems"] == 1
    assert properties["entities"]["maxItems"] == 1
    assert properties["updates"]["maxItems"] == 0
    assert properties["deprecations"]["maxItems"] == 0


def test_stakeholder_requirements_schema_reuses_existing_requirements():
    task = next(item for item in task_catalog() if item.id == "stakeholder_requirements")
    requirement = make_entity(EntityKind.REQUIREMENT, "已有需求")
    stakeholder = make_entity(EntityKind.STAKEHOLDER, "已有利益相关者")
    request = TaskExecutor(lambda request: None).request(
        task,
        ContextBuilder().build(ModelGraph("p1", (requirement, stakeholder)), task),
        "v2.1",
    )

    properties = request.output_contract["properties"]
    assert properties["entities"]["maxItems"] == 0
    assert properties["relations"]["minItems"] == 1


def test_stakeholder_requirements_allows_noop_without_source_entities():
    task = next(item for item in task_catalog() if item.id == "stakeholder_requirements")
    requirement = make_entity(EntityKind.REQUIREMENT, "已有需求")
    request = TaskExecutor(lambda request: None).request(
        task,
        ContextBuilder().build(ModelGraph("p1", (requirement,)), task),
        "v2.1",
    )

    assert request.output_contract["properties"]["entities"]["maxItems"] == 0
    assert "minItems" not in request.output_contract["properties"]["relations"]


def test_stakeholder_requirements_keeps_add_path_for_new_concerns():
    task = next(item for item in task_catalog() if item.id == "stakeholder_requirements")
    requirement = make_entity(EntityKind.REQUIREMENT, "已有需求")
    concern = make_entity(EntityKind.CONCERN, "新发现的关注点")
    request = TaskExecutor(lambda request: None).request(
        task,
        ContextBuilder().build(ModelGraph("p1", (requirement, concern)), task),
        "v2.1",
    )

    properties = request.output_contract["properties"]
    assert properties["entities"]["maxItems"] == 32
    assert properties["relations"]["minItems"] == 1


def test_lifecycle_analysis_reuses_existing_stages_for_new_transitions():
    task = next(item for item in task_catalog() if item.id == "lifecycle_analysis")
    stage = make_entity(EntityKind.LIFECYCLE_STAGE, "运行")
    request = TaskExecutor(lambda request: None).request(
        task,
        ContextBuilder().build(ModelGraph("p1", (stage,)), task),
        "v2.1",
    )

    entity_schema = request.output_contract["properties"]["entities"]["items"]
    assert entity_schema["properties"]["kind"] == {"const": "lifecycle_transition"}


def test_vertical_requirements_contract_only_allows_missing_r_kinds():
    task = stage_task("requirements")
    existing = tuple(
        make_entity(kind, kind.value)
        for kind in (
            EntityKind.SYSTEM,
            EntityKind.STAKEHOLDER,
            EntityKind.LIFECYCLE_STAGE,
            EntityKind.SCENARIO_HYPOTHESIS,
            EntityKind.REQUIREMENT,
        )
    )

    request = TaskExecutor(lambda request: None).request(
        task,
        ContextBuilder().build(ModelGraph("p1", existing), task),
        "v2.1",
    )

    properties = request.output_contract["properties"]
    entity_schema = properties["entities"]["items"]
    assert entity_schema["properties"]["kind"] == {
        "enum": ["activity", "concern", "lifecycle_transition", "operational_scenario", "use_case"]
    }
    assert properties["entities"]["maxItems"] == 5
    assert properties["deprecations"]["maxItems"] == 0
