"""Stable RFLP domain kernel."""

from rflp_lite.domain.requirements import (
    Diagnostic,
    DocumentRegion,
    StructuredRequirement,
    TraceLink,
)
from rflp_lite.domain.mbse import Actor, Activity, Lifeline, Message, UseCase
from rflp_lite.domain.entities import Entity, EntityKind, EntityMeta, EntityStatus, Producer, make_entity
from rflp_lite.domain.model import (
    AddEntity, Deprecate, ModelGraph, Patch, Relation, Relate, Revision, UpdateEntity,
)
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.domain.requirements import Metric, Requirement
from rflp_lite.domain.concept_design import (
    ConstraintResult,
    DisciplineEvaluation,
    IndicatorEnvelope,
    LayoutCandidate,
    OptimizationRun,
    SchemeRecord,
    SimilarityMatch,
)

__all__ = [
    "Actor", "Activity", "Diagnostic", "DocumentRegion", "Lifeline", "Message",
    "StructuredRequirement", "TraceLink", "UseCase",
    "Entity", "EntityKind", "EntityMeta", "EntityStatus", "Producer", "make_entity",
    "AddEntity", "Deprecate", "ModelGraph", "Patch", "Relation", "Relate", "Revision", "UpdateEntity",
    "RelationPredicate", "Metric", "Requirement",
    "ConstraintResult", "DisciplineEvaluation", "IndicatorEnvelope",
    "LayoutCandidate", "OptimizationRun", "SchemeRecord", "SimilarityMatch",
]
