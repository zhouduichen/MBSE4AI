from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rflp_lite.application.run_catalog import RunRecord
from rflp_lite.application.workspaces import WorkspaceRef


def short_hash(value: object, length: int = 12) -> str:
    text = str(value or "")
    return text if len(text) <= length else f"{text[:length]}…"


def page_context(
    workspace: WorkspaceRef | None,
    *,
    workspaces: tuple[WorkspaceRef, ...] = (),
    active: str = "dashboard",
    nav_result_hash: str | None = None,
    **values: Any,
) -> dict[str, object]:
    return {
        "workspace": workspace,
        "workspaces": workspaces,
        "active": active,
        "nav_result_hash": nav_result_hash,
        "short_hash": short_hash,
        **values,
    }


def run_detail_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    return page_context(
        workspace,
        active="runs",
        nav_result_hash=record.result_hash,
        run=record,
        manifest=record.outputs["run-manifest.json"],
        decision=record.outputs["decision.json"],
        simulation=record.outputs["simulation.json"],
        baseline=record.outputs["baseline.json"],
        files=tuple(record.outputs),
    )


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    status: str
    purpose: str
    dependency: str
    expected_input: str
    expected_output: str
    enable_when: str


LAYER_ORDER = ("R", "F", "L", "P")
LAYER_NAMES = {
    "R": "Requirement",
    "F": "Function",
    "L": "Logical",
    "P": "Physical",
}


def artifacts_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    artifacts = record.outputs["artifacts.json"]
    spans = record.outputs["spans.json"]
    claims = record.outputs["claims.json"]
    return page_context(
        workspace,
        active="artifacts",
        nav_result_hash=record.result_hash,
        run=record,
        artifacts=artifacts,
        spans=spans,
        claims=claims,
    )


def rflp_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    model = record.outputs["rflp.json"]
    grouped = {
        layer: tuple(item for item in model["elements"] if item["layer"] == layer)
        for layer in LAYER_ORDER
    }
    return page_context(
        workspace,
        active="rflp",
        nav_result_hash=record.result_hash,
        run=record,
        layers=grouped,
        layer_names=LAYER_NAMES,
        relations=model["relations"],
    )


def candidates_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    candidates = tuple(
        sorted(record.outputs["candidates.json"], key=lambda item: (-item["score"], item["id"]))
    )
    return page_context(
        workspace,
        active="candidates",
        nav_result_hash=record.result_hash,
        run=record,
        candidates=candidates,
        decision=record.outputs["decision.json"],
    )


def simulation_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    simulation = record.outputs["simulation.json"]
    events = tuple(
        sorted(
            simulation["events"],
            key=lambda item: (item["time"], item["priority"], item["sequence"]),
        )
    )
    return page_context(
        workspace,
        active="simulation",
        nav_result_hash=record.result_hash,
        run=record,
        simulation=simulation,
        events=events,
    )


def baselines_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    return page_context(
        workspace,
        active="baselines",
        nav_result_hash=record.result_hash,
        run=record,
        baseline=record.outputs["baseline.json"],
        delta=record.outputs["delta.json"],
    )


def tasks_context(workspace: WorkspaceRef, record: RunRecord) -> dict[str, object]:
    return page_context(
        workspace,
        active="tasks",
        nav_result_hash=record.result_hash,
        run=record,
        tasks=record.outputs["task-contracts.json"],
    )


def evidence_context(
    workspace: WorkspaceRef,
    record: RunRecord,
    audit: tuple[dict[str, object], ...],
) -> dict[str, object]:
    evidence = record.outputs["evidence.json"]
    kinds = tuple(sorted({item["kind"] for item in evidence}))
    grouped = {kind: tuple(item for item in evidence if item["kind"] == kind) for kind in kinds}
    return page_context(
        workspace,
        active="evidence",
        nav_result_hash=record.result_hash,
        run=record,
        evidence_groups=grouped,
        audit=audit,
    )


CAPABILITIES = (
    Capability("LLM / Ollama", "planned", "从声明辅助生成模型建议", "Ollama 或兼容 LLM Adapter", "Claim", "候选 ModelElement", "契约、审计与人工批准门禁完成"),
    Capability("Docling", "planned", "解析复杂 PDF/DOCX", "Docling optional adapter", "本地文档", "Artifact / TextSpan", "版面回归与资源上限完成"),
    Capability("SysML v2", "planned", "导入、导出与图形编辑", "SysML v2 repository adapter", "RFLP model", "SysML v2 model", "映射契约和往返测试完成"),
    Capability("MLflow", "planned", "追踪实验与参数", "MLflow adapter", "Run manifest", "Experiment record", "本地存储策略完成"),
    Capability("Profile / Pack 编辑", "planned", "配置已验证运行参数", "Schema-driven editor", "Profile JSON", "Validated Profile", "字段校验和版本迁移完成"),
    Capability("后台任务队列", "planned", "承载长耗时运行", "Persistent job repository", "Run request", "Job status", "重启恢复和幂等完成"),
    Capability("对外 Web API", "planned", "为受控客户端提供契约接口", "Versioned API adapter", "Versioned request", "Versioned response", "认证、限流和 OpenAPI 契约完成"),
    Capability("登录与权限", "planned", "支持多人和角色边界", "Identity and policy layer", "Identity", "Authorization decision", "威胁模型和审计完成"),
    Capability("插件与远程运行", "planned", "接入受控外部能力", "Signed runtime protocol", "TaskContract", "Evidence", "隔离、签名和回滚完成"),
)
