"""Read-only Workbench snapshots."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from rflp_lite.domain.canonical import canonical_hash


@dataclass(frozen=True, slots=True)
class WorkbenchSnapshot:
    workspace: str
    revision: int
    content_revision: int
    input_hash: str
    state: Mapping[str, object]

    @classmethod
    def from_state(cls, workspace: str, state: Mapping[str, object]) -> "WorkbenchSnapshot":
        copied = deepcopy(dict(state))
        revision = int(copied.get("revision", 0) or 0)
        content_revision = int(
            copied.get("content_revision", revision) or 0
        )
        input_hash = str(copied.get("input_hash") or canonical_hash(copied))
        return cls(
            workspace=workspace,
            revision=revision,
            content_revision=content_revision,
            input_hash=input_hash,
            state=MappingProxyType(copied),
        )

    def working_copy(self) -> dict[str, object]:
        """Return an independent mutable copy for a Mutation."""
        return deepcopy(dict(self.state))
