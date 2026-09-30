from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.methodology.contracts import RunStatus
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.ports.generative_model import GenerationResponse
from rflp_lite.application.sysml_v2 import graph_to_sysml, sysml_to_graph
from rflp_lite.runtime.structured_model import StructuredModelRuntime


SOURCE = Path("tests/fixtures/requirements_use_case_acceptance.txt")


def _accept_input_requirements(services, project_id: str) -> None:
    """Model the explicit user acceptance required before trusted closure."""

    review = services.review(project_id)
    graph = services.repository(project_id).load_graph(project_id)
    revision = graph.revision
    for entity in graph.entities:
        if entity.kind is EntityKind.REQUIREMENT:
            review.accept_entity(project_id, entity.id, expected_revision=revision)
            revision += 1


def test_pipeline_auto_intakes_ingested_document_before_running(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("document-pipeline")
    services.projects.ingest("document-pipeline", SOURCE)
    _accept_input_requirements(services, "document-pipeline")

    summary = services.analysis("document-pipeline").run(
        "document-pipeline",
        force_new=True,
    )
    graph = services.model("document-pipeline").graph("document-pipeline")
    report = services.analysis("document-pipeline").pipeline_report("document-pipeline")

    assert summary.status is RunStatus.DEGRADED
    # Document intake creates candidate requirements; the lifecycle pauses
    # before trusted closure until a human accepts those candidates.
    assert len(summary.completed_tasks) == 18
    requirements = [item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]
    assert report["traceability"]["end_to_end_complete_count"] == 0
    assert any(item.kind is EntityKind.USE_CASE for item in graph.entities)
    assert any(item.kind is EntityKind.OPERATIONAL_SCENARIO for item in graph.entities)
    assert any(item.kind is EntityKind.ACTIVITY for item in graph.entities)
    assert any(
        event.get("kind") == "requirements_use_case.draft_applied"
        for event in services.repository("document-pipeline").list_audit_events(
            "document-pipeline"
        )
    )


def test_pipeline_from_natural_language_creates_operational_and_functional_layers(
    tmp_path: Path,
):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统应支持自主配送并允许人工接管"
    )
    _accept_input_requirements(services, "robot")

    summary = services.analysis("robot").run("robot", force_new=True)

    graph = services.model("robot").graph("robot")
    kinds = {item.kind for item in graph.entities}
    assert {
        EntityKind.SYSTEM,
        EntityKind.STAKEHOLDER,
        EntityKind.CONCERN,
        EntityKind.LIFECYCLE_STAGE,
        EntityKind.SCENARIO_HYPOTHESIS,
        EntityKind.USE_CASE,
        EntityKind.OPERATIONAL_SCENARIO,
        EntityKind.ACTIVITY,
        EntityKind.FUNCTION,
        EntityKind.FUNCTIONAL_FLOW,
        EntityKind.FUNCTIONAL_SCENARIO,
    } <= kinds
    assert summary.status is RunStatus.BLOCKED
    assert len(summary.completed_tasks) == 23


def test_pipeline_closes_logical_physical_and_assurance_layers(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统功耗不超过 50 W 且续航不少于 10 h"
    )
    _accept_input_requirements(services, "robot")

    summary = services.analysis("robot").run("robot", force_new=True)
    graph = services.model("robot").graph("robot")
    kinds = {item.kind for item in graph.entities}

    assert {
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.INTERFACE,
        EntityKind.STATE,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.HAZARD,
        EntityKind.FAILURE_MODE,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    } <= kinds
    assert any(item.payload.get("level") == "technical" for item in graph.entities)
    assert summary.status is RunStatus.BLOCKED
    assert len(summary.completed_tasks) == 23

    requirement = next(
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") != "technical"
    )
    targets = {
        relation.predicate: relation.target_id
        for relation in graph.relations
        if relation.source_id == requirement.id
    }
    function_id = targets[RelationPredicate.SATISFIED_BY]
    logical_id = next(
        relation.target_id
        for relation in graph.relations
        if relation.source_id == function_id
        and relation.predicate is RelationPredicate.ALLOCATED_TO
    )
    physical_id = next(
        relation.target_id
        for relation in graph.relations
        if relation.source_id == logical_id
        and relation.predicate is RelationPredicate.ALLOCATED_TO
    )
    assert physical_id in graph.entity_index
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.VERIFIED_BY
        for relation in graph.relations
    )
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.VALIDATED_BY
        for relation in graph.relations
    )


def test_pipeline_preserves_requirement_scope_for_multi_requirement_input(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统应完成配送。功耗不超过 120 W。时延不超过 200 ms。系统应支持人工接管。"
    )
    _accept_input_requirements(services, "robot")

    summary = services.analysis("robot").run("robot", force_new=True)
    graph = services.model("robot").graph("robot")
    report = services.analysis("robot").pipeline_report("robot")

    assert summary.status is RunStatus.BLOCKED
    assert len(summary.completed_tasks) == 23
    traceability = report["traceability"]
    physicals = {
        item.payload["source_requirement_ids"][0]: item
        for item in graph.entities
        if item.kind is EntityKind.PHYSICAL_BLOCK
    }
    requirements = {
        item.payload["statement"]: item
        for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") != "technical"
    }
    assert physicals[requirements["功耗不超过 120 W"].id].payload["constraints"] == {
        "max_power_w": 120.0
    }
    assert physicals[requirements["时延不超过 200 ms"].id].payload["constraints"] == {
        "max_latency_ms": 200.0
    }
    assert not physicals[requirements["系统应完成配送"].id].payload["constraints"]
    assert not physicals[requirements["系统应支持人工接管"].id].payload["constraints"]
    technical = [
        item for item in graph.entities
        if item.kind is EntityKind.REQUIREMENT
        and item.payload.get("level") == "technical"
    ]
    input_requirement_ids = {
        item.id for item in requirements.values()
        if item.payload.get("source") == "user_input"
    }
    complete_paths = traceability["paths"]
    assert len(input_requirement_ids) == 4
    assert traceability["complete_count"] == len(complete_paths)
    assert traceability["end_to_end_complete_count"] == len(complete_paths)
    assert input_requirement_ids <= {path[0] for path in complete_paths}
    assert all(len(path) == 6 for path in traceability["paths"])
    assert len(technical) == 2
    assert all(item.payload["source_physical_ids"] == [
        physicals[item.payload["source_requirement_ids"][0]].id
    ] for item in technical)
    hazard = next(item for item in graph.entities if item.kind is EntityKind.HAZARD)
    assert set(hazard.payload["requirement_ids"]) == {
        item.id for item in requirements.values()
    }


def test_pipeline_delivers_complete_traceable_editable_model(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements(
        "系统应支持自主配送并允许人工接管"
    )
    _accept_input_requirements(services, "robot")

    summary = services.analysis("robot").run("robot", force_new=True)
    graph = services.model("robot").graph("robot")
    package = services.deliverables("robot").build("robot")
    trace_metrics = package["artifacts"]["traceability"]["content"]["metrics"]

    assert summary.status is RunStatus.BLOCKED
    assert len(summary.completed_tasks) == 23
    assert set(summary.completed_tasks) == {task.id for task in task_catalog()}
    assert trace_metrics["requirement_count"] == 1
    assert trace_metrics["complete_count"] == 1
    assert package["revision"] == graph.revision
    assert package["snapshot_hash"] == graph.snapshot_hash
    assert package["artifacts"]["rflp"]["content"]["edges"]
    assert package["artifacts"]["vv_plan"]["content"]["rows"]

    restored = sysml_to_graph(graph_to_sysml(graph), "robot")
    assert {item.id: item.kind for item in restored.entities} == {
        item.id: item.kind for item in graph.entities
    }
    assert {
        (item.source_id, item.predicate, item.target_id)
        for item in restored.relations
    } == {
        (item.source_id, item.predicate, item.target_id)
        for item in graph.relations
    }

    function = next(item for item in graph.entities if item.kind is EntityKind.FUNCTION)
    services.review("robot").edit_entity(
        "robot",
        function.id,
        payload={"review_note": "人工确认功能职责"},
    )
    edited = services.model("robot").graph("robot").entity_index[function.id]
    assert edited.payload["review_note"] == "人工确认功能职责"


class LifecycleModel:
    """A deterministic model double that exercises the structured LLM boundary."""

    def __init__(self):
        self.calls: list[str] = []

    def complete_json(self, request):
        self.calls.append(request.lens_id)
        entities = request.user_payload["context"]["entities"]
        by_kind: dict[str, list[dict[str, object]]] = {}
        for item in entities:
            by_kind.setdefault(str(item["kind"]), []).append(item)
        proposal = {
            "entities": [],
            "relations": [],
            "updates": [],
            "deprecations": [],
            "reason": request.lens_id,
        }

        def add(local_ref: str, kind: str, name: str, payload: dict[str, object]):
            proposal["entities"].append({
                "local_ref": local_ref,
                "kind": kind,
                "name": name,
                "payload": payload,
                "source_ids": [],
                "evidence_ids": [],
                "lifecycle_ids": [],
            })

        def relate(source_ref: str, predicate: str, target_ref: str):
            proposal["relations"].append({
                "source_ref": source_ref,
                "predicate": predicate,
                "target_ref": target_ref,
                "evidence_ids": [],
            })

        def update(entity_id: str, payload: dict[str, object]):
            proposal["updates"].append({
                "entity_id": entity_id,
                "field_patch": {"payload": payload},
            })

        def first(kind: str):
            return by_kind.get(kind, [None])[0]

        requirement = first("requirement")
        system = first("system")
        stakeholder = first("stakeholder")
        concern = first("concern")
        stage = first("lifecycle_stage")
        scenario = first("scenario_hypothesis")
        use_case = first("use_case")
        operational = first("operational_scenario")
        activity = first("activity")
        function = first("function")
        logical = first("logical_component")
        physical = first("physical_block")

        if request.lens_id == "system_definition":
            if system:
                update(system["id"], {"open_questions": []})
            else:
                add("system", "system", "脚本系统", {
                    "mission": "完成输入需求定义的系统目标",
                    "system_boundary": {"inside": ["系统能力"], "outside": ["运行环境"]},
                    "objectives": ["形成可追溯模型"],
                    "environment_assumptions": ["环境条件待确认"],
                    "exclusions": [],
                    "open_questions": [],
                })
        elif request.lens_id == "stakeholder_analysis":
            add("stakeholder", "stakeholder", "操作者", {"role": "使用和验收系统"})
            add("concern", "concern", "任务可控", {"topic": "任务完成和异常接管"})
            relate("stakeholder", "hasConcern", "concern")
        elif request.lens_id == "stakeholder_requirements":
            if requirement and concern:
                update(requirement["id"], {"level": "system", "rationale": "来自利益相关方关注点"})
                relate(requirement["id"], "derivedFrom", concern["id"])
        elif request.lens_id == "lifecycle_analysis":
            add("stage", "lifecycle_stage", "运行生命周期", {
                "stage": "operation",
                "sequence": ["需求", "设计", "运行", "维护"],
                "exit_criteria": "运行责任明确",
            })
            add("transition", "lifecycle_transition", "设计到运行", {
                "from_stage": "设计", "to_stage": "运行", "trigger": "验收通过",
            })
            if system:
                relate("stage", "derivedFrom", system["id"])
            relate("transition", "derivedFrom", "stage")
        elif request.lens_id == "scenario_exploration":
            add("scenario", "scenario_hypothesis", "正常和异常场景", {
                "category": "normal_and_exception",
                "trigger": "提交任务",
                "outcome": "完成任务或人工接管",
            })
            if stage:
                relate("scenario", "derivedFrom", stage["id"])
        elif request.lens_id == "use_case_analysis":
            add("use_case", "use_case", "执行任务", {
                "goal": "完成任务并支持异常处理",
                "preconditions": ["系统已部署"],
                "postconditions": ["任务结果已反馈"],
            })
            if scenario:
                relate("use_case", "derivedFrom", scenario["id"])
        elif request.lens_id == "operational_scenario":
            add("operational", "operational_scenario", "任务执行运行场景", {
                "actor_ids": [stakeholder["id"]] if stakeholder else [],
                "steps": ["提交", "执行", "接管", "反馈"],
                "exchanges": [],
                "internal_component_ids": [],
            })
            if use_case:
                relate("operational", "derivedFrom", use_case["id"])
            if stakeholder:
                relate(stakeholder["id"], "participatesIn", "operational")
        elif request.lens_id == "activity_analysis":
            add("activity", "activity", "执行和处置活动", {
                "steps": ["接收", "执行", "监测", "接管", "反馈"],
            })
            if operational:
                relate("activity", "derivedFrom", operational["id"])
            if stage:
                relate("activity", "occursIn", stage["id"])
        elif request.lens_id == "system_requirement_derivation":
            if requirement:
                update(requirement["id"], {"derived_by": "system_requirement_derivation", "rationale": "由运行活动推导"})
                if activity:
                    relate(requirement["id"], "derivedFrom", activity["id"])
        elif request.lens_id == "function_identification":
            add("function", "function", "执行任务能力", {
                "requirement_id": requirement["id"] if requirement else "",
                "behavior": "执行输入需求规定的系统行为",
            })
            if requirement:
                relate(requirement["id"], "satisfiedBy", "function")
        elif request.lens_id == "functional_decomposition":
            if function:
                update(function["id"], {"decomposition": "atomic_behavior"})
        elif request.lens_id == "functional_interaction":
            add("flow", "functional_flow", "任务状态信息流", {
                "source_function_ids": [function["id"]] if function else [],
                "target_function_ids": [function["id"]] if function else [],
                "exchanges": ["任务请求", "状态反馈", "接管指令"],
            })
            if function:
                relate(function["id"], "exchangesWith", "flow")
        elif request.lens_id == "functional_scenario":
            add("fscenario", "functional_scenario", "功能执行场景", {
                "function_ids": [function["id"]] if function else [],
                "steps": ["请求", "处理", "反馈"],
            })
            if function:
                relate(function["id"], "participatesIn", "fscenario")
        elif request.lens_id == "functional_requirement":
            if requirement:
                update(requirement["id"], {
                    "functional_behavior_ids": [function["id"]] if function else [],
                    "functional_requirement_status": "allocated",
                })
        elif request.lens_id == "logical_analysis":
            add("logical", "logical_component", "任务逻辑组件", {
                "function_id": function["id"] if function else "",
                "allocation_strategy": "one_component_per_function",
            })
            if function:
                relate(function["id"], "allocatedTo", "logical")
        elif request.lens_id == "physical_candidates":
            add("physical", "physical_block", "任务执行候选", {
                "logical_id": logical["id"] if logical else "",
                "candidate_type": "implementation_candidate",
                "measurement_status": "needs_measurement",
            })
            if logical:
                relate(logical["id"], "allocatedTo", "physical")
        elif request.lens_id == "allocation_tradeoff":
            if physical:
                update(physical["id"], {"trade_study": {"decision_status": "requires_review"}})
        elif request.lens_id == "technical_requirement":
            if physical:
                update(physical["id"], {"technical_requirement_status": "no_explicit_constraints"})
        elif request.lens_id == "interface_sequence_state":
            add("interface", "interface", "任务控制接口", {
                "kind": "control_and_status", "messages": ["任务", "状态", "接管"],
            })
            add("state", "state", "任务状态", {
                "values": ["待命", "执行中", "异常", "完成"],
                "transitions": ["待命→执行中", "执行中→异常", "执行中→完成"],
            })
            if logical:
                relate(logical["id"], "connectedTo", "interface")
                relate(logical["id"], "decomposes", "state")
        elif request.lens_id == "fmea_stpa_hazard":
            add("hazard", "hazard", "任务失败危险", {
                "description": "任务异常导致目标未达成",
                "requirement_ids": [requirement["id"]] if requirement else [],
                "branches": ["人工接管"],
            })
            add("failure", "failure_mode", "任务未完成失效", {
                "effect": "需求结果不满足",
                "cause": "执行条件异常",
                "requirement_ids": [requirement["id"]] if requirement else [],
            })
            relate("hazard", "causes", "failure")
            if requirement:
                relate("hazard", "mitigatedBy", requirement["id"])
                relate("failure", "mitigatedBy", requirement["id"])
        elif request.lens_id == "verification_validation":
            scope = {
                "requirement_ids": [requirement["id"]] if requirement else [],
                "function_ids": [function["id"]] if function else [],
                "logical_component_ids": [logical["id"]] if logical else [],
                "physical_ids": [physical["id"]] if physical else [],
            }
            add("verification", "verification_case", "验证输入需求", {
                **scope,
                "method": "test",
                "verification_objective": "证明输入需求在规定条件下满足",
                "precondition": "系统处于可测试状态",
                "test_condition": "标准运行环境和需求边界条件",
                "input": "输入需求场景",
                "stimulus": "提交输入需求并施加运行事件",
                "procedure": "执行系统行为并记录结果",
                "expected_result": "行为满足需求",
                "pass_criteria": "需求约束满足",
            })
            add("validation", "validation_case", "确认用户场景", {
                **scope,
                "method": "demonstration",
                "verification_objective": "确认用户场景目标达成",
                "precondition": "典型用户场景可用",
                "test_condition": "典型用户、真实场景和代表性任务条件",
                "input": "用户任务",
                "stimulus": "用户执行典型任务操作",
                "procedure": "执行典型任务并收集反馈",
                "expected_result": "用户目标达成",
                "pass_criteria": "用户确认通过",
            })
            if requirement:
                relate(requirement["id"], "verifiedBy", "verification")
                relate(requirement["id"], "validatedBy", "validation")
        elif request.lens_id == "reverse_feasibility":
            if requirement:
                update(requirement["id"], {
                    "feasibility_review": {
                        "status": "needs_measurement",
                        "measured_values": None,
                    },
                })
        elif request.lens_id == "global_cross_analysis":
            for item in by_kind.get("verification_case", []):
                update(item["id"], {
                    "cross_analysis_status": "checked",
                    "traceability_checked": True,
                })

        return GenerationResponse(
            request.lens_id,
            proposal,
            "scripted-input",
            "scripted-output",
            False,
            "scripted",
            "lifecycle-model",
        )


def test_structured_llm_executes_all_23_tasks_and_writes_the_graph(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces")
    services.projects.create("robot")
    services.requirements_input("robot").ensure_text_requirements("系统应支持人工接管")
    _accept_input_requirements(services, "robot")
    model = LifecycleModel()
    services._runtime_override = StructuredModelRuntime(model)

    summary = services.analysis("robot").run("robot", force_new=True)

    assert summary.status is RunStatus.BLOCKED
    assert model.calls == [task.id for task in task_catalog()]
    report = services.analysis("robot").pipeline_report("robot")
    assert report["traceability"]["complete_count"] == 1
    assert report["report_revision"] == services.model("robot").graph("robot").revision
    stored = services.repository("robot").load_run("robot", summary.run_id)
    assert stored is not None
    assert len(stored.steps) == 23
    assert all(step.status == "completed" for step in stored.steps)
    task_patches = services.repository("robot").list_patches("robot")
    assert {str(item["task_id"]) for item in task_patches} >= set(model.calls)

    graph = services.model("robot").graph("robot")
    assert any(item.kind is EntityKind.FUNCTION for item in graph.entities)
    assert any(
        item.kind is EntityKind.VALIDATION_CASE
        for item in graph.entities
    )
    logical = next(
        item for item in graph.entities
        if item.kind is EntityKind.LOGICAL_COMPONENT
    )
    assert logical.payload["architecture_reasoning"]["basis"]["function_ids"] == [
        logical.payload["function_id"]
    ]
    physical = next(
        item for item in graph.entities
        if item.kind is EntityKind.PHYSICAL_BLOCK
    )
    assert physical.payload["feasibility_reasoning"]["logical_ids"] == [
        physical.payload["logical_id"]
    ]
    assert physical.payload["feasibility_reasoning"]["status"] == "needs_measurement"
    package = services.deliverables("robot").build("robot")
    trace_metrics = package["artifacts"]["traceability"]["content"]["metrics"]
    assert trace_metrics["requirement_count"] == 1
    assert trace_metrics["complete_count"] == 1
    assert package["artifacts"]["rflp"]["content"]["edges"]
    assert package["artifacts"]["vv_plan"]["content"]["rows"]
    restored = sysml_to_graph(package["artifacts"]["sysml"]["content"], "robot")
    assert {item.id for item in restored.entities} == {item.id for item in graph.entities}
    assert {
        (item.source_id, item.predicate, item.target_id)
        for item in restored.relations
    } == {
        (item.source_id, item.predicate, item.target_id)
        for item in graph.relations
    }
