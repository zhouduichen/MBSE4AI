"""Interface projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_interfaces(model: MbseSemanticModel) -> tuple[object, ...]:
    return model.interfaces
