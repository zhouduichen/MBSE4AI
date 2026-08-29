"""Functional-layer projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_functional(model: MbseSemanticModel) -> tuple[object, ...]:
    return model.functions
