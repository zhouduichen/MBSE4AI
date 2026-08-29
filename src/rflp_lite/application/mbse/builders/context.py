"""Typed context and immutable model wrapper for MBSE building."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class MbseBuildContext:
    state: Mapping[str, object]
    revision: object = None
    provenance: object = None

    @classmethod
    def from_state(
        cls, state: Mapping[str, object], revision: object = None, provenance: object = None
    ) -> "MbseBuildContext":
        return cls(MappingProxyType(deepcopy(dict(state))), revision, provenance)


@dataclass(frozen=True, slots=True)
class MbseSemanticModel:
    """Read-only typed façade over the stable semantic JSON contract."""

    payload: Mapping[str, object]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "MbseSemanticModel":
        return cls(MappingProxyType(deepcopy(dict(payload))))

    @property
    def sections(self) -> Mapping[str, object]:
        sections = self.payload.get("sections", {})
        return sections if isinstance(sections, Mapping) else MappingProxyType({})

    @property
    def functions(self) -> tuple[Mapping[str, object], ...]:
        return _items(self.sections.get("functional"), "functions")

    @property
    def logical_components(self) -> tuple[Mapping[str, object], ...]:
        return _items(self.sections.get("logical"), "components")

    @property
    def physical_components(self) -> tuple[Mapping[str, object], ...]:
        return _items(self.sections.get("physical"), "components")

    @property
    def interfaces(self) -> tuple[Mapping[str, object], ...]:
        logical = _items(self.sections.get("logical"), "interfaces")
        physical = _items(self.sections.get("physical"), "interfaces")
        return logical + tuple(item for item in physical if item not in logical)

    @property
    def relations(self) -> tuple[Mapping[str, object], ...]:
        values = self.payload.get("relations", ())
        return tuple(item for item in values if isinstance(item, Mapping)) if isinstance(values, (list, tuple)) else ()

    @property
    def gaps(self) -> tuple[Mapping[str, object], ...]:
        result: list[Mapping[str, object]] = []
        for section in self.sections.values():
            if isinstance(section, Mapping):
                result.extend(_items(section, "gaps"))
        return tuple(result)

    def as_dict(self) -> dict[str, object]:
        return deepcopy(dict(self.payload))


def _items(section: object, key: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(section, Mapping):
        return ()
    values = section.get(key, ())
    return tuple(item for item in values if isinstance(item, Mapping)) if isinstance(values, (list, tuple)) else ()
