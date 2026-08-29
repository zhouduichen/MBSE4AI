"""Stable read model for the requirements ledger."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RequirementItemView:
    id: str
    text: str
    status: str
    status_label: str
    source_label: str
    is_current: bool
    source_type: str = ""
    source_locator: str = ""

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RequirementsPageView:
    workspace: str
    total: int
    submitted: int
    current: int
    counts: Mapping[str, int]
    items: tuple[RequirementItemView, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace": self.workspace,
            "total": self.total,
            "submitted": self.submitted,
            "current": self.current,
            "counts": dict(self.counts),
            "items": tuple(item.as_dict() for item in self.items),
        }


def requirements_page_view(
    state: Mapping[str, object] | None,
    records: tuple[Mapping[str, object], ...] = (),
    *,
    workspace: str = "",
) -> RequirementsPageView:
    """Build a view from ledger records without mutating the Workbench."""

    current_ids = {
        str(item.get("id", ""))
        for item in (state or {}).get("claims", ())
        if isinstance(item, Mapping)
    }
    labels = {
        "candidate": "待确认",
        "accepted": "已接受",
        "rejected": "已驳回",
        "deleted": "已删除",
    }
    source_labels = {
        "need": "利益相关方需求",
        "constraint": "约束 / 质量属性",
        "goal": "系统目标",
        "problem": "问题 / 痛点",
        "provisional": "待分类输入",
    }
    items = tuple(
        RequirementItemView(
            id=str(record.get("id", "")),
            text=str(record.get("object", record.get("statement", ""))),
            status=str(record.get("status", "candidate")),
            status_label=str(
                record.get("status_label", labels.get(str(record.get("status", "candidate")), ""))
            ),
            source_label=str(
                record.get(
                    "source_label",
                    source_labels.get(str(record.get("source_type", "")), "自然语言输入"),
                )
            ),
            is_current=bool(record.get("is_current", str(record.get("id", "")) in current_ids)),
            source_type=str(record.get("source_type", "")),
            source_locator=str(record.get("source_locator", record.get("span_id", ""))),
        )
        for record in sorted(records, key=lambda item: str(item.get("id", "")))
        if str(record.get("id", ""))
    )
    counts = MappingProxyType(
        {
            status: sum(item.status == status for item in items)
            for status in ("candidate", "accepted", "rejected")
        }
    )
    return RequirementsPageView(
        workspace=workspace,
        total=len(items),
        submitted=len(items),
        current=sum(item.is_current for item in items),
        counts=counts,
        items=items,
    )
