"""Typed boundary between generated JSON and Workbench state."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import TypeAlias

from rflp_lite.application.intelligence.block_schemas import (
    BLOCK_SCHEMA_VERSION,
    schema_for,
)
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.generative_model import GenerationResponse


BlockItem: TypeAlias = dict[str, object]


@dataclass(frozen=True, slots=True)
class BlockDTO:
    block_id: str
    items: tuple[BlockItem, ...]
    diagnostics: tuple[dict[str, object], ...]
    coverage_decisions: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class SystemScopeDTO(BlockDTO):
    pass


@dataclass(frozen=True, slots=True)
class StakeholdersDTO(BlockDTO):
    pass


@dataclass(frozen=True, slots=True)
class ConcernsNeedsDTO(BlockDTO):
    pass


@dataclass(frozen=True, slots=True)
class RequirementsDTO(BlockDTO):
    pass


@dataclass(frozen=True, slots=True)
class ScenariosDTO(BlockDTO):
    pass


@dataclass(frozen=True, slots=True)
class ArchitectureDTO(BlockDTO):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedBlockResult:
    block_id: str
    input_hash: str
    workspace: str
    dto: BlockDTO
    diagnostics: tuple[dict[str, object], ...]
    provenance: dict[str, object]
    output_hash: str
    repaired: bool


_DTO_TYPES = {
    "system_scope": SystemScopeDTO,
    "stakeholders": StakeholdersDTO,
    "concerns_needs": ConcernsNeedsDTO,
    "requirements": RequirementsDTO,
    "scenarios": ScenariosDTO,
    "architecture": ArchitectureDTO,
}


def _state_input_hash(state: dict[str, object]) -> str:
    scope = state.get("project_scope")
    if isinstance(scope, dict) and str(scope.get("input_hash", "")):
        return str(scope["input_hash"])
    values = state.get("document_regions") or state.get("spans") or []
    return canonical_hash(values)


def _state_workspace(state: dict[str, object]) -> str:
    scope = state.get("project_scope")
    return str(scope.get("workspace", "")) if isinstance(scope, dict) else ""


def _jsonschema_validate(payload: dict[str, object], schema: dict[str, object]) -> None:
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - optional install guard
        raise ContractViolation("JSON Schema 校验依赖不可用") from exc
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        path = ".".join(str(item) for item in exc.absolute_path)
        suffix = f" at {path}" if path else ""
        raise ContractViolation(f"分析块结构不符合 Strict Schema{suffix}: {exc.message}") from exc
    except jsonschema.SchemaError as exc:
        raise ContractViolation("分析块 Strict Schema 无效") from exc


def _assert_finite(value: object, path: str = "") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractViolation(f"分析块包含非有限数值: {path or 'value'}")
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_finite(item, f"{path}[{index}]")


def parse_block_dto(block_id: str, payload: dict[str, object]) -> BlockDTO:
    if not isinstance(payload, dict):
        raise ContractViolation("分析块响应必须是对象")
    _assert_finite(payload)
    _jsonschema_validate(payload, schema_for(block_id))
    items = payload.get("items")
    diagnostics = payload.get("diagnostics")
    if not isinstance(items, list) or not isinstance(diagnostics, list):
        raise ContractViolation("分析块必须包含 items 和 diagnostics 数组")
    allowed_operations = {
        "upsert_entity",
        "enrich_fields",
        "propose_change",
        "flag_for_review",
        "add_relation",
    }
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).casefold()
        operation = str(
            item.get(
                "operation",
                "add_relation"
                if block_id == "architecture" and kind == "relation"
                else "upsert_entity",
            )
        )
        if operation not in allowed_operations:
            raise ContractViolation(f"分析块包含不允许的操作: {operation}")
        if block_id == "architecture":
            if kind == "relation" and operation not in {"add_relation", "flag_for_review"}:
                raise ContractViolation("架构 relation 只能使用 add_relation 或 flag_for_review")
            if kind != "relation" and operation == "add_relation":
                raise ContractViolation("架构实体不能使用 add_relation")
        elif operation == "add_relation":
            raise ContractViolation("当前分析块不支持 add_relation")
        if operation != "upsert_entity" and not str(item.get("target_id", "")).strip():
            # Relations identify both endpoints; an explicit target_id is not
            # required when source/target endpoint fields are present.
            if operation != "add_relation" or not str(item.get("source_id", "")).strip() or not str(item.get("target_id", "")).strip():
                raise ContractViolation(f"分析块第 {index + 1} 项缺少 target_id")
    raw_decisions = payload.get("coverage_decisions", [])
    if not isinstance(raw_decisions, list):
        raise ContractViolation("coverage_decisions 必须是数组")
    decisions: list[dict[str, object]] = []
    valid_types = {
        "scenario_type",
        "scenario_dimension",
        "lifecycle_phase",
        "stakeholder_category",
        "architecture_dimension",
    }
    for raw in raw_decisions:
        if not isinstance(raw, dict):
            raise ContractViolation("coverage_decisions 项必须是对象")
        decision_type = str(raw.get("decision_type", ""))
        key = str(raw.get("key", ""))
        refs = tuple(str(value) for value in raw.get("source_requirement_ids", ()))
        if decision_type not in valid_types or not key or not refs:
            raise ContractViolation("coverage_decisions 缺少有效的类型、key 或需求引用")
        decision = dict(raw)
        decision["id"] = str(
            raw.get("id")
            or "coverage-decision-"
            + canonical_hash((decision_type, key, sorted(refs)))[:12]
        )
        decisions.append(decision)
    dto_type = _DTO_TYPES[block_id]
    return dto_type(
        block_id=block_id,
        items=tuple(json.loads(canonical_json(item)) for item in items),
        diagnostics=tuple(json.loads(canonical_json(item)) for item in diagnostics),
        coverage_decisions=tuple(json.loads(canonical_json(item)) for item in decisions),
    )


def validate_and_build_result(
    response: GenerationResponse,
    *,
    state: dict[str, object],
    block_id: str,
) -> ValidatedBlockResult:
    payload = response.payload
    if not isinstance(payload, dict):
        raise ContractViolation("LLM 分析块响应必须是对象")
    dto = parse_block_dto(block_id, payload)
    declared_block_id = str(payload.get("block_id", "")).strip()
    if declared_block_id and declared_block_id != block_id:
        raise ContractViolation("分析块 block_id 与请求不一致")
    input_hash = str(payload.get("input_hash") or _state_input_hash(state)).strip()
    workspace = str(payload.get("workspace") or _state_workspace(state)).strip()
    expected_input_hash = _state_input_hash(state)
    expected_workspace = _state_workspace(state)
    if input_hash != expected_input_hash:
        raise ContractViolation("分析块 input_hash 与当前工作台不一致")
    if expected_workspace and workspace != expected_workspace:
        raise ContractViolation("分析块 workspace 与当前工作台不一致")
    ids = [str(item.get("id", "")) for item in dto.items]
    if any(not item_id for item_id in ids):
        raise ContractViolation("分析块项目必须包含 id")
    if len(ids) != len(set(ids)):
        raise ContractViolation("分析块存在重复 id")
    provenance = {
        "block_id": block_id,
        "schema_version": BLOCK_SCHEMA_VERSION,
        "input_hash": input_hash,
        "workspace": workspace,
        "lens_id": response.lens_id,
        "provider_id": response.provider_id,
        "model_id": response.model_id,
        "template_version": response.template_version,
        "repaired": response.repaired,
    }
    return ValidatedBlockResult(
        block_id=block_id,
        input_hash=input_hash,
        workspace=workspace,
        dto=dto,
        diagnostics=dto.diagnostics,
        provenance=provenance,
        output_hash=response.output_hash or canonical_hash(payload),
        repaired=response.repaired,
    )


__all__ = [
    "ArchitectureDTO",
    "BlockDTO",
    "ConcernsNeedsDTO",
    "RequirementsDTO",
    "ScenariosDTO",
    "StakeholdersDTO",
    "SystemScopeDTO",
    "ValidatedBlockResult",
    "parse_block_dto",
    "validate_and_build_result",
]
