from dataclasses import replace

from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import TransportFailure
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.controller import (
    ControllerAction,
    ControllerPlan,
    ControllerProposal,
)
from rflp_lite.methodology.engine import MethodologyFinding, MethodologyReport
from rflp_lite.methodology.llm_controller import LLMController
from rflp_lite.ports.generative_model import GenerationResponse


class RecordingModel:
    provider_id = "remote-provider"
    model_id = "remote-model"

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        payload = self.payload
        if payload is None:
            action = request.user_payload["controller_plan"]["actions"][0]
            payload = {
                "action_id": action["id"],
                "option_id": action["options"][0]["id"],
                "rationale": "先比较候选方案，再重新验证受影响需求。",
                "assumptions": ["当前约束仍然有效"],
                "open_questions": ["是否允许调整资源预算"],
            }
        return GenerationResponse(
            request.lens_id,
            payload,
            "request-hash",
            "response-hash",
            False,
            self.provider_id,
            self.model_id,
        )


def _graph(entity_count=60):
    entities = tuple(
        make_entity(EntityKind.REQUIREMENT, f"需求 {index}")
        for index in range(entity_count)
    )
    return ModelGraph("robot", entities, revision=7)


def _plan(option_count=10):
    options = tuple(
        {"id": f"trade-option-{index}", "option": f"候选方案 {index}"}
        for index in range(option_count)
    )
    action = ControllerAction(
        "controller-action-trade",
        "trade_study",
        "allocation_tradeoff",
        "physical",
        "P0",
        ("requirement-1",),
        "物理资源存在冲突",
        options,
    )
    return ControllerPlan("needs_action", "推进模型", actions=(action,))


def _report():
    findings = tuple(
        MethodologyFinding(
            f"finding-{index}",
            "error",
            "physical",
            tuple(f"entity-{item}" for item in range(20)),
            f"发现 {index}",
            ("allocation_tradeoff",),
            tuple((f"entity-{item}",) for item in range(30)),
        )
        for index in range(15)
    )
    return MethodologyReport(
        findings=findings,
        metrics={"physical_conflict_count": 15},
        impacted_entity_ids=tuple(f"entity-{index}" for index in range(40)),
        impacted_stages=("physical",),
        recommended_tasks=("allocation_tradeoff",),
        impact_paths=tuple((f"entity-{index}",) for index in range(30)),
    )


def test_controller_plan_serializes_optional_llm_proposal():
    proposal = ControllerProposal(
        "proposed",
        "controller-action-1",
        "trade-option-1",
        "先比较替代架构，再重新验证受影响需求。",
        ("功耗实测值仍需确认",),
        ("是否允许更换计算平台",),
        (),
        "input-hash",
        "output-hash",
        "openai-compatible",
        "remote-model",
    )
    plan = ControllerPlan(
        "needs_action",
        "推进模型",
        actions=(ControllerAction(
            "controller-action-1", "trade_study", "allocation_tradeoff",
            "physical", "P0", ("physical-1",), "物理冲突",
            ({"id": "trade-option-1", "option": "替代候选"},),
        ),),
        proposal=proposal,
    )

    payload = plan.as_dict()

    assert payload["llm_proposal"]["status"] == "proposed"
    assert payload["llm_proposal"]["action_id"] == "controller-action-1"
    assert payload["llm_proposal"]["option_id"] == "trade-option-1"
    assert payload["actions"][0]["id"] == "controller-action-1"


def test_llm_controller_accepts_only_ids_from_deterministic_plan():
    graph = _graph()
    model = RecordingModel()
    proposal = LLMController(model).propose(graph, _report(), _plan())

    request = model.requests[0]
    assert proposal.status == "proposed"
    assert request.lens_id == "controller.proposal"
    assert set(request.user_payload) == {"context", "methodology", "controller_plan"}
    assert len(request.user_payload["context"]["entities"]) <= 48
    assert len(request.user_payload["context"]["relations"]) <= 96
    assert len(request.user_payload["methodology"]["findings"]) <= 12
    assert len(request.user_payload["methodology"]["impact_paths"]) <= 24
    assert len(request.user_payload["controller_plan"]["actions"]) <= 8
    assert len(request.user_payload["controller_plan"]["actions"][0]["options"]) <= 8
    assert request.user_payload["context"]["revision"] == graph.revision
    assert request.user_payload["context"]["snapshot_hash"] == graph.snapshot_hash
    assert graph.revision == 7


def test_llm_controller_rejects_unknown_action_without_mutation():
    graph = _graph()
    model = RecordingModel({
        "action_id": "controller-action-unknown",
        "option_id": None,
        "rationale": "越权建议",
        "assumptions": [],
        "open_questions": [],
    })

    proposal = LLMController(model).propose(graph, _report(), _plan())

    assert proposal.status == "fallback"
    assert "unknown_action" in proposal.diagnostics[0]
    assert graph.revision == 7


def test_llm_controller_rejects_unknown_trade_option_without_mutation():
    graph = _graph()
    model = RecordingModel({
        "action_id": "controller-action-trade",
        "option_id": "trade-option-unknown",
        "rationale": "越权选项",
        "assumptions": [],
        "open_questions": [],
    })

    proposal = LLMController(model).propose(graph, _report(), _plan())

    assert proposal.status == "fallback"
    assert "unknown_trade_option" in proposal.diagnostics[0]
    assert graph.revision == 7


def test_llm_controller_returns_fallback_on_transport_failure():
    graph = _graph()
    model = RecordingModel(
        error=TransportFailure(
            "remote unavailable",
            code="network_error",
            provider_id="remote",
            model_id="model",
            raw_response="x" * 12000,
        )
    )

    proposal = LLMController(model).propose(graph, _report(), _plan())

    assert proposal.status == "fallback"
    assert proposal.diagnostics == ("controller_proposal_network_error",)
    assert all(len(item) < 256 for item in proposal.diagnostics)
    assert graph.revision == 7


def test_llm_controller_skips_provider_when_unconfigured_or_no_action():
    graph = _graph()
    model = RecordingModel()

    unconfigured = LLMController(None).propose(graph, _report(), _plan())
    no_action = LLMController(model).propose(
        graph,
        _report(),
        replace(_plan(), actions=()),
    )

    assert unconfigured.status == "not_configured"
    assert no_action.status == "not_needed"
    assert model.requests == []
