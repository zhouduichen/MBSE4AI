import pytest

from rflp_lite.application.requirement_inference import suggest_implicit_requirements
from rflp_lite.application.requirements_workbench import accept_traceable, analyze_artifact, suggest_implicit_constraints
from rflp_lite.domain.errors import AdapterFailure
from rflp_lite.domain.requirements import DocumentRegion


def test_inferred_requirement_requires_known_source():
    region = DocumentRegion("region-1", "artifact-1", 1, "paragraph", "page-1/paragraph-1", "系统支持导入 PDF")

    def complete(_config, _prompt):
        return '[{"source_region_id":"region-1","statement":"关键尺寸应满足工艺能力","entities":["关键尺寸"],"constraints":[["manufacturing","required"]],"verification_method":"analysis","confidence":0.72}]'

    item = suggest_implicit_requirements((region,), {"model": "local"}, complete)[0]
    assert item.source_type == "inferred"
    assert item.producer == "llm"
    assert item.status == "candidate"


def test_unknown_llm_source_is_rejected():
    region = DocumentRegion("region-1", "artifact-1", 1, "paragraph", "page-1/paragraph-1", "原文")

    def complete(_config, _prompt):
        return '[{"source_region_id":"missing","statement":"约束","entities":[],"constraints":[],"verification_method":"inspection","confidence":0.6}]'

    with pytest.raises(AdapterFailure, match="source_region_id"):
        suggest_implicit_requirements((region,), {"model": "local"}, complete)


def test_inferred_requirement_is_not_bulk_accepted():
    state = analyze_artifact("requirements.txt", "系统应满足隐含工艺约束。".encode())
    region_id = state["document_regions"][0]["id"]

    def complete(_config, _prompt):
        return '[{"source_region_id":"' + region_id + '","statement":"关键尺寸应满足工艺能力","entities":["关键尺寸"],"constraints":[],"verification_method":"analysis","confidence":0.72}]'

    state = suggest_implicit_constraints(state, {"model": "local"}, complete)
    state = accept_traceable(state)
    inferred = next(item for item in state["structured_requirements"] if item["source_type"] == "inferred")
    assert inferred["status"] == "candidate"
