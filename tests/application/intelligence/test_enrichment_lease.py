from __future__ import annotations

import time

from rflp_lite.application.intelligence.enrichment_jobs import EnrichmentJobRunner
from rflp_lite.application.web_facade import WebFacade
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.ports.generative_model import GenerationResponse


class SlowModel:
    model_id = "slow-test"

    def complete_json(self, request):
        time.sleep(1.2)
        payload = {"items": [], "diagnostics": []}
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
            provider_id="test",
            model_id=self.model_id,
        )


def test_long_local_generation_keeps_job_lease_alive(tmp_path):
    facade = WebFacade(tmp_path / "workspaces")
    facade.create_workspace("demo")
    facade._project_analysis_model = lambda: None
    facade.analyze_requirements("demo", "requirements.txt", "系统应支持备份。".encode())
    runner = EnrichmentJobRunner(facade.workspace("demo").path)
    runner.jobs.lease_seconds = 0.5

    result = runner.run(SlowModel())

    assert result["status"] == "completed"
