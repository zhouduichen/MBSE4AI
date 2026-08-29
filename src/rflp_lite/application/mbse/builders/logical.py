"""Logical-layer projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_logical(model: MbseSemanticModel) -> tuple[object, ...]:
    return model.logical_components
