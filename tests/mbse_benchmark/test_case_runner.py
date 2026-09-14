from __future__ import annotations

from tests.mbse_benchmark.runners.case_runner import _run_analysis


class _GenerationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def generate(self, project_id: str, *, document_ids: tuple[str, ...], force_new: bool) -> str:
        assert force_new is True
        self.calls.append((project_id, document_ids))
        return "vertical-result"


class _AnalysisService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, project_id: str, *, force_new: bool) -> str:
        assert force_new is True
        self.calls.append(project_id)
        return "lifecycle-result"


class _Services:
    def __init__(self) -> None:
        self.generation_service = _GenerationService()
        self.analysis_service = _AnalysisService()

    def generation(self, project_id: str) -> _GenerationService:
        return self.generation_service

    def analysis(self, project_id: str) -> _AnalysisService:
        return self.analysis_service


def test_vertical_benchmark_path_calls_product_generation_service() -> None:
    services = _Services()

    result = _run_analysis(
        services,
        "case-04",
        {"document_id": "document-case-04", "region_count": 3},
        {"provider": "remote"},
        "vertical",
    )

    assert result == "vertical-result"
    assert services.generation_service.calls == [("case-04", ("document-case-04",))]
    assert services.analysis_service.calls == []


def test_vertical_benchmark_path_does_not_treat_fixture_id_as_readable_document() -> None:
    services = _Services()

    result = _run_analysis(
        services,
        "case-04",
        {"document_id": "fixture-case-04", "region_count": 0},
        {"provider": "remote"},
        "vertical",
    )

    assert result == "vertical-result"
    assert services.generation_service.calls == [("case-04", ())]


def test_lifecycle_benchmark_path_keeps_legacy_workflow_entrypoint() -> None:
    services = _Services()

    result = _run_analysis(services, "case-04", {}, None, "lifecycle")

    assert result == "lifecycle-result"
    assert services.analysis_service.calls == ["case-04"]
    assert services.generation_service.calls == []
