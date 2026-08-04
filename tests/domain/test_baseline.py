from dataclasses import FrozenInstanceError

import pytest

from rflp_lite.domain.baseline import approve_baseline
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import ModelElement, Relation


def test_baseline_is_immutable_and_hash_is_reproducible():
    element = ModelElement("req-1", "R", "Restore a version")
    first = approve_baseline((element,), ())
    second = approve_baseline((element,), ())
    assert first.hash == second.hash == canonical_hash(first.payload)
    with pytest.raises(FrozenInstanceError):
        first.hash = "changed"  # type: ignore[misc]


def test_baseline_rejects_unknown_relation_target():
    element = ModelElement("req-1", "R", "Restore a version")
    relation = Relation("rel-1", "req-1", "satisfiedBy", "fn-missing")
    with pytest.raises(InvariantViolation, match="unknown element"):
        approve_baseline((element,), (relation,))

