"""Relation projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_relations(model: MbseSemanticModel) -> tuple[object, ...]:
    return model.relations
