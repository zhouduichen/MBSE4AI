"""Typed results returned by Workbench mutations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from rflp_lite.domain.requirements import Diagnostic


class MutationKind(StrEnum):
    HUMAN_CONTENT = "human_content"
    GENERATED_CONTENT = "generated_content"
    DERIVED_MODEL = "derived_model"
    METADATA = "metadata"


@dataclass(frozen=True, slots=True)
class MutationResult:
    state: dict[str, object]
    changed_ids: tuple[str, ...] = ()
    invalidated_sections: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    mutation_kind: MutationKind = MutationKind.HUMAN_CONTENT


WorkbenchMutation = Callable[[dict[str, object]], MutationResult]


__all__ = ["MutationKind", "MutationResult", "WorkbenchMutation"]
