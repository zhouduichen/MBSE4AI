from dataclasses import FrozenInstanceError

import pytest

from rflp_lite.ports.generative_model import GenerationRequest


def test_generation_request_is_immutable():
    request = GenerationRequest("stakeholders", "JSON", {}, {"type": "object"})
    with pytest.raises(FrozenInstanceError):
        request.lens_id = "other"
