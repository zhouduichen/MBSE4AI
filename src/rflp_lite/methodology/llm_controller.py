"""Optional read-only LLM recommendations for deterministic controller plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityStatus
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.controller import (
    ControllerPlan,
    ControllerProposal,
)
from rflp_lite.methodology.engine import MethodologyReport
from rflp_lite.ports.generative_model import (
    GenerationRequest,
    GenerativeModel,
    add_simplified_chinese_instruction,
)


_PROPOSAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action_id", "option_id", "rationale", "assumptions", "open_questions"],
    "properties": {
        "action_id": {"type": ["string", "null"], "maxLength": 128},
        "option_id": {"type": ["string", "null"], "maxLength": 128},
        "rationale": {"type": "string", "maxLength": 800},
        "assumptions": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "maxLength": 200},
        },
        "open_questions": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "maxLength": 200},
        },
    },
}
_PROPOSAL_FIELDS = frozenset(_PROPOSAL_SCHEMA["required"])
_CODE_RE = re.compile(r"[^a-zA-Z0-9_-]+")
_INACTIVE = frozenset({EntityStatus.REJECTED, EntityStatus.DEPRECATED})
_ENTITY_CONTEXT_LIMIT = 48
_RELATION_CONTEXT_LIMIT = 96


class _ProposalContractViolation(ContractViolation):
    def __init__(self, message: str, code: str):
        self.code = code
        super().__init__(message)

_CONTROLLER_SYSTEM_PROMPT = add_simplified_chinese_instruction(
    "你是系统工程 Controller 的只读建议器。根据有限的 ModelGraph、方法论检查和确定性动作目录，"
    "只推荐一个已有动作；不得创建动作、实体、关系、任务、Patch 或修订。"
    "action_id 必须来自 controller_plan.actions，trade_study 必须同时选择该动作已有的 option_id；"
    "无法可靠判断时仍需返回已有动作，并把不确定性写入 assumptions 或 open_questions。只输出符合 JSON Schema 的对象。"
)


class LLMController:
    """Ask an eligible model for a bounded recommendation without executing it."""

    def __init__(self, model: GenerativeModel | None, *, max_tokens: int = 768):
        self.model = model
        self.max_tokens = max(256, min(int(max_tokens), 1200))

    def propose(
        self,
        graph: ModelGraph,
        report: MethodologyReport,
        plan: ControllerPlan,
    ) -> ControllerProposal:
        if self.model is None:
            return ControllerProposal("not_configured", None, None)
        if not plan.actions:
            return ControllerProposal("not_needed", None, None)

        context = _bounded_controller_context(graph, report, plan)
        context_hash = canonical_hash(context)
        request = GenerationRequest(
            "controller.proposal",
            _CONTROLLER_SYSTEM_PROMPT,
            context,
            _PROPOSAL_SCHEMA,
            self.max_tokens,
        )
        try:
            response = self.model.complete_json(request)
            action_id, option_id, rationale, assumptions, open_questions = _validate_proposal(
                response.payload,
                plan,
            )
        except Exception as exc:
            return ControllerProposal(
                "fallback",
                None,
                None,
                diagnostics=(f"controller_proposal_{_safe_error_code(exc)}",),
                input_hash=context_hash,
                provider_id=_bounded_identity(exc, "provider_id"),
                model_id=_bounded_identity(exc, "model_id"),
            )

        return ControllerProposal(
            "proposed",
            action_id,
            option_id,
            rationale,
            assumptions,
            open_questions,
            input_hash=str(getattr(response, "input_hash", "") or context_hash)[:128],
            output_hash=str(getattr(response, "output_hash", ""))[:128],
            provider_id=str(getattr(response, "provider_id", ""))[:128],
            model_id=str(getattr(response, "model_id", ""))[:128],
        )


def _bounded_controller_context(
    graph: ModelGraph,
    report: MethodologyReport,
    plan: ControllerPlan,
) -> Mapping[str, object]:
    active_ids = {
        entity.id
        for entity in graph.entities
        if entity.meta.status not in _INACTIVE
    }
    action_entity_ids = _unique_active_ids(
        active_ids,
        (
            entity_id
            for action in plan.actions
            for entity_id in action.entity_ids
        ),
    )
    finding_entity_ids = _unique_active_ids(
        active_ids,
        (
            entity_id
            for finding in report.findings
            if finding.severity == "error"
            for entity_id in finding.entity_ids
        ),
    )
    impacted_entity_ids = _unique_active_ids(
        active_ids,
        report.impacted_entity_ids,
    )
    priority_ids = _ordered_unique(
        (*action_entity_ids, *finding_entity_ids, *impacted_entity_ids)
    )
    neighbor_ids = _relation_neighbors(graph, priority_ids, active_ids)
    ordered_entity_ids = _ordered_unique(
        (*priority_ids, *neighbor_ids, *sorted(active_ids))
    )
    selected_entity_ids = set(ordered_entity_ids[:_ENTITY_CONTEXT_LIMIT])
    entities = [
        _entity_summary(graph.entity_index[entity_id])
        for entity_id in ordered_entity_ids[:_ENTITY_CONTEXT_LIMIT]
    ]
    priority_id_set = set(priority_ids)
    impacted_id_set = set(impacted_entity_ids)
    ordered_relations = sorted(
        (
            relation
            for relation in graph.relations
            if relation.source_id in selected_entity_ids
            and relation.target_id in selected_entity_ids
        ),
        key=lambda relation: (
            0
            if relation.source_id in priority_id_set
            or relation.target_id in priority_id_set
            else 1
            if relation.source_id in impacted_id_set
            or relation.target_id in impacted_id_set
            else 2,
            relation.id,
        ),
    )
    relations = [
        {
            "id": relation.id,
            "source_id": relation.source_id,
            "predicate": relation.predicate.value,
            "target_id": relation.target_id,
        }
        for relation in ordered_relations[:_RELATION_CONTEXT_LIMIT]
    ]
    return {
        "context": {
            "project_id": graph.project_id,
            "revision": graph.revision,
            "snapshot_hash": graph.snapshot_hash,
            "entities": entities,
            "relations": relations,
            "selection": {
                "policy": "action-impact-first",
                "entity_limit": _ENTITY_CONTEXT_LIMIT,
                "relation_limit": _RELATION_CONTEXT_LIMIT,
                "selected_entity_ids": ordered_entity_ids[:_ENTITY_CONTEXT_LIMIT],
                "omitted_entity_ids": sorted(active_ids - selected_entity_ids),
                "action_entity_ids": list(action_entity_ids),
                "selected_action_entity_ids": [
                    entity_id
                    for entity_id in action_entity_ids
                    if entity_id in selected_entity_ids
                ],
                "omitted_action_entity_ids": [
                    entity_id
                    for entity_id in action_entity_ids
                    if entity_id not in selected_entity_ids
                ],
                "selected_relation_ids": [
                    relation.id for relation in ordered_relations[:_RELATION_CONTEXT_LIMIT]
                ],
                "omitted_relation_count": max(
                    0,
                    len(ordered_relations) - _RELATION_CONTEXT_LIMIT,
                ),
            },
        },
        "methodology": {
            "findings": [_finding_summary(item) for item in report.findings[:12]],
            "metrics": {
                str(key): _bounded_value(value)
                for key, value in list(report.metrics.items())[:24]
            },
            "impacted_entity_ids": list(report.impacted_entity_ids[:24]),
            "impact_paths": [
                list(path[:8]) for path in report.impact_paths[:24]
            ],
            "decision_package": {
                "decision_records": [
                    _bounded_value(item) for item in report.decisions[:12]
                ],
                "decision_count": len(report.decisions),
                "truncated": len(report.decisions) > 12,
            },
            "recommended_tasks": list(report.recommended_tasks[:8]),
        },
        "controller_plan": {
            "status": plan.status,
            "objective": plan.objective[:240],
            "findings": list(plan.findings[:12]),
            "impacted_entity_ids": list(plan.impacted_entity_ids[:24]),
            "impacted_stages": list(plan.impacted_stages[:8]),
            "actions": [_action_summary(action) for action in plan.actions[:8]],
        },
    }


def _unique_active_ids(
    active_ids: set[str],
    values,
) -> tuple[str, ...]:
    return _ordered_unique(
        str(value).strip()
        for value in values
        if str(value).strip() in active_ids
    )


def _ordered_unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _relation_neighbors(
    graph: ModelGraph,
    seed_ids: Sequence[str],
    active_ids: set[str],
) -> tuple[str, ...]:
    seeds = set(seed_ids)
    neighbors: list[str] = []
    for relation in sorted(graph.relations, key=lambda item: item.id):
        if relation.source_id not in active_ids or relation.target_id not in active_ids:
            continue
        if relation.source_id in seeds and relation.target_id not in seeds:
            neighbors.append(relation.target_id)
        elif relation.target_id in seeds and relation.source_id not in seeds:
            neighbors.append(relation.source_id)
    return _ordered_unique(neighbors)


def _entity_summary(entity) -> Mapping[str, object]:
    payload = entity.payload
    summary = {
        "id": entity.id,
        "kind": entity.kind.value,
        "name": entity.meta.name[:160],
        "status": entity.meta.status.value,
        "statement": _first_text(
            payload,
            ("statement", "obligation", "description", "behavior", "responsibility", "objective"),
        ),
        "constraints": _bounded_value(payload.get("constraints", {})),
    }
    for key in ("architecture_status", "feasibility_status"):
        if key in payload:
            summary[key] = _bounded_value(payload[key])
    return summary


def _finding_summary(finding) -> Mapping[str, object]:
    return {
        "code": finding.code,
        "severity": finding.severity,
        "stage": finding.stage,
        "entity_ids": list(finding.entity_ids[:24]),
        "message": finding.message[:400],
        "recommended_actions": list(finding.recommended_actions[:8]),
        "impact_paths": [list(path[:8]) for path in finding.impact_paths[:4]],
    }


def _action_summary(action) -> Mapping[str, object]:
    return {
        "id": action.id,
        "kind": action.kind,
        "task_id": action.task_id,
        "stage": action.stage,
        "priority": action.priority,
        "entity_ids": list(action.entity_ids[:24]),
        "reason": action.reason[:400],
        "options": [_bounded_value(option) for option in action.options[:8]],
    }


def _first_text(payload: Mapping[str, object], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:400]
    return ""


def _bounded_value(value: object, *, depth: int = 0) -> object:
    if depth >= 3:
        return str(value)[:240]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:240]
    if isinstance(value, Mapping):
        return {
            str(key)[:80]: _bounded_value(item, depth=depth + 1)
            for key, item in list(value.items())[:16]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_bounded_value(item, depth=depth + 1) for item in list(value)[:16]]
    return str(value)[:240]


def _validate_proposal(
    payload: object,
    plan: ControllerPlan,
) -> tuple[str, str | None, str, tuple[str, ...], tuple[str, ...]]:
    if not isinstance(payload, Mapping):
        raise _ProposalContractViolation(
            "controller proposal must be an object", "schema_validation"
        )
    if set(payload) != _PROPOSAL_FIELDS:
        raise _ProposalContractViolation(
            "controller proposal fields do not match schema", "schema_validation"
        )
    action_id = _bounded_id(payload.get("action_id"), "action_id")
    action = next((item for item in plan.actions if item.id == action_id), None)
    if action is None:
        raise _ProposalContractViolation(
            "controller proposal references an unknown action", "unknown_action"
        )
    option_id = _bounded_id(payload.get("option_id"), "option_id", allow_null=True)
    if action.kind == "trade_study":
        option = next(
            (item for item in action.options if str(item.get("id", "")) == option_id),
            None,
        )
        if option is None:
            raise _ProposalContractViolation(
                "controller proposal references an unknown trade option",
                "unknown_trade_option",
            )
    elif option_id:
        raise _ProposalContractViolation(
            "non-trade controller proposal cannot contain option_id",
            "unexpected_option",
        )
    return (
        action_id,
        option_id or None,
        _bounded_text(payload["rationale"], "rationale", 800),
        _bounded_texts(payload["assumptions"], "assumptions"),
        _bounded_texts(payload["open_questions"], "open_questions"),
    )


def _bounded_id(value: object, name: str, *, allow_null: bool = False) -> str:
    if value is None and allow_null:
        return ""
    if not isinstance(value, str) or len(value) > 128:
        raise _ProposalContractViolation(
            f"controller proposal {name} must be a short string", "schema_validation"
        )
    value = value.strip()
    if not value:
        raise _ProposalContractViolation(
            f"controller proposal {name} is required", "schema_validation"
        )
    return value


def _bounded_text(value: object, name: str, max_length: int) -> str:
    if not isinstance(value, str) or len(value) > max_length:
        raise _ProposalContractViolation(
            f"controller proposal {name} is invalid", "schema_validation"
        )
    return value.strip()


def _bounded_texts(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 4:
        raise _ProposalContractViolation(
            f"controller proposal {name} must be a short array", "schema_validation"
        )
    return tuple(_bounded_text(item, name, 200) for item in value)


def _safe_error_code(exc: Exception) -> str:
    raw_code = str(getattr(exc, "code", exc.__class__.__name__.casefold()))[:64]
    return _CODE_RE.sub("_", raw_code).strip("_") or "provider_error"


def _bounded_identity(exc: Exception, name: str) -> str:
    return str(getattr(exc, name, ""))[:128]
