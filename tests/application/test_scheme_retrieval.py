import pytest

from rflp_lite.application.scheme_retrieval import find_similar_schemes
from rflp_lite.domain.concept_design import IndicatorEnvelope, SchemeRecord


@pytest.fixture()
def pack() -> dict[str, object]:
    return {
        "id": "test",
        "version": 1,
        "parameters": [
            {"name": "mass_kg", "unit": "kg", "type": "number", "required": True, "minimum": 0, "maximum": 1000},
            {"name": "layout", "unit": "1", "type": "string", "required": True},
        ],
        "retrieval": {
            "features": [
                {"parameter": "mass_kg", "weight": 1.0},
                {"parameter": "layout", "weight": 0.5},
            ]
        },
    }


@pytest.fixture()
def envelope() -> IndicatorEnvelope:
    return IndicatorEnvelope(
        id="T-E-1",
        object_type="layout",
        schema_version=1,
        domain_pack_id="test",
        domain_pack_version=1,
        revision=1,
        status="draft",
        source_requirement_ids=(),
        parameters=(("layout", "baseline"), ("mass_kg", 100.0)),
        bounds=(),
        input_hash="input",
    )


def _scheme(identifier: str, mass: float, layout: str = "baseline") -> SchemeRecord:
    return SchemeRecord(
        id=identifier,
        object_type="layout",
        schema_version=1,
        domain_pack_id="test",
        domain_pack_version=1,
        revision=1,
        status="imported",
        source="fixture",
        parameters=(("layout", layout), ("mass_kg", mass)),
        extensions=(),
        content_hash=identifier,
    )


def test_similarity_is_deterministic_and_explained(pack, envelope):
    schemes = (
        _scheme("scheme-far", 900.0, "alternate"),
        _scheme("scheme-nearest", 120.0),
        _scheme("scheme-middle", 500.0),
    )
    first = find_similar_schemes(pack, envelope, schemes, limit=3)
    second = find_similar_schemes(pack, envelope, tuple(reversed(schemes)), limit=3)

    assert first == second
    assert first[0].scheme_id == "scheme-nearest"
    assert dict(first[0].feature_differences)["mass_kg"] == pytest.approx(0.02)
    assert 0.0 <= first[0].similarity <= 1.0
    assert first[0].missing_features == ()


def test_missing_feature_is_explicit_and_penalized(pack, envelope):
    missing = _scheme("scheme-missing", 100.0)
    missing = SchemeRecord(
        id=missing.id,
        object_type=missing.object_type,
        schema_version=missing.schema_version,
        domain_pack_id=missing.domain_pack_id,
        domain_pack_version=missing.domain_pack_version,
        revision=missing.revision,
        status=missing.status,
        source=missing.source,
        parameters=(("mass_kg", 100.0),),
        extensions=missing.extensions,
        content_hash=missing.content_hash,
    )
    match = find_similar_schemes(pack, envelope, (missing,))[0]
    assert match.missing_features == ("layout",)
    assert dict(match.feature_differences)["layout"] == 1.0
    assert match.similarity == pytest.approx(1.0 / 1.5)


def test_zero_limit_returns_no_matches(pack, envelope):
    assert find_similar_schemes(pack, envelope, (_scheme("one", 100.0),), limit=0) == ()
