"""Explicit analysis-gap projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_gaps(model: MbseSemanticModel) -> tuple[object, ...]:
    return model.gaps
