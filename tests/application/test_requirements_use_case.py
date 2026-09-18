from pathlib import Path

from rflp_lite.application.requirements_use_case import RequirementsUseCaseService
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, EntityStatus, Producer
from rflp_lite.ports.generative_model import GenerationResponse
from rflp_lite.repository.sqlite import SQLiteModelRepository


def _payload() -> dict[str, object]:
    return {
        "schema_version": "requirements-use-case-draft.v1",
        "source_document_ids": ["doc-1"],
        "system_context": {
            "name": "城市巡检系统",
            "mission": "执行城市巡检并上报告警",
            "source_refs": ["region-1"],
        },
        "entities": [{
            "local_ref": "actor_operator",
            "kind": "stakeholder",
            "name": "操作员",
            "attributes": {"role": "任务执行者"},
            "source_refs": ["region-1"],
            "confidence": 0.9,
        }],
        "requirements": [
            {
                "local_ref": "req_latency",
                "statement": "系统时延不得超过 2 s",
                "level": "system",
                "type": "performance",
                "obligation": "系统应",
                "verification_method": "test",
                "constraints": [{
                    "field": "latency_ms",
                    "operator": "max",
                    "value": 5000,
                    "unit": "ms",
                    "source": "llm_inferred",
                    "source_refs": ["region-1"],
                    "confidence": 0.4,
                    "assumption": "响应应较快",
                }],
                "source_refs": ["region-1"],
                "confidence": 0.85,
                "related_refs": [],
            },
            {
                "local_ref": "req_report",
                "statement": "系统应上报告警",
                "level": "system",
                "type": "functional",
                "obligation": "系统应",
                "verification_method": "review",
                "constraints": [],
                "source_refs": ["region-1"],
                "confidence": 0.8,
                "related_refs": [],
            },
            {
                "local_ref": "req_control",
                "statement": "系统应支持人工接管",
                "level": "system",
                "type": "functional",
                "obligation": "系统应",
                "verification_method": "test",
                "constraints": [],
                "source_refs": ["region-1"],
                "confidence": 0.8,
                "related_refs": [],
            },
        ],
        "use_cases": [{
            "local_ref": "uc_monitor",
            "name": "执行城市巡检",
            "goal": "完成巡检并上报告警",
            "primary_actor_refs": ["actor_operator"],
            "preconditions": [],
            "postconditions": ["告警已上报"],
            "scenario_refs": ["scenario_monitor"],
            "requirement_refs": ["req_latency", "req_report"],
            "source_refs": ["region-1"],
            "confidence": 0.8,
        }],
        "scenarios": [{
            "local_ref": "scenario_monitor",
            "kind": "operational_scenario",
            "name": "发现目标并上报",
            "description": "操作员下达任务，系统采集数据并上报",
            "actor_refs": ["actor_operator"],
            "steps": [
                {"order": 1, "actor_ref": "actor_operator", "action": "下达巡检任务", "guard": ""},
                {"order": 2, "actor_ref": "system", "action": "采集数据并上报告警", "guard": "发现异常"},
            ],
            "branches": [{"condition": "数据不可用", "target_order": 1, "action": "报告异常"}],
            "requirement_refs": ["req_report"],
            "source_refs": ["region-1"],
            "confidence": 0.75,
        }],
        "clarifications": [],
        "diagnostics": [],
    }


class FakeModel:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload
        self.requests = []

    def complete_json(self, request):
        self.requests.append(request)
        return GenerationResponse(
            request.lens_id,
            self.payload,
            canonical_hash(request.user_payload),
            canonical_hash(self.payload),
            False,
            "jiayuinter-vllm",
            "qwen3.5-controller",
        )


class InvalidModel:
    def complete_json(self, request):
        return GenerationResponse(
            request.lens_id,
            {"not": "a draft"},
            "input",
            "output",
            False,
            "remote",
            "bad-model",
        )


def _repository(tmp_path: Path) -> SQLiteModelRepository:
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.save_document("p1", {"id": "doc-1", "kind": "txt", "path": "brief.txt"})
    repository.save_source_regions(
        "p1",
        ({"id": "region-1", "document_id": "doc-1", "page": 1, "locator": "p1", "text": "系统时延不得超过 2 s；系统应上报告警；系统应支持人工接管"},),
    )
    repository.save_evidence(
        "p1",
        {"id": "region-1", "source_type": "document_region", "source_id": "doc-1", "locator": "p1", "claim": "brief", "excerpt": "系统时延不得超过 2 s"},
    )
    return repository


def test_llm_draft_merges_explicit_constraints_and_preserves_remote_metadata(tmp_path: Path):
    repository = _repository(tmp_path)
    model = FakeModel(_payload())
    service = RequirementsUseCaseService(
        repository,
        "p1",
        model=model,
        profile_id="jiayuinter-vllm",
        provider_id="openai-compatible",
        model_id="qwen3.5-controller",
    )

    draft = service.create_draft(document_ids=("doc-1",))

    assert draft.status == "completed"
    assert draft.provider_id == "jiayuinter-vllm"
    assert model.requests[0].lens_id == "requirements.use_case"
    requirement = next(item for item in draft.payload["requirements"] if item["local_ref"] == "req_latency")
    assert requirement["constraints"][0]["value"] == 2000.0
    assert requirement["constraints"][0]["source"] == "explicit"
    assert any("explicit-wins" in item for item in draft.diagnostics)


def test_apply_draft_creates_traceable_behavior_and_is_idempotent(tmp_path: Path):
    repository = _repository(tmp_path)
    service = RequirementsUseCaseService(repository, "p1", model=FakeModel(_payload()))
    draft = service.create_draft(document_ids=("doc-1",))

    first = service.apply_draft(draft)
    second = service.apply_draft(draft)
    graph = repository.load_graph("p1")

    assert first["applied"] is True
    assert second["idempotent"] is True
    assert len([item for item in graph.entities if item.kind is EntityKind.REQUIREMENT]) == 3
    assert len([item for item in graph.entities if item.kind is EntityKind.USE_CASE]) == 1
    assert len([item for item in graph.entities if item.kind is EntityKind.OPERATIONAL_SCENARIO]) == 1
    assert len([item for item in graph.entities if item.kind is EntityKind.ACTIVITY]) == 2
    assert all(item.meta.status is EntityStatus.CANDIDATE for item in graph.entities if item.meta.producer is Producer.LLM)
    assert any(item.kind is EntityKind.EVIDENCE for item in graph.entities)
    assert any(item.predicate.value == "participatesIn" for item in graph.relations)


def test_rule_fallback_is_explicitly_degraded_but_produces_use_case_framework(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    service = RequirementsUseCaseService(repository, "p1")

    draft = service.create_draft(text="操作员应能在 2 秒内接收告警；系统应支持人工接管")
    result = service.apply_draft(draft)
    graph = repository.load_graph("p1")

    assert draft.status == "degraded"
    assert any("model_unavailable" in item for item in draft.diagnostics)
    assert result["created_entity_count"] >= 4
    assert any(item.kind is EntityKind.USE_CASE for item in graph.entities)
    assert any(item.kind is EntityKind.ACTIVITY for item in graph.entities)
    assert all(
        item.meta.producer is Producer.RULE
        for item in graph.entities
        if item.kind is not EntityKind.EVIDENCE
    )


def test_invalid_structured_model_output_degrades_without_writing_invalid_json(tmp_path: Path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    draft = RequirementsUseCaseService(repository, "p1", model=InvalidModel()).create_draft(
        text="系统应支持人工接管"
    )

    assert draft.status == "degraded"
    assert any("schema-invalid" in item for item in draft.diagnostics)
    assert draft.payload["schema_version"] == "requirements-use-case-draft.v1"
