"""Operational-layer projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_operational(model: MbseSemanticModel) -> object:
    return model.sections.get("operational", {})
