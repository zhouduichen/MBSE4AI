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
    Capability("LLM / Ollama", "partial", "从声明辅助生成模型建议", "OpenAI-compatible LLM Adapter + 页面配置", "Claim", "候选 ModelElement", "完整模型管理、流式对话和远程权限"),
    Capability("Docling", "planned", "解析复杂 PDF/DOCX", "Docling optional adapter", "本地文档", "Artifact / TextSpan", "版面回归与资源上限完成"),
    Capability("SysML v2", "partial", "导入导出 RFLP SysML v2 常用子集文本", "本地 SysML v2 subset bridge；完整语义仍未配置", "RFLP model / .sysml", "Textual SysML subset + SVG", "完整 SysML v2 语义映射和图形编辑"),
    Capability("MLflow", "partial", "将本地运行记录真实写入 MLflow", "可选 MLflow SDK + 本地 file tracking", "Run manifest", "MLflow run / artifacts", "MLflow SDK 或 Tracking Server 配置"),
    Capability("Profile / Pack 编辑", "available", "配置已验证运行参数", "Schema-driven local editor", "Profile JSON", "Validated Profile", "版本迁移和多人协作"),
    Capability("后台任务队列", "available", "记录本地操作的任务状态", "Persistent local job ledger", "Run request", "Job status", "异步 worker、重启恢复和分布式幂等"),
    Capability("对外 Web API", "available", "提供版本化本地 JSON API", "FastAPI /api/v1", "Versioned request", "Versioned response", "认证、限流和公网部署"),
    Capability("登录与权限", "planned", "支持多人和角色边界", "Identity and policy layer", "Identity", "Authorization decision", "威胁模型和审计完成"),
    Capability("插件与远程运行", "partial", "注册并调用本地进程内插件", "Local in-process plugin registry", "Structured payload", "Structured result", "远程隔离、签名和回滚"),
)
