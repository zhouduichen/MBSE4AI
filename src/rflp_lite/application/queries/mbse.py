"""Stable MBSE query view for pages and API presenters."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class MBSEView:
    status: str
    revision: str
    semantic_hash: str
    view_count: int
    element_count: int
    relation_count: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def mbse_view(state: Mapping[str, object] | None, views: tuple[Mapping[str, object], ...] = ()) -> MBSEView:
    model = (state or {}).get("mbse")
    model = model if isinstance(model, Mapping) else {}
    semantic = model.get("semantic_model")
    semantic = semantic if isinstance(semantic, Mapping) else model
    sections = semantic.get("sections", {})
    elements = 0
    if isinstance(sections, Mapping):
        for section in sections.values():
            if isinstance(section, Mapping):
                elements += sum(
                    len(value) for value in section.values() if isinstance(value, (list, tuple))
                )
            elif isinstance(section, (list, tuple)):
                elements += len(section)
    relations = semantic.get("relations", ())
    return MBSEView(
        status=str(model.get("status", "empty")),
        revision=str(model.get("revision", "")),
        semantic_hash=str(semantic.get("model_hash", "")),
        view_count=len(views),
        element_count=elements,
        relation_count=len(relations) if isinstance(relations, (list, tuple)) else 0,
    )
