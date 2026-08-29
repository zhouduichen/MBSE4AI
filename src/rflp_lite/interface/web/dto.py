"""Pydantic transport DTOs converted to application commands at the edge."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class RequirementReviewRequest(_RequestModel):
    group: str
    item_id: str
    status: str = Field(min_length=1)
    value: str = ""
    category: str = ""
    expected_revision: int | None = None


class EntityDeletionRequest(_RequestModel):
    entity_type: str
    entity_id: str
    plan_hash: str = ""


class EntityRestoreRequest(_RequestModel):
    entity_type: str
    entity_id: str


class ScenarioRequest(_RequestModel):
    title: str
    description: str = ""
    steps: list[str] = Field(default_factory=list)
    expected_outcomes: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


def to_application_payload(model: BaseModel) -> dict[str, object]:
    """Convert a validated transport object before leaving Interface."""

    return model.model_dump(exclude_none=True)


__all__ = [
    "EntityDeletionRequest",
    "EntityRestoreRequest",
    "RequirementReviewRequest",
    "ScenarioRequest",
    "to_application_payload",
]
