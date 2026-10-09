import pytest

from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.methodology.registries import ValidatorRegistry


def test_validator_registry_preserves_routable_methodology_errors():
    registry = ValidatorRegistry({
        "semantic": lambda _subject: (_ for _ in ()).throw(
            MethodologyValidationError("semantic_invalid", "invalid function name")
        ),
    })

    with pytest.raises(MethodologyValidationError) as error:
        registry.validate(("semantic",), value={})

    assert error.value.code == "semantic_invalid"


def test_validator_registry_wraps_untyped_validator_errors():
    registry = ValidatorRegistry({
        "broken": lambda _subject: (_ for _ in ()).throw(ValueError("bad validator")),
    })

    with pytest.raises(MethodologyValidationError) as error:
        registry.validate(("broken",), value={})

    assert error.value.code == "validator_failed"
