from __future__ import annotations

import re

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import InvariantViolation
from rflp_lite.domain.models import Claim, ModelElement, Relation


def _identifier(prefix: str, *parts: object) -> str:
    return f"{prefix}-{canonical_hash(parts)[:12]}"


def _physical_name(text: str) -> str:
    lowered = text.casefold()
    if any(word in lowered for word in ("航天", "卫星", "火箭", "空间", "飞控", "载荷")):
        return "航天平台 / 地面控制接口"
    if any(word in lowered for word in ("保存", "版本", "审计", "数据", "store", "record", "version")):
        return "SQLite Repository"
    if any(word in lowered for word in ("用户", "查看", "接口", "请求", "user", "view", "api")):
        return "Web/API"
    return "Python Service"


def _logical_name(claim: Claim) -> str:
    subject = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", claim.subject).strip()
    action = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", claim.object).strip()
    return f"{subject or 'System'} · {action[:24]} Service"


def synthesize_rflp(
    claims: tuple[Claim, ...]
) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]:
    if not claims:
        raise InvariantViolation("at least one accepted claim is required")
    requirements: list[ModelElement] = []
    functions: list[ModelElement] = []
    logical: list[ModelElement] = []
    physical_by_name: dict[str, ModelElement] = {}
    relations: list[Relation] = []
    for claim in sorted(claims, key=lambda item: item.id):
        requirement = ModelElement(
            id=_identifier("req", claim.id),
            layer="R",
            kind="requirement",
            name=claim.object.rstrip(".。"),
            attributes=(("claim_id", claim.id),),
        )
        function = ModelElement(
            id=_identifier("fn", claim.id),
            layer="F",
            kind="function",
            name=claim.object.rstrip(".。"),
            attributes=(
                ("input", "request context"),
                ("output", "validated result"),
                ("precondition", "request is authorized"),
                ("postcondition", claim.object.rstrip(".。")),
                ("failure_mode", "validation or execution failure"),
            ),
        )
        logical_element = ModelElement(
            id=_identifier("logical", claim.id),
            layer="L",
            kind="logical-component",
            name=_logical_name(claim),
        )
        physical_name = _physical_name(f"{claim.subject} {claim.object}")
        physical = physical_by_name.setdefault(
            physical_name,
            ModelElement(
                id=_identifier("physical", physical_name),
                layer="P",
                kind="physical-component",
                name=physical_name,
            ),
        )
        requirements.append(requirement)
        functions.append(function)
        logical.append(logical_element)
        for source, predicate, target in (
            (requirement, "satisfiedBy", function),
            (function, "allocatedTo", logical_element),
            (logical_element, "realizedBy", physical),
        ):
            relations.append(
                Relation(
                    _identifier("rel", source.id, predicate, target.id),
                    source.id,
                    predicate,
                    target.id,
                )
            )
    elements = tuple(
        sorted(
            requirements + functions + logical + list(physical_by_name.values()),
            key=lambda item: ("RFLP".index(item.layer), item.name, item.id),
        )
    )
    return elements, tuple(sorted(relations, key=lambda item: item.id))
