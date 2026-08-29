"""Requirement-layer projection."""

from rflp_lite.application.mbse.builders.context import MbseSemanticModel


def build_requirements(model: MbseSemanticModel) -> object:
    functional = model.sections.get("functional", {})
    return functional.get("requirements", ()) if isinstance(functional, dict) else ()
