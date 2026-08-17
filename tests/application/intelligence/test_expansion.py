from dataclasses import replace

from rflp_lite.application.intelligence.expansion import expand_candidates
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


class FakeModel:
    def __init__(self):
        self.lenses = []

    def complete_json(self, request):
        self.lenses.append(request.lens_id)
        element_types = {
            "stakeholders": "stakeholder", "environment": "system_boundary", "lifecycle_use_cases": "lifecycle_phase",
            "scenarios": "operational_scenario", "capabilities_requirements": "capability", "functions": "function",
            "components_solutions": "logical_component", "risks_questions": "risk",
        }
        payloads = {
            "stakeholders": {"name": "急救医生", "category": "medical", "goals": ["稳定患者状态"], "interactions": ["提交医疗任务"]},
            "environment": {"name": "城市医疗飞行汽车边界"},
            "lifecycle_use_cases": {"name": "起飞", "phase_id": "takeoff"},
            "scenarios": {"name": "低能见度转运", "actors": ["急救医生"], "preconditions": ["患者已登机"], "trigger": "收到转运任务", "steps": ["起飞", "巡航", "降落"], "expected_outcome": "患者送达", "scenario_type": "degraded"},
            "capabilities_requirements": {"name": "医疗转运", "outcome": "患者安全送达", "enablers": ["飞行控制"]},
            "functions": {"name": "规划航路", "input": ["任务"], "output": ["航路"]},
            "components_solutions": {"name": "任务计算机", "responsibilities": ["规划航路"], "interfaces": []},
            "risks_questions": {"name": "低能见度运行风险", "cause": "雾", "effect": "态势感知下降", "mitigations": ["降级"]},
        }
        item = {"element_type": element_types[request.lens_id], "payload": payloads[request.lens_id], "source_type": "inferred", "source_id": f"lens-{request.lens_id}", "rationale": "领域分析", "confidence": 0.72, "assumptions": []}
        payload = {"items": [item]}
        return GenerationResponse(request.lens_id, payload, canonical_hash(request.user_payload), canonical_hash(payload), False)


def pack():
    schemas = {
        "stakeholder": {"required": ["name", "category", "goals", "interactions"]}, "system_boundary": {"required": ["name"]},
        "lifecycle_phase": {"required": ["name", "phase_id"]}, "operational_scenario": {"required": ["name", "actors", "preconditions", "trigger", "steps", "expected_outcome", "scenario_type"]},
        "capability": {"required": ["name", "outcome", "enablers"]}, "function": {"required": ["name", "input", "output"]},
        "logical_component": {"required": ["name", "responsibilities", "interfaces"]}, "risk": {"required": ["name", "cause", "effect", "mitigations"]},
    }
    return {"id": "urban-medical-aam-v1", "element_schemas": schemas, "prompt_fragments": {name: name for name, _ in (("stakeholders", ()), ("environment", ()), ("lifecycle_use_cases", ()), ("scenarios", ()), ("capabilities_requirements", ()), ("functions", ()), ("components_solutions", ()), ("risks_questions", ()))}}


def state():
    return {"discovery": {"intake": {"system_name": "城市医疗用途的飞行汽车", "seed_hash": "seed-1"}, "candidate_sets": [], "diagnostics": [], "revision": 1}}


def test_expansion_runs_all_lenses_and_keeps_llm_items_as_candidates():
    model = FakeModel()
    result = expand_candidates(state(), pack(), model)
    assert model.lenses == ["stakeholders", "environment", "lifecycle_use_cases", "scenarios", "capabilities_requirements", "functions", "components_solutions", "risks_questions"]
    items = [item for group in result["discovery"]["candidate_sets"] for item in group["items"]]
    assert items and all(item["status"] == "candidate" for item in items) and all(item["producer"] == "llm" for item in items)


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


def test_expansion_accepts_grouped_element_schema_response():
    class GroupedModel(FakeModel):
        def complete_json(self, request):
            response = super().complete_json(request)
            item = response.payload["items"][0]
            return replace(response, payload={"element_schemas": {item["element_type"]: [item]}})

    result = expand_candidates(state(), pack(), GroupedModel())
    items = [item for group in result["discovery"]["candidate_sets"] for item in group["items"]]
    assert len(items) == 8
