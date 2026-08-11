from dataclasses import FrozenInstanceError

import pytest

from rflp_lite.domain.discovery import CandidateEnvelope, ProvenanceRef


def test_candidate_identity_is_deterministic_and_source_aware():
    source = ProvenanceRef("explicit", "region-1", "用户原文")
    first = CandidateEnvelope.create(
        element_type="stakeholder",
        pack_id="urban-medical-aam-v1",
        payload={"name": "急救医生", "category": "medical_staff"},
        provenance=(source,),
        producer="rule",
    )
    second = CandidateEnvelope.create(
        element_type="stakeholder",
        pack_id="urban-medical-aam-v1",
        payload={"category": "medical_staff", "name": "急救医生"},
        provenance=(source,),
        producer="rule",
    )
    assert first == second
    assert first.id.startswith("candidate-")
    assert first.as_dict()["payload"]["name"] == "急救医生"


def test_candidate_rejects_unknown_source_and_is_immutable():
    with pytest.raises(ValueError, match="source_type"):
        ProvenanceRef("guess", "region-1")
    item = CandidateEnvelope.create(
        element_type="mission",
        pack_id="urban-medical-aam-v1",
        payload={"name": "城市医疗运输"},
        provenance=(ProvenanceRef("inferred", "lens-mission"),),
        producer="llm",
    )
    with pytest.raises(FrozenInstanceError):
        item.status = "accepted"


def test_candidate_rejects_unknown_review_status():
    with pytest.raises(ValueError, match="status"):
        CandidateEnvelope.create(
            element_type="mission",
            pack_id="urban-medical-aam-v1",
            payload={"name": "城市医疗运输"},
            provenance=(ProvenanceRef("explicit", "region-1"),),
            producer="rule",
            status="published",
        )


def test_candidate_confidence_is_bounded():
    with pytest.raises(ValueError, match="confidence"):
        CandidateEnvelope.create(
            element_type="risk",
            pack_id="urban-medical-aam-v1",
            payload={"name": "低能见度"},
            provenance=(ProvenanceRef("inferred", "lens-risk"),),
            producer="llm",
            confidence=1.2,
        )
