from __future__ import annotations

from rflp_lite.application.mbse.builders.context import MbseSemanticModel
from rflp_lite.application.mbse.builders.functional import build_functional
from rflp_lite.application.mbse.builders.gaps import build_gaps
from rflp_lite.application.mbse.builders.interfaces import build_interfaces
from rflp_lite.application.mbse.builders.logical import build_logical
from rflp_lite.application.mbse.builders.operational import build_operational
from rflp_lite.application.mbse.builders.physical import build_physical
from rflp_lite.application.mbse.builders.relations import build_relations
from rflp_lite.application.mbse.builders.requirements import build_requirements
from rflp_lite.application.mbse.pipeline import build_typed_mbse_semantic_model


def test_typed_builder_pipeline_preserves_semantic_sections_and_hash() -> None:
    state = {
        "revision": 1,
        "project_scope": {"workspace": "demo", "input_hash": "input-1"},
        "document_regions": [{"id": "region-1", "text": "系统必须安全运行"}],
        "structured_requirements": [
            {
                "id": "req-1",
                "statement": "系统必须安全运行",
                "status": "accepted",
                "verification_method": "analysis",
                "source_region_id": "region-1",
            }
        ],
        "stakeholders": [],
        "concerns": [],
        "needs": [],
        "scenarios": [],
        "discovery": {},
    }
    typed = build_typed_mbse_semantic_model(state, revision=1, provenance={"producer": "test"})

    assert isinstance(typed, MbseSemanticModel)
    assert build_operational(typed)
    assert build_requirements(typed)
    assert build_functional(typed) == ()
    assert build_logical(typed) == ()
    assert build_physical(typed) == ()
    assert build_interfaces(typed) == ()
    assert build_relations(typed)
    assert build_gaps(typed)
    assert typed.as_dict()["model_hash"]
