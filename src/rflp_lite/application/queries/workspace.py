"""Stable workspace query view."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    name: str
    path: str
    revision: int
    content_revision: int
    requirement_count: int
    accepted_requirement_count: int
    has_rflp: bool
    has_mbse: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def workspace_view(name: str, path: Path | str, state: Mapping[str, object] | None) -> WorkspaceView:
    claims = tuple(
        item for item in (state or {}).get("claims", ()) if isinstance(item, Mapping)
    )
    return WorkspaceView(
        name=str(name),
        path=str(path),
        revision=int((state or {}).get("revision", 0) or 0),
        content_revision=int(
            (state or {}).get("content_revision", (state or {}).get("revision", 0)) or 0
        ),
        requirement_count=len(claims),
        accepted_requirement_count=sum(
            str(item.get("status", "")) == "accepted" for item in claims
        ),
        has_rflp=bool((state or {}).get("rflp")),
        has_mbse=bool((state or {}).get("mbse")),
    )
