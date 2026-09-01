import time
from pathlib import Path

from rflp_lite.application.intelligence.enrichment_jobs import EnrichmentJobRunner
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.ports.generative_model import GenerationResponse


class FakeModel:
    def __init__(self):
        self.calls = []

    def complete_json(self, request):
        block_id = request.user_payload["block_id"]
        self.calls.append(block_id)
        if block_id == "requirements":
            raise AdapterFailure("requirements failed")
        if block_id == "scenarios":
            return GenerationResponse(
                request.lens_id,
                {"items": [{"id": "normal", "title": "正常运行", "scenario_type": "normal"}], "diagnostics": []},
                canonical_hash(request.user_payload),
                canonical_hash({"items": []}),
                False,
            )
        items = [{"id": "operator", "name": "运营人员", "category": "operator"}] if block_id == "stakeholders" else []
        payload = {"items": items, "diagnostics": []}
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
        )


def _runner(tmp_path: Path) -> EnrichmentJobRunner:
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("demo")
    facade._project_analysis_model = lambda: None
    facade.analyze_requirements("demo", "requirements.txt", "系统应支持备份。".encode())
    workspace = facade.workspace("demo")
    return EnrichmentJobRunner(workspace.path)


def _wait(runner: EnrichmentJobRunner, job_id: str):
    for _ in range(100):
        job = runner.jobs.get(job_id)
        if job and job.get("status") in {"completed", "degraded", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_enrichment_job_isolates_failed_blocks(tmp_path):
    runner = _runner(tmp_path)
    first = runner.run(FakeModel())
    assert first["status"] == "degraded"
    assert first["blocks"]["stakeholders"] == "succeeded"
    assert first["blocks"]["requirements"] == "failed"
    assert first["blocks"]["scenarios"] == "succeeded"


def test_retry_does_not_duplicate_successful_block(tmp_path):
    runner = _runner(tmp_path)
    model = FakeModel()
    first = runner.run(model)
    retry = runner.retry(first["id"], model)
    second = _wait(runner, str(retry["id"]))
    assert second["blocks"]["stakeholders"] == "succeeded"
    assert len(second.get("merged_item_ids", [])) == len(set(second.get("merged_item_ids", [])))
    assert model.calls.count("stakeholders") == 1


class RuntimeErrorModel:
    model_id = "runtime-error"

    def complete_json(self, _request):
        raise RuntimeError("provider runtime failure")


class TypoSourceModel:
    model_id = "typo-source-test"

    def complete_json(self, request):
        region_id = request.user_payload["allowed_source_region_ids"][0]
        typo = region_id[:-2] + "c8e7"
        block_id = request.user_payload["block_id"]
        item = {
            "id": "inferred-1",
            "statement": "系统应支持备份",
            "subject": "系统",
            "predicate": "应",
            "verification_method": "analysis",
            "source_region_ids": [typo],
            "confidence": 0.8,
        }
        payload = {
            "items": [item] if block_id == "requirements" else [],
            "diagnostics": [],
        }
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
            provider_id="test",
            model_id=self.model_id,
        )


def test_single_source_typo_is_repaired_before_semantic_validation(tmp_path):
    runner = _runner(tmp_path)

    result = runner.run(TypoSourceModel())

    assert result["status"] == "completed"
    state = runner._load_state()
    assert any(
        item.get("code") == "source_region_repaired"
        for item in state["auto_analysis"]["diagnostics"]
    )


def test_unclassified_provider_error_persists_degraded_workbench_state(tmp_path):
    runner = _runner(tmp_path)

    result = runner.run(RuntimeErrorModel())
    job = runner.jobs.get(str(result["id"]))
    state = runner._load_state()

    assert result["status"] == "degraded"
    assert job is not None
    assert job["status"] == "degraded"
    assert state["auto_analysis"]["status"] == "degraded"
    assert any(
        item.get("code") == "llm_block_failed"
        for item in state["auto_analysis"]["diagnostics"]
    )
