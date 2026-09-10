"""HTML pages and read-only workflow view models for the Harness UI."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.gates import gate_for_phase, global_gate
from rflp_lite.methodology.tasks import task_catalog, tasks_for_phase
from rflp_lite.application.projections.assurance import build_assurance_view
from rflp_lite.application.projections.behavior import build_behavior_view
from rflp_lite.application.projections.history import build_history_view, build_revision_diff
from rflp_lite.application.projections.operational import build_operational_view
from rflp_lite.application.projections.requirements import build_requirement_detail, build_requirements_view
from rflp_lite.application.projections.rflp import build_rflp_view
from rflp_lite.application.projections.traceability import build_traceability_view
from rflp_lite.diagrams.engineering.rflp import render_rflp_svg


resource_pages = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")


_PHASES: tuple[tuple[Phase, str], ...] = (
    (Phase.OPERATIONAL, "Operational"),
    (Phase.FUNCTIONAL, "Functional"),
    (Phase.LOGICAL_PHYSICAL, "Logical/Physical"),
    (Phase.ASSURANCE, "Assurance"),
    (Phase.CLOSURE, "Closure"),
)
_PHASE_LABELS = {
    Phase.OPERATIONAL.value: "运行场景",
    Phase.FUNCTIONAL.value: "功能分析",
    Phase.LOGICAL_PHYSICAL.value: "逻辑/物理架构",
    Phase.ASSURANCE.value: "验证与确认",
    Phase.CLOSURE.value: "封版归档",
}
_PHASE_ACTION_LABELS = {
    Phase.OPERATIONAL.value: "运行场景分析",
    Phase.FUNCTIONAL.value: "功能分析",
    Phase.LOGICAL_PHYSICAL.value: "逻辑/物理架构分析",
    Phase.ASSURANCE.value: "验证与确认",
}
_ENTITY_KIND_LABELS = {
    "system": "系统",
    "stakeholder": "利益相关方",
    "concern": "关注点",
    "lifecycle_stage": "生命周期阶段",
    "lifecycle_transition": "生命周期转移",
    "scenario_hypothesis": "场景假设",
    "use_case": "用例",
    "operational_scenario": "运行场景",
    "activity": "活动",
    "requirement": "需求",
    "function": "功能",
    "functional_flow": "功能流",
    "functional_scenario": "功能场景",
    "logical_component": "逻辑组件",
    "physical_block": "物理块",
    "interface": "接口",
    "state": "状态",
    "hazard": "危险源",
    "failure_mode": "失效模式",
    "verification_case": "验证用例",
    "validation_case": "确认用例",
    "evidence": "证据",
}
_STATUS_LABELS = {
    "queued": "排队中",
    "running": "运行中",
    "degraded": "已降级",
    "failed": "失败",
    "completed": "已完成",
    "repairing": "修复中",
    "cancelled": "已取消",
    "candidate": "候选",
    "validated": "已验证",
    "accepted": "已接受",
    "rejected": "已拒绝",
    "deprecated": "已弃用",
    "locked": "已锁定",
    "passed": "已通过",
    "pending": "待处理",
    "ready": "待运行",
    "blocked": "已阻塞",
    "idle": "空闲",
    "有记录": "有记录",
    "暂无记录": "暂无记录",
}
_TASK_LABELS = {
    "system_definition": "系统定义",
    "stakeholder_analysis": "利益相关方分析",
    "stakeholder_requirements": "利益相关方需求",
    "lifecycle_analysis": "生命周期分析",
    "scenario_exploration": "场景探索",
    "use_case_analysis": "用例分析",
    "operational_scenario": "运行场景分析",
    "activity_analysis": "活动分析",
    "system_requirement_derivation": "系统需求推导",
    "function_identification": "功能识别",
    "functional_decomposition": "功能分解",
    "functional_interaction": "功能交互",
    "functional_scenario": "功能场景分析",
    "functional_requirement": "功能需求",
    "logical_analysis": "逻辑架构分析",
    "physical_candidates": "物理候选方案",
    "allocation_tradeoff": "分配与权衡",
    "technical_requirement": "技术需求",
    "interface_sequence_state": "接口、时序与状态",
    "fmea_stpa_hazard": "FMEA/STPA 危险分析",
    "verification_validation": "验证与确认",
    "reverse_feasibility": "反向可行性分析",
    "global_cross_analysis": "全局交叉分析",
}
_ISSUE_LABELS = {
    "missing_stakeholder": "缺少利益相关方",
    "missing_lifecycle": "缺少生命周期",
    "missing_scenario": "缺少场景",
    "missing_use_case": "缺少用例",
    "missing_requirement": "缺少需求",
    "missing_function": "缺少功能",
    "broken_requirement_function_trace": "需求到功能的链路断裂",
    "incomplete_rflp_chain": "RFLP 链路不完整",
    "broken_requirement_rflp_trace": "需求到 RFLP 的链路断裂",
    "missing_verification": "缺少验证用例",
    "broken_requirement_verification_trace": "需求到验证的链路断裂",
}
_ROOT_CAUSE_LABELS = {
    "stakeholder": "利益相关方",
    "lifecycle": "生命周期",
    "scenario": "场景与用例",
    "requirement": "需求",
    "function": "功能",
    "architecture": "逻辑/物理架构",
    "verification": "验证与确认",
    "evidence": "证据",
}
_ANALYSIS_MODULES = (
    ("stakeholders", "利益相关方", "参与者、关注点与利益关系", (EntityKind.STAKEHOLDER, EntityKind.CONCERN)),
    ("lifecycle", "生命周期", "阶段、转移与运行边界", (EntityKind.LIFECYCLE_STAGE, EntityKind.LIFECYCLE_TRANSITION)),
    ("scenarios", "场景与用例", "场景假设、用例、活动与运行场景", (EntityKind.SCENARIO_HYPOTHESIS, EntityKind.USE_CASE, EntityKind.OPERATIONAL_SCENARIO, EntityKind.ACTIVITY)),
    ("requirements", "需求分析", "需求、来源、证据与验收约束", (EntityKind.REQUIREMENT,)),
    ("functions", "功能分析", "功能、功能流与功能场景", (EntityKind.FUNCTION, EntityKind.FUNCTIONAL_FLOW, EntityKind.FUNCTIONAL_SCENARIO)),
    ("architecture", "逻辑/物理架构", "逻辑组件、物理块、接口与状态", (EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK, EntityKind.INTERFACE, EntityKind.STATE)),
    ("verification", "验证与确认", "验证、确认、危险源与失效模式", (EntityKind.VERIFICATION_CASE, EntityKind.VALIDATION_CASE, EntityKind.HAZARD, EntityKind.FAILURE_MODE)),
    ("evidence", "证据与问题", "证据记录、质量门禁问题与修复入口", (EntityKind.EVIDENCE,)),
    ("runs", "运行与审计", "当前任务、运行台账、修复与封版", ()),
)
_TRACE_STAGES: tuple[tuple[EntityKind, str], ...] = (
    (EntityKind.REQUIREMENT, "Requirement"),
    (EntityKind.FUNCTION, "Function"),
    (EntityKind.LOGICAL_COMPONENT, "Logical"),
    (EntityKind.PHYSICAL_BLOCK, "Physical"),
    (EntityKind.VERIFICATION_CASE, "Verification"),
)
_TRACE_STAGE_LABELS = {
    "Requirement": "需求",
    "Function": "功能",
    "Logical": "逻辑",
    "Physical": "物理",
    "Verification": "验证",
}
_ROOT_CAUSES = {
    "missing_stakeholder": "stakeholder",
    "missing_lifecycle": "lifecycle",
    "missing_scenario": "scenario",
    "missing_use_case": "scenario",
    "missing_requirement": "requirement",
    "missing_function": "function",
    "broken_requirement_function_trace": "function",
    "incomplete_rflp_chain": "architecture",
    "broken_requirement_rflp_trace": "architecture",
    "missing_verification": "verification",
    "broken_requirement_verification_trace": "verification",
}
_SUGGESTED_TASKS = {
    "stakeholder": "stakeholder_analysis",
    "lifecycle": "lifecycle_analysis",
    "scenario": "scenario_exploration",
    "requirement": "system_requirement_derivation",
    "function": "function_identification",
    "architecture": "logical_analysis",
    "verification": "verification_validation",
}


def _plain(value: object) -> object:
    """Convert mixed legacy/new service objects to JSON/Jinja values."""

    if is_dataclass(value):
        return _plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _mapping(value: object) -> dict[str, object]:
    clean = _plain(value)
    return dict(clean) if isinstance(clean, Mapping) else {}


def _state(request: Request, name: str, factory):
    value = getattr(request.app.state, name, None)
    if value is None:
        value = factory()
        setattr(request.app.state, name, value)
    return value


def remember_run(request: Request, project_id: str, run: Mapping[str, object]) -> None:
    """Remember a Web-triggered result until a repository list API is available."""

    records = _state(request, "web_analysis_runs", dict)
    records.setdefault(project_id, []).append(dict(_plain(run)))
    records[project_id] = records[project_id][-20:]


def remember_repair(request: Request, project_id: str, repair: Mapping[str, object]) -> None:
    repairs = _state(request, "web_repairs", dict)
    repairs.setdefault(project_id, []).append(dict(_plain(repair)))
    repairs[project_id] = repairs[project_id][-20:]


def _services(request: Request):
    return request.app.state.container.v2


def _phase_value(value: object) -> str:
    return str(getattr(value, "value", value or ""))


def _status_value(value: object, default: str = "") -> str:
    return _phase_value(value) or default


def _label(labels: Mapping[str, str], value: object, default: str = "—") -> str:
    key = str(getattr(value, "value", value or ""))
    return labels.get(key, default if not key else key)


def _status_label(value: object, default: str = "待处理") -> str:
    return _label(_STATUS_LABELS, value, default)


def _kind_label(value: object) -> str:
    return _label(_ENTITY_KIND_LABELS, value, "模型元素")


def _phase_label(value: object) -> str:
    return _label(_PHASE_LABELS, value, "生命周期阶段")


def _task_label(value: object) -> str:
    return _label(_TASK_LABELS, value, "分析任务")


def _display_name(value: object, default: str = "未命名元素") -> str:
    name = str(value or default)
    task_name = name.removesuffix(" 候选")
    return _TASK_LABELS.get(task_name, name)


def _decorate_entity(entity, relation_counts: Mapping[str, int]):
    value = _mapping(entity.as_dict() if hasattr(entity, "as_dict") else entity)
    value["kind_label"] = _kind_label(value.get("kind"))
    value["status_label"] = _status_label(value.get("status"))
    value["producer_label"] = {"user": "用户", "llm": "模型", "rule": "规则", "import": "导入"}.get(
        str(value.get("producer", "")), str(value.get("producer", ""))
    )
    value["relation_count"] = int(relation_counts.get(str(value.get("id", "")), 0))
    return value


def _runtime_metadata(services, run: Mapping[str, object] | None = None) -> dict[str, object]:
    run_data = run or {}
    recorded = _mapping(run_data.get("runtime"))
    try:
        active = _mapping(services.settings.active_config())
    except Exception:
        active = {}
    profile_id = str(
        run_data.get("model_profile")
        or run_data.get("profile_id")
        or recorded.get("profile_id")
        or active.get("id")
        or "offline-rule"
    )
    provider_id = str(
        run_data.get("provider_id")
        or run_data.get("provider")
        or recorded.get("provider_id")
        or active.get("provider_id")
        or active.get("provider")
        or ("openai-compatible" if active else "offline")
    )
    model_id = str(
        run_data.get("model_id")
        or recorded.get("model_id")
        or active.get("model")
        or ("rule-runtime" if not active else "")
    )
    raw_mode = str(
        run_data.get("runtime_mode")
        or recorded.get("mode")
        or active.get("mode")
        or ("configured" if active else "offline")
    ).casefold()
    if raw_mode in {"injected", "injected runtime"}:
        mode = "Injected Runtime"
    elif raw_mode in {"configured", "configured model", "active"} or active:
        mode = "Configured Model"
    else:
        mode = "Offline Rule Mode"
    return {
        "profile_id": profile_id,
        "profile_label": "离线规则" if profile_id == "offline-rule" else profile_id,
        "provider_id": provider_id,
        "provider_label": "离线规则" if provider_id == "offline" else provider_id,
        "model_id": model_id,
        "model_label": "规则引擎" if model_id == "rule-runtime" else model_id,
        "mode": mode,
        "mode_label": {"Injected Runtime": "注入运行时", "Configured Model": "已配置模型", "Offline Rule Mode": "离线规则模式"}.get(mode, mode),
        "configured": mode == "Configured Model",
        "source": "run" if run_data and (run_data.get("provider_id") or run_data.get("model_id") or run_data.get("model_profile")) else "active" if active else "fallback",
        "source_label": "本次运行" if run_data and (run_data.get("provider_id") or run_data.get("model_id") or run_data.get("model_profile")) else "活动配置" if active else "默认离线规则",
    }


def _normalize_run(raw: object) -> dict[str, object] | None:
    value = _mapping(raw)
    if not value:
        return None
    run_id = str(value.get("run_id") or value.get("id") or "")
    if not run_id:
        return None
    normalized = dict(value)
    normalized["run_id"] = run_id
    normalized["phase"] = _status_value(value.get("phase"), "operational")
    normalized["status"] = _status_value(value.get("status"), "queued")
    normalized["phase_label"] = _phase_label(normalized["phase"])
    normalized["status_label"] = _status_label(normalized["status"])
    normalized["completed_tasks"] = list(value.get("completed_tasks", ()))
    normalized["diagnostics"] = list(value.get("diagnostics", ()))
    steps = []
    for item in value.get("steps", ()):
        step = _mapping(item)
        if not step:
            continue
        step["task_label"] = _task_label(step.get("task_id"))
        step["status_label"] = _status_label(step.get("status"))
        steps.append(step)
    normalized["steps"] = steps
    return normalized


def _repository_latest_run(services, project_id: str) -> dict[str, object] | None:
    repository = services.repository(project_id)
    list_runs = getattr(repository, "list_runs", None)
    if callable(list_runs):
        try:
            runs = list_runs(project_id)
            candidates = [_normalize_run(item) for item in runs]
            candidates = [item for item in candidates if item]
            if candidates:
                return candidates[-1]
        except Exception:
            pass
    # The current legacy repository has no list_runs port. This read-only
    # fallback is isolated to the Web presentation adapter.
    connection = getattr(repository, "_connection", None)
    if connection is not None:
        try:
            row = connection.execute(
                "SELECT id FROM runs WHERE project_id = ? ORDER BY rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if row is not None:
                return _normalize_run(repository.load_run(project_id, str(row[0])))
        except Exception:
            pass
    return None


def _latest_run(request: Request, services, project_id: str) -> dict[str, object] | None:
    records = _state(request, "web_analysis_runs", dict).get(project_id, ())
    if records:
        remembered = _normalize_run(records[-1])
        if remembered:
            repository = services.repository(project_id)
            try:
                stored = _normalize_run(repository.load_run(project_id, remembered["run_id"]))
            except Exception:
                stored = None
            if stored:
                stored_steps = stored.get("steps", ())
                merged = {**stored, **remembered}
                if not remembered.get("steps"):
                    merged["steps"] = stored_steps
                return merged
            return remembered
        return _repository_latest_run(services, project_id)
    return _repository_latest_run(services, project_id)


def _aggregate_pipeline_steps(services, project_id: str, run: dict[str, object] | None) -> dict[str, object] | None:
    if not run or run.get("steps"):
        return run
    phase_results = run.get("phase_results", ())
    values = phase_results.values() if isinstance(phase_results, Mapping) else phase_results
    repository = services.repository(project_id)
    steps: list[dict[str, object]] = []
    for item in values or ():
        phase_run_id = _mapping(item).get("run_id")
        if not phase_run_id:
            continue
        try:
            stored = _normalize_run(repository.load_run(project_id, str(phase_run_id)))
        except Exception:
            stored = None
        if stored:
            steps.extend(stored.get("steps", ()))
    if not steps:
        return run
    return {**run, "steps": steps}


def _issue_payload(raw: object, *, fallback_phase: Phase | None = None) -> dict[str, object]:
    value = _mapping(raw)
    code = str(value.get("code") or "issue")
    root_cause = str(value.get("root_cause") or _ROOT_CAUSES.get(code, "evidence"))
    rollback = value.get("rollback_phase") or value.get("suggested_rollback")
    rollback_value = _status_value(rollback) if rollback else _status_value(fallback_phase)
    entity_ids = [str(item) for item in value.get("entity_ids", ())]
    code_label = _ISSUE_LABELS.get(code, "模型问题")
    evidence_gap = bool(value.get("evidence_gap", code.startswith("missing_")))
    return {
        "id": str(value.get("id") or f"issue-{canonical_hash((code, tuple(entity_ids), rollback_value))[:12]}"),
        "code": code,
        "code_label": code_label,
        "severity": str(value.get("severity") or "error"),
        "severity_label": {"error": "错误", "warning": "警告", "info": "提示"}.get(str(value.get("severity") or "error"), "问题"),
        "root_cause": root_cause,
        "root_cause_label": _ROOT_CAUSE_LABELS.get(root_cause, "待分析"),
        "entity_ids": entity_ids,
        "suggested_task": str(value.get("suggested_task") or _SUGGESTED_TASKS.get(root_cause, "manual_review")),
        "suggested_task_label": _task_label(value.get("suggested_task") or _SUGGESTED_TASKS.get(root_cause, "manual_review")),
        "rollback_phase": rollback_value,
        "rollback_phase_label": _phase_label(rollback_value),
        "evidence_gap": evidence_gap,
        "evidence_gap_label": "需要补充" if evidence_gap else "无",
        "status": str(value.get("status") or "open"),
        "status_label": {"open": "待处理", "resolved": "已解决", "ignored": "已忽略"}.get(str(value.get("status") or "open"), "待处理"),
        "message": str(value.get("message") or f"{code_label}需要检查"),
    }


def _gate_payload(raw: object, *, fallback_phase: Phase | None = None) -> dict[str, object]:
    value = _mapping(raw)
    gate_id = str(value.get("gate_id") or "Global-Gate")
    raw_issues = value.get("issues", ())
    issues = [_issue_payload(item, fallback_phase=fallback_phase) for item in raw_issues]
    passed = bool(value.get("passed", not issues))
    return {
        "gate_id": gate_id,
        "gate_label": {"O-Gate": "运行场景质量门禁", "F-Gate": "功能质量门禁", "P-Gate": "逻辑/物理质量门禁", "Global-Gate": "全局质量门禁"}.get(gate_id, gate_id),
        "passed": passed,
        "status": "passed" if passed else "failed",
        "status_label": "已通过" if passed else "未通过",
        "issues": issues,
        "rollback_phase": _status_value(value.get("rollback_phase"), "") or None,
        "rollback_phase_label": _phase_label(value.get("rollback_phase")) if value.get("rollback_phase") else "—",
    }


def _record_gate_results(run: Mapping[str, object] | None) -> dict[str, dict[str, object]]:
    if not run:
        return {}
    raw = run.get("gate_results", ())
    values = raw.values() if isinstance(raw, Mapping) else raw
    result: dict[str, dict[str, object]] = {}
    for item in values or ():
        payload = _mapping(item)
        phase = str(payload.get("phase") or payload.get("phase_id") or "")
        gate = _gate_payload(payload)
        if not phase:
            phase = gate["gate_id"]
        result[phase] = gate
    return result


def _current_task(services, project_id: str, graph: ModelGraph, run: Mapping[str, object] | None, runtime: Mapping[str, object]) -> dict[str, object]:
    steps = list(run.get("steps", ())) if run else []
    step = next((item for item in steps if item.get("status") == "running"), None)
    if step is None and steps:
        step = max(steps, key=lambda item: (int(item.get("attempt", 0) or 0), str(item.get("task_id", ""))))
    task_id = str(step.get("task_id", "")) if step else ""
    phase_values = {item.value for item, _label in _PHASES}
    phase = Phase(str(run.get("phase", Phase.OPERATIONAL.value))) if run and str(run.get("phase", "")) in phase_values else Phase.OPERATIONAL
    task = next((item for item in task_catalog() if item.id == task_id), None)
    if task is None:
        phase_tasks = tasks_for_phase(phase)
        task = phase_tasks[0] if phase_tasks else None
        task_id = task.id if task else "awaiting_task"
    context: dict[str, object] = {
        "revision": graph.revision,
        "entity_count": len(graph.entities),
        "relation_count": len(graph.relations),
        "evidence_count": 0,
        "token_estimate": 0,
    }
    try:
        if task is not None:
            from rflp_lite.methodology.context import ContextBuilder

            bundle = ContextBuilder().build(graph, task)
            context.update(
                evidence_count=len(bundle.evidence),
                token_estimate=bundle.token_estimate,
            )
    except Exception:
        pass
    step_status = str(step.get("status", "queued")) if step else "queued"
    diagnostics = [str(item) for item in (step.get("diagnostics", ()) if step else ())]
    if step_status == "completed":
        validation = "已通过"
    elif diagnostics:
        validation = "; ".join(diagnostics)
    else:
        validation = "未运行"
    patch_id = "—"
    if step:
        patch_id = str(step.get("output_patch_id") or step.get("patch_id") or "—")
    provider_id = str(step.get("provider_id") or runtime.get("provider_id", "")) if step else str(runtime.get("provider_id", ""))
    model_id = str(step.get("model_id") or runtime.get("model_id", "")) if step else str(runtime.get("model_id", ""))
    return {
        "task_id": task_id,
        "task_label": _task_label(task_id),
        "phase": phase.value,
        "phase_label": _phase_label(phase),
        "status": step_status,
        "status_label": _status_label(step_status),
        "input_context": context,
        "evidence_count": context["evidence_count"],
        "provider_id": provider_id,
        "provider_label": "离线规则" if provider_id == "offline" else provider_id,
        "model_id": model_id,
        "model_label": "规则引擎" if model_id == "rule-runtime" else model_id,
        "attempt": int(step.get("attempt", 0) or 0) if step else 0,
        "patch_id": patch_id,
        "validation": validation,
        "diagnostics": diagnostics,
    }


def _phase_status(run: Mapping[str, object] | None, phase: Phase) -> str:
    if not run:
        return "ready" if phase is Phase.OPERATIONAL else "pending"
    results = run.get("phase_results", ())
    values = results.values() if isinstance(results, Mapping) else results
    for item in values or ():
        value = _mapping(item)
        if _status_value(value.get("phase")) == phase.value:
            return _status_value(value.get("status"), "queued")
    if _status_value(run.get("phase")) == phase.value:
        return _status_value(run.get("status"), "queued")
    closure = _mapping(run.get("closure"))
    if phase is Phase.CLOSURE and closure.get("status"):
        return str(closure["status"])
    return "pending"


def _analysis_module_views(services, project_id: str, graph: ModelGraph, issues: list[dict], run: Mapping[str, object] | None):
    relation_counts: dict[str, int] = {}
    for relation in graph.relations:
        relation_counts[relation.source_id] = relation_counts.get(relation.source_id, 0) + 1
        relation_counts[relation.target_id] = relation_counts.get(relation.target_id, 0) + 1
    evidence: list[dict] = []
    try:
        evidence = [_mapping(item) for item in services.evidence(project_id).list(project_id)]
    except Exception:
        pass
    modules: list[dict] = []
    for module_id, title, description, kinds in _ANALYSIS_MODULES:
        entities = [
            _decorate_entity(entity, relation_counts)
            for entity in graph.entities
            if entity.kind in kinds
        ]
        records: list[dict] = []
        module_issues = issues if module_id == "evidence" else []
        if module_id == "evidence":
            records.extend(
                {
                    "label": "证据",
                    "name": str(item.get("claim") or "未命名证据"),
                    "detail": str(item.get("locator") or "未提供定位信息"),
                    "status_label": "已收录",
                }
                for item in evidence
            )
            records.extend(
                {
                    "label": "问题",
                    "name": str(item.get("code_label") or "模型问题"),
                    "detail": str(item.get("message") or "需要检查"),
                    "status_label": str(item.get("status_label") or "待处理"),
                }
                for item in module_issues
            )
        elif module_id == "runs":
            if run:
                records.append(
                    {
                        "label": "最近一次运行",
                        "name": str(run.get("run_id") or "未命名运行"),
                        "detail": f"{run.get('phase_label', '生命周期')} · {run.get('status_label', '待处理')}",
                        "status_label": str(run.get("status_label") or "待处理"),
                    }
                )
                records.extend(
                    {
                        "label": str(step.get("task_label") or "分析任务"),
                        "name": "已执行",
                        "detail": f"尝试第 {step.get('attempt', 0)} 次 · {step.get('input_hash') or '无输入哈希'}",
                        "status_label": str(step.get("status_label") or "待处理"),
                    }
                    for step in run.get("steps", ())
                    if isinstance(step, Mapping)
                )
        else:
            records = [
                {
                    "label": str(entity.get("kind_label") or "模型元素"),
                    "name": _display_name(entity.get("name")),
                    "detail": f"{entity.get('status_label', '候选')} · 关联 {entity.get('relation_count', 0)} 条",
                    "status_label": str(entity.get("status_label") or "候选"),
                    "id": str(entity.get("id") or ""),
                }
                for entity in entities
            ]
        count = len(records)
        modules.append(
            {
                "id": module_id,
                "title": title,
                "description": description,
                "count": count,
                "status": "有记录" if count else "暂无记录",
                "status_label": "有记录" if count else "暂无记录",
                "entities": entities,
                "issues": module_issues,
                "records": records,
            }
        )
    return modules


def build_analysis_view(request: Request, project_id: str) -> dict[str, object]:
    services = _services(request)
    project = _mapping(services.projects.summary(project_id))
    graph = services.model(project_id).graph(project_id)
    has_analysis_input = services.projects.has_analysis_input(project_id)
    run = _aggregate_pipeline_steps(services, project_id, _latest_run(request, services, project_id))
    runtime = _runtime_metadata(services, run)
    record_gates = _record_gate_results(run)
    gate_results: list[dict[str, object]] = []
    for phase, _label in _PHASES:
        if phase is Phase.CLOSURE:
            result = record_gates.get(phase.value) or record_gates.get("Global-Gate")
            if result is None:
                result = _gate_payload(global_gate(graph), fallback_phase=Phase.ASSURANCE)
        else:
            result = record_gates.get(phase.value)
            if result is None:
                result = _gate_payload(gate_for_phase(phase, graph), fallback_phase=phase)
        result = dict(result)
        result["phase"] = phase.value
        gate_results.append(result)
    global_result = next((item for item in gate_results if item["gate_id"] == "Global-Gate"), None)
    if global_result is None:
        global_result = _gate_payload(global_gate(graph), fallback_phase=Phase.ASSURANCE)
        global_result["phase"] = Phase.CLOSURE.value
    stored_issues = []
    try:
        stored_issues = [_issue_payload(item) for item in services.model(project_id).issues(project_id)]
    except Exception:
        pass
    all_issues = list(stored_issues)
    for gate in gate_results:
        all_issues.extend(gate["issues"])
    unique: dict[str, dict[str, object]] = {}
    for issue in all_issues:
        unique[str(issue["id"])] = issue
    all_issues = list(unique.values())
    repair_records = _state(request, "web_repairs", dict).get(project_id, ())
    repair = dict(repair_records[-1]) if repair_records else _mapping(run.get("repair")) if run else {}
    if not repair:
        repair = {
            "status": "idle",
            "status_label": "空闲",
            "root_cause": "—",
            "root_cause_label": "—",
            "rollback_phase": "—",
            "rollback_phase_label": "—",
            "rollback_task": "—",
            "rollback_task_label": "—",
            "automatic_round": 0,
            "manual_action": "选择一个质量门禁问题后开始定向修复。",
            "manual_action_label": "选择一个质量门禁问题后开始定向修复。",
        }
    else:
        repair["status_label"] = _status_label(repair.get("status"))
        repair["root_cause_label"] = _ROOT_CAUSE_LABELS.get(str(repair.get("root_cause", "")), str(repair.get("root_cause", "—")))
        repair["rollback_phase_label"] = _phase_label(repair.get("rollback_phase"))
        repair["rollback_task_label"] = _task_label(repair.get("rollback_task"))
        repair["manual_action_label"] = str(repair.get("manual_action", "选择一个质量门禁问题后开始定向修复。"))
    closure = _mapping(run.get("closure")) if run else {}
    if not closure:
        closure = {"status": "pending", "status_label": "待处理", "accepted_revision": None, "manifest": None}
    else:
        closure["status_label"] = _status_label(closure.get("status"))
    latest_run = dict(run) if run else None
    if latest_run is not None:
        latest_run["runtime"] = runtime
    gate_by_phase = {item["phase"]: item for item in gate_results}
    phase_states = [
        {
            "phase": phase.value,
            "name": label,
            "name_label": _phase_label(phase),
            "action_label": _PHASE_ACTION_LABELS.get(phase.value, _phase_label(phase)),
            "status": _phase_status(run, phase),
            "status_label": _status_label(_phase_status(run, phase)),
            "gate": gate_by_phase[phase.value],
        }
        for phase, label in _PHASES
    ]
    analysis_modules = _analysis_module_views(services, project_id, graph, all_issues, run)
    view = {
        "project": {**project, "revision": graph.revision},
        "project_id": project_id,
        "current_revision": graph.revision,
        "has_analysis_input": has_analysis_input,
        "graph_hash": graph.snapshot_hash,
        "runtime": runtime,
        "active_runtime": runtime,
        "active_model": runtime,
        "run_status": latest_run.get("status", "ready") if latest_run else "ready",
        "latest_run": latest_run,
        "current_run": latest_run,
        "phases": phase_states,
        "phase_states": phase_states,
        "analysis_modules": analysis_modules,
        "current_task": _current_task(services, project_id, graph, run, runtime),
        "task_ledger": list(latest_run.get("steps", ())) if latest_run else [],
        "gate_results": gate_results,
        "gate_result": global_result,
        "global_gate": global_result,
        "gate_issues": all_issues,
        "issues": all_issues,
        "repair": repair,
        "repair_results": list(repair_records),
        "closure": closure,
        "closure_state": closure,
    }
    return view


def _trace_node(project_id: str, entity, stage: str) -> dict[str, object]:
    return {
        "stage": stage,
        "stage_label": _TRACE_STAGE_LABELS.get(stage, stage),
        "kind": entity.kind.value,
        "kind_label": _kind_label(entity.kind.value),
        "id": entity.id,
        "name": _display_name(entity.meta.name, "未命名实体"),
        "status": entity.meta.status.value,
        "status_label": _status_label(entity.meta.status.value),
        "href": f"/projects/{project_id}/entities?kind={entity.kind.value}#entity-{entity.id}",
    }


def _kind_path(graph: ModelGraph, adjacency: Mapping[str, tuple[str, ...]], start_id: str, target_kind: EntityKind) -> tuple[str, ...] | None:
    index = graph.entity_index
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(start_id, (start_id,))])
    visited = {start_id}
    while queue:
        current, path = queue.popleft()
        if current != start_id and index.get(current) and index[current].kind is target_kind:
            return path
        for target in adjacency.get(current, ()):
            if target not in visited and target in index:
                visited.add(target)
                queue.append((target, path + (target,)))
    return None


def build_trace_view(request: Request, project_id: str) -> dict[str, object]:
    services = _services(request)
    graph = services.model(project_id).graph(project_id)
    index = graph.entity_index
    adjacency: dict[str, list[str]] = {}
    for relation in graph.relations:
        adjacency.setdefault(relation.source_id, []).append(relation.target_id)
    adjacency_tuple = {key: tuple(value) for key, value in adjacency.items()}
    paths: list[dict[str, object]] = []
    issues: list[dict[str, object]] = []
    for requirement in sorted((item for item in graph.entities if item.kind is EntityKind.REQUIREMENT), key=lambda item: item.id):
        ids: list[str | None] = [requirement.id]
        function_path = _kind_path(graph, adjacency_tuple, requirement.id, EntityKind.FUNCTION)
        ids.append(function_path[-1] if function_path else None)
        logical_path = _kind_path(graph, adjacency_tuple, ids[-1], EntityKind.LOGICAL_COMPONENT) if ids[-1] else None
        ids.append(logical_path[-1] if logical_path else None)
        physical_path = _kind_path(graph, adjacency_tuple, ids[-1], EntityKind.PHYSICAL_BLOCK) if ids[-1] else None
        ids.append(physical_path[-1] if physical_path else None)
        verification_path = _kind_path(graph, adjacency_tuple, requirement.id, EntityKind.VERIFICATION_CASE)
        ids.append(verification_path[-1] if verification_path else None)
        nodes: list[dict[str, object] | None] = []
        missing: list[str] = []
        for entity_id, (_kind, stage) in zip(ids, _TRACE_STAGES):
            entity = index.get(entity_id) if entity_id else None
            nodes.append(_trace_node(project_id, entity, stage) if entity else None)
            if entity is None:
                missing.append(stage)
                issues.append({
                    "code": f"missing_trace_{stage.casefold()}",
                    "message": f"{requirement.meta.name}暂无{stage}链路",
                    "entity_ids": [requirement.id],
                    "severity": "warning",
                    "severity_label": "警告",
                })
        path: dict[str, object] = {
            "path_id": f"trace-{canonical_hash((project_id, requirement.id))[:12]}",
            "complete": not missing,
            "missing": missing,
            "nodes": nodes,
        }
        for node, (_kind, stage) in zip(nodes, _TRACE_STAGES):
            path[stage.casefold()] = node
        paths.append(path)
    return {
        "project_id": project_id,
        "revision": graph.revision,
        "graph_hash": graph.snapshot_hash,
        "stages": [stage for _kind, stage in _TRACE_STAGES],
        "stage_labels": [_TRACE_STAGE_LABELS[label] for _kind, label in _TRACE_STAGES],
        "paths": paths,
        "issues": issues,
    }


def build_settings_view(request: Request) -> dict[str, object]:
    services = _services(request)
    settings = _mapping(services.settings.list_profiles())
    profiles = []
    for item in settings.get("profiles", ()):
        profile = _mapping(item)
        profile["kind_label"] = {"local": "本地服务", "remote": "远程服务"}.get(str(profile.get("kind", "")), "服务")
        profile["provider_label"] = {"ollama": "Ollama", "openai-compatible": "OpenAI 兼容"}.get(str(profile.get("provider", "")), str(profile.get("provider", "服务")))
        profile["credential_label"] = "已配置" if profile.get("api_key_configured") else "未配置"
        profile["enabled_label"] = "已启用" if profile.get("enabled", True) else "已停用"
        profiles.append(profile)
    settings["profiles"] = profiles
    return {"settings": settings, "runtime": _runtime_metadata(services)}


def _v2(request: Request):
    return request.app.state.container.v2


@resource_pages.get("/ui/projects", name="projects_page")
def projects_page(request: Request):
    return templates.TemplateResponse(request=request, name="projects.html", context={"projects": _v2(request).projects.list(), "active": "projects"})


@resource_pages.get("/ui/projects/{project_id}/analysis", name="analysis_page")
def analysis_page(request: Request, project_id: str):
    view = build_analysis_view(request, project_id)
    return templates.TemplateResponse(request=request, name="analysis.html", context={**view, "analysis": view, "active": "analysis"})


@resource_pages.get("/ui/projects/{project_id}/documents", name="documents_page")
def documents_page(request: Request, project_id: str):
    services = _v2(request)
    project = services.projects.summary(project_id)
    input_root = services.projects.path(project_id) / "inputs"
    documents = []
    if input_root.is_dir():
        for path in sorted((item for item in input_root.iterdir() if item.is_file()), key=lambda item: item.name.casefold()):
            size = path.stat().st_size
            documents.append({
                "name": path.name,
                "kind": path.suffix.removeprefix(".").upper() or "FILE",
                "size_label": f"{size} B",
                "relative_path": str(path.relative_to(services.projects.path(project_id))),
            })
    return templates.TemplateResponse(request=request, name="documents.html", context={"project": project, "project_id": project_id, "documents": documents, "active": "documents"})


@resource_pages.get("/ui/projects/{project_id}/model", name="model_page")
def model_page(request: Request, project_id: str):
    services = _v2(request)
    trace = build_trace_view(request, project_id)
    return templates.TemplateResponse(request=request, name="model.html", context={"project": services.projects.summary(project_id), "project_id": project_id, "trace": trace, "active": "model"})


@resource_pages.get("/ui/projects/{project_id}/evidence", name="evidence_page")
def evidence_page(request: Request, project_id: str):
    services = _v2(request)
    issues = [_issue_payload(item) for item in services.model(project_id).issues(project_id)]
    return templates.TemplateResponse(request=request, name="evidence-issues.html", context={"project": services.projects.summary(project_id), "evidence": services.evidence(project_id).list(project_id), "issues": issues, "project_id": project_id, "active": "evidence"})


@resource_pages.get("/ui/settings", name="settings_page")
def settings_page(request: Request):
    view = build_settings_view(request)
    return templates.TemplateResponse(request=request, name="settings.html", context={**view, "active": "settings"})


def _review_context(request: Request, project_id: str) -> dict[str, object]:
    services = _v2(request)
    model = services.model(project_id)
    graph = model.graph(project_id)
    issues = tuple(model.issues(project_id))
    return {"services": services, "graph": graph, "issues": issues}


@resource_pages.get("/ui/projects/{project_id}/requirements", name="requirements_page")
def requirements_page(request: Request, project_id: str, status: str | None = None, q: str | None = None):
    context = _review_context(request, project_id)
    view = build_requirements_view(context["graph"], context["issues"])
    query = str(q or "").casefold().strip()
    if status or query:
        view["rows"] = [row for row in view["rows"] if (not status or row["status"] == status) and (not query or query in str(row["id"]).casefold() or query in str(row["name"]).casefold() or query in str(row["statement"]).casefold())]
    return templates.TemplateResponse(request=request, name="requirements.html", context={**view, "project_id": project_id, "active": "requirements", "selected_status": status or "", "query": q or ""})


@resource_pages.get("/ui/projects/{project_id}/requirements/{entity_id}", name="requirement_detail_page")
def requirement_detail_page(request: Request, project_id: str, entity_id: str):
    context = _review_context(request, project_id)
    detail = build_requirement_detail(context["graph"], entity_id, issues=context["issues"], evidence=tuple(context["services"].evidence(project_id).list(project_id)))
    if detail is None:
        from rflp_lite.domain.errors import NotFoundError
        raise NotFoundError(f"requirement not found: {entity_id}")
    return templates.TemplateResponse(request=request, name="requirement-detail.html", context={**detail, "project_id": project_id, "active": "requirements"})


@resource_pages.get("/ui/projects/{project_id}/traceability", name="traceability_page")
def traceability_page(request: Request, project_id: str):
    context = _review_context(request, project_id)
    view = build_traceability_view(context["graph"], context["issues"])
    return templates.TemplateResponse(request=request, name="traceability.html", context={**view, "project_id": project_id, "active": "traceability"})


@resource_pages.get("/ui/projects/{project_id}/rflp", name="rflp_page")
def rflp_page(request: Request, project_id: str, requirement_id: str | None = None):
    context = _review_context(request, project_id)
    view = build_rflp_view(context["graph"], context["issues"], selected_requirement=requirement_id)
    return templates.TemplateResponse(request=request, name="rflp.html", context={**view, "svg": render_rflp_svg(view), "project_id": project_id, "active": "rflp"})


@resource_pages.get("/ui/projects/{project_id}/operational", name="operational_page")
def operational_page(request: Request, project_id: str):
    context = _review_context(request, project_id)
    view = build_operational_view(context["graph"], context["issues"])
    return templates.TemplateResponse(request=request, name="operational.html", context={**view, "project_id": project_id, "active": "operational"})


@resource_pages.get("/ui/projects/{project_id}/behavior", name="behavior_page")
def behavior_page(request: Request, project_id: str):
    context = _review_context(request, project_id)
    view = build_behavior_view(context["graph"], context["issues"])
    return templates.TemplateResponse(request=request, name="behavior.html", context={**view, "project_id": project_id, "active": "behavior"})


@resource_pages.get("/ui/projects/{project_id}/assurance", name="assurance_page")
def assurance_page(request: Request, project_id: str):
    context = _review_context(request, project_id)
    view = build_assurance_view(context["graph"], context["issues"])
    return templates.TemplateResponse(request=request, name="assurance.html", context={**view, "project_id": project_id, "active": "assurance"})


@resource_pages.get("/ui/projects/{project_id}/history", name="history_page")
def history_page(request: Request, project_id: str):
    view = build_history_view(_v2(request).repository(project_id), project_id)
    return templates.TemplateResponse(request=request, name="history.html", context={**view, "project_id": project_id, "active": "history"})


@resource_pages.get("/ui/projects/{project_id}/history/revisions/{revision}/diff", name="revision_diff_page")
def revision_diff_page(request: Request, project_id: str, revision: int):
    repository = _v2(request).repository(project_id)
    after = repository.load_revision(project_id, revision)
    if after is None:
        from rflp_lite.domain.errors import NotFoundError
        raise NotFoundError(f"revision not found: {revision}")
    before = repository.load_revision(project_id, revision - 1)
    diff = build_revision_diff(before, after, revision=revision)
    return templates.TemplateResponse(request=request, name="revision-diff.html", context={**diff, "project_id": project_id, "active": "history"})
