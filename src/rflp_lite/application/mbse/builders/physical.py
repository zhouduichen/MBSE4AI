"""Physical-layer projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_physical(model: MbseSemanticModel) -> tuple[object, ...]:
    return model.physical_components
