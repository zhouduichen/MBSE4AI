from pathlib import Path

from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.entities import EntityKind, Producer
from rflp_lite.ports.generative_model import GenerationResponse
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.runtime.rule_based import VerticalRuleRuntime


class ScriptedModel:
    def __init__(self):
        self.calls = []

    def complete_json(self, request):
        self.calls.append(request.lens_id)
        entities = request.user_payload["context"]["entities"]
        by_kind = {}
        for item in entities:
            by_kind.setdefault(item["kind"], []).append(item)
        payload = {"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": request.lens_id}

        def entity(local_ref, kind, name, data):
            payload["entities"].append({"local_ref": local_ref, "kind": kind, "name": name, "payload": data, "confidence": 0.9, "source_ids": [], "evidence_ids": [], "lifecycle_ids": []})

        def relation(source_ref, predicate, target_ref):
            payload["relations"].append({"source_ref": source_ref, "predicate": predicate, "target_ref": target_ref, "evidence_ids": []})

        requirements = by_kind.get("requirement", [])
        if request.lens_id == "vertical.requirements":
            entity("system", "system", "校园配送系统", {"mission": "完成校园配送", "system_boundary": {"inside": ["配送服务"], "outside": ["校园环境"]}, "objectives": ["按时完成任务"], "environment_assumptions": ["道路可通行"], "exclusions": [], "open_questions": []})
            entity("stakeholder", "stakeholder", "配送运营人员", {"role": "任务运营"})
            entity("scenario", "operational_scenario", "典型配送场景", {"actor_ids": ["stakeholder"], "steps": ["提交任务", "完成配送"], "exchanges": [], "internal_component_ids": []})
            relation("system", "decomposes", "stakeholder")
            relation("stakeholder", "participatesIn", "scenario")
            if requirements:
                relation(requirements[0]["id"], "derivedFrom", "scenario")
        elif request.lens_id == "vertical.functional":
            entity("function", "function", "规划并执行配送", {"behavior": "根据任务完成配送", "inputs": ["任务"], "outputs": ["结果"]})
            entity("flow", "functional_flow", "任务结果流", {"content": "任务和结果"})
            entity("fscenario", "functional_scenario", "完成配送功能场景", {"function_ids": ["function"], "steps": ["输入", "处理", "输出"]})
            if requirements:
                relation(requirements[0]["id"], "satisfiedBy", "function")
            relation("function", "exchangesWith", "flow")
        elif request.lens_id == "vertical.logical":
            functions = by_kind.get("function", [])
            entity("logical", "logical_component", "配送控制组件", {"responsibility": "协调配送功能", "interfaces": []})
            entity("interface", "interface", "配送服务接口", {"protocol": "logical-message", "exchanges": ["request", "response"]})
            if functions:
                relation(functions[0]["id"], "allocatedTo", "logical")
                relation(functions[0]["id"], "exchangesWith", "interface")
        elif request.lens_id == "vertical.physical":
            entity("physical", "physical_block", "配送执行单元", {"candidate_type": "可部署执行单元", "constraints": ["满足逻辑职责"], "rationale": "承载配送控制"})
            logical = by_kind.get("logical_component", [])
            if logical:
                relation(logical[0]["id"], "allocatedTo", "physical")
        elif request.lens_id == "vertical.verification_validation":
            entity("verification", "verification_case", "验证配送需求", {"method": "test", "pass_criteria": "测试满足需求", "requirement_ids": [requirements[0]["id"]] if requirements else [], "scenario_ids": []})
            entity("validation", "validation_case", "确认配送体验", {"method": "demonstration", "pass_criteria": "用户场景满足需求", "requirement_ids": [requirements[0]["id"]] if requirements else [], "scenario_ids": []})
            if requirements:
                relation(requirements[0]["id"], "verifiedBy", "verification")
                relation(requirements[0]["id"], "validatedBy", "validation")
        payload["assumptions"] = ["脚本模型用于测试结构化边界"]
        payload["open_questions"] = []
        return GenerationResponse(request.lens_id, payload, "input", "output", False, "fake", "scripted")


def test_generation_creates_real_rflp_and_vv_objects_from_one_requirement(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot", "校园配送机器人")

    result = services.generation("robot").generate(
        "robot",
        requirement_text="系统应在校园内自主完成配送并支持人工接管",
    )
    graph = services.model("robot").graph("robot")

    assert result.status == "completed"
    assert {
        EntityKind.FUNCTION,
        EntityKind.LOGICAL_COMPONENT,
        EntityKind.PHYSICAL_BLOCK,
        EntityKind.VERIFICATION_CASE,
        EntityKind.VALIDATION_CASE,
    } <= {item.kind for item in graph.entities}
    assert result.traceability.complete_count >= 1
    assert all(
        "候选" not in item.meta.name and "待确认" not in item.meta.name
        for item in graph.entities
        if item.meta.producer is Producer.RULE
    )


def test_generation_is_recorded_as_one_five_stage_run(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )
    run = services.repository("robot").load_run("robot", result.run_id)

    assert run is not None
    assert run.phase == "vertical_generation"
    assert {step.task_id for step in run.steps} == {
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    }
    assert all(step.status == "completed" for step in run.steps)


def test_generation_uses_structured_llm_runtime_for_all_five_stages(tmp_path: Path):
    model = ScriptedModel()
    services = build_v2_services(
        tmp_path / "workspaces",
        runtime=StructuredModelRuntime(model),
    )
    services.projects.create("robot")

    result = services.generation("robot").generate(
        "robot", requirement_text="系统应支持人工接管"
    )

    assert result.status == "completed"
    assert model.calls == [
        "vertical.requirements",
        "vertical.functional",
        "vertical.logical",
        "vertical.physical",
        "vertical.verification_validation",
    ]
    assert result.traceability.complete_count == 1
