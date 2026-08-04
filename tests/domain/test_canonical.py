from hypothesis import given, strategies as st

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import ModelElement


@given(st.text(min_size=1, max_size=30))
def test_equivalent_elements_have_same_hash(name):
    first = ModelElement("req-1", "R", name)
    second = ModelElement("req-1", "R", name)
    assert canonical_hash(first) == canonical_hash(second)

