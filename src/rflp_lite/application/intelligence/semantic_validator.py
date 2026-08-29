"""Semantic and provenance checks for validated LLM analysis blocks."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.application.intelligence.validated_result import ValidatedBlockResult
from rflp_lite.domain.errors import ContractViolation


VALID_RELATION_KINDS = frozenset(
    {
        "satisfiedBy",
        "allocatedTo",
        "realizedBy",
        "interfacesWith",
        "flowsTo",
        "verifiedBy",
        "derivedFrom",
        "refines",
    }
)

_ENTITY_KINDS = {
    "system_scope": "system_scope",
    "stakeholders": "stakeholder",
    "concerns_needs": "concern_or_need",
    "requirements": "requirement",
    "scenarios": "scenario",
    "function": "function",
    "logical_component": "logical_component",
    "physical_component": "physical_component",
    "interface": "interface",
}

_RELATION_ENDPOINTS = {
    "satisfiedBy": ({"requirement"}, {"function"}),
    "allocatedTo": ({"function"}, {"logical_component"}),
    "realizedBy": ({"logical_component"}, {"physical_component"}),
    "interfacesWith": ({"stakeholder", "logical_component", "physical_component", "interface"}, {"logical_component", "physical_component", "interface"}),
    "flowsTo": ({"interface", "logical_component", "physical_component"}, {"interface", "logical_component", "physical_component"}),
    "verifiedBy": ({"requirement"}, {"evidence", "test", "simulation"}),
    "derivedFrom": ({"requirement", "concern_or_need"}, {"source_region", "concern_or_need", "requirement"}),
    "refines": ({"concern_or_need", "requirement"}, {"requirement", "technical_requirement"}),
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: str
    message: str
    block_id: str
    path: str = ""

    def as_dict(self) -> dict[str, object]:
        value = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "block_id": self.block_id,
        }
        if self.path:
            value["path"] = self.path
        return value


def _state_entities(state: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    groups = {
        "claims": "requirement",
        "structured_requirements": "requirement",
        "stakeholders": "stakeholder",
        "concerns": "concern_or_need",
        "needs": "concern_or_need",
        "scenarios": "scenario",
        "document_regions": "source_region",
        "spans": "source_region",
    }
    for group, kind in groups.items():
        values = state.get(group, ())
        for item in values if isinstance(values, (list, tuple)) else ():
            if isinstance(item, dict) and str(item.get("id", "")):
                result.setdefault(str(item["id"]), kind)
    discovery = state.get("discovery")
    architecture = discovery.get("architecture") if isinstance(discovery, dict) else {}
    if isinstance(architecture, dict):
        for key, kind in (
            ("functions", "function"),
            ("logical_components", "logical_component"),
            ("physical_components", "physical_component"),
            ("interfaces", "interface"),
        ):
            values = architecture.get(key, ())
            for item in values if isinstance(values, (list, tuple)) else ():
                if isinstance(item, dict) and str(item.get("id", "")):
                    result.setdefault(str(item["id"]), kind)
    return result


def _dto_entities(result: ValidatedBlockResult) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in result.dto.items:
        item_id = str(item.get("id", ""))
        if not item_id:
            continue
        kind = str(item.get("kind", ""))
        if result.block_id == "architecture" and kind == "relation":
            continue
        if result.block_id == "concerns_needs":
            kind = "concern_or_need"
        elif result.block_id == "system_scope":
            kind = "system_scope"
        elif result.block_id == "stakeholders":
            kind = "stakeholder"
        elif result.block_id == "requirements":
            kind = "requirement"
        elif result.block_id == "scenarios":
            kind = "scenario"
        values[item_id] = _ENTITY_KINDS.get(kind, kind)
    return values


class AnalysisSemanticValidator:
    def validate(
        self, result: ValidatedBlockResult, state: dict[str, object]
    ) -> tuple[dict[str, object], ...]:
        issues: list[Diagnostic] = []
        existing = _state_entities(state)
        incoming = _dto_entities(result)
        input_hash = ""
        scope = state.get("project_scope")
        if isinstance(scope, dict):
            input_hash = str(scope.get("input_hash", ""))
        if input_hash and result.input_hash != input_hash:
            issues.append(
                Diagnostic(
                    "input_hash_mismatch",
                    "error",
                    "分析块不属于当前 Workbench 输入",
                    result.block_id,
                    "input_hash",
                )
            )
        region_ids = {
            item_id for item_id, kind in existing.items() if kind == "source_region"
        }
        for index, item in enumerate(result.dto.items):
            item_id = str(item.get("id", ""))
            if item_id in existing and existing[item_id] != incoming.get(item_id):
                issues.append(
                    Diagnostic(
                        "duplicate_id",
                        "error",
                        f"分析块 ID 与已有实体冲突: {item_id}",
                        result.block_id,
                        f"items[{index}].id",
                    )
                )
            for region_id in item.get("source_region_ids", ()):
                if str(region_id) not in region_ids:
                    issues.append(
                        Diagnostic(
                            "source_region_not_found",
                            "error",
                            f"来源区域不存在: {region_id}",
                            result.block_id,
                            f"items[{index}].source_region_ids",
                        )
                    )
        all_entities = {**existing, **incoming}
        if result.block_id == "architecture":
            for index, relation in enumerate(result.dto.items):
                if str(relation.get("kind", "")) != "relation":
                    continue
                predicate = str(relation.get("predicate", ""))
                source_id = str(relation.get("source_id", ""))
                target_id = str(relation.get("target_id", ""))
                if predicate not in VALID_RELATION_KINDS:
                    issues.append(
                        Diagnostic(
                            "unknown_relation_kind",
                            "error",
                            f"未知关系类型: {predicate}",
                            result.block_id,
                            f"items[{index}].predicate",
                        )
                    )
                    continue
                if source_id not in all_entities or target_id not in all_entities:
                    issues.append(
                        Diagnostic(
                            "relation_endpoint_not_found",
                            "error",
                            f"关系端点不存在: {source_id} -> {target_id}",
                            result.block_id,
                            f"items[{index}]",
                        )
                    )
                    continue
                allowed_source, allowed_target = _RELATION_ENDPOINTS[predicate]
                if all_entities[source_id] not in allowed_source or all_entities[target_id] not in allowed_target:
                    issues.append(
                        Diagnostic(
                            "relation_endpoint_type_invalid",
                            "error",
                            f"关系端点类型不合法: {predicate} ({all_entities[source_id]} -> {all_entities[target_id]})",
                            result.block_id,
                            f"items[{index}]",
                        )
                    )
        return tuple(issue.as_dict() for issue in issues)

    def assert_valid(
        self, result: ValidatedBlockResult, state: dict[str, object]
    ) -> None:
        issues = self.validate(result, state)
        if issues:
            first = issues[0]
            raise ContractViolation(
                f"分析块语义校验失败 [{first.get('code')}]: {first.get('message')}"
            )


__all__ = ["AnalysisSemanticValidator", "Diagnostic", "VALID_RELATION_KINDS"]
