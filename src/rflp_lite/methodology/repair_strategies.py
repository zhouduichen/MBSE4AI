"""Bounded LLM-first and deterministic Rule fallback repair strategies."""

from __future__ import annotations

from dataclasses import dataclass

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.model import ModelGraph, Patch
from rflp_lite.methodology.contracts import ContextBundle, StepStatus, TaskExecutionResponse
from rflp_lite.methodology.coverage import CoverageGap, CoverageReport
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.repair import patch_for_plan, plan_repair
from rflp_lite.methodology.repair_context import RepairContext
from rflp_lite.methodology.repair_planner import RepairTask


@dataclass(frozen=True, slots=True)
class RepairProposal:
    patch: Patch | None
    strategy: str
    target_task: str
    diagnostics: tuple[str, ...] = ()


def _repair_prompt(task: RepairTask) -> str:
    return "\n".join((
        "# Role", "你是受限的 MBSE 语义修复工程师。",
        "# Goal", f"只修复 issue {task.issue_code} 的最小根因。",
        "# Inputs", "只使用提供的根实体、一跳邻居和 evidence。",
        "# MBSE Method", "优先修复关系或单个缺失实体，不重建整个阶段。",
        "# Required Coverage", "补齐目标 trace 的最小断点。",
        "# Semantic Constraints", "保持候选状态，尊重 locked/user_modified。",
        "# Evidence Rules", "只引用上下文中存在的 evidence id。",
        "# Relation Rules", "只使用 RepairTask policy 中的 predicate。",
        "# Forbidden Behavior", "不得改动 unrelated entity 或扩大操作数量。",
        "# Output Guidance", "只返回 TaskProposal JSON，包含 entities、relations、updates、deprecations、reason；不要返回 Patch operations。",
        "# Self-check Before Emitting Proposal", "检查实体 kind、引用、predicate、证据和锁定保护。",
    ))


class LLMRepairStrategy:
    def __init__(self, executor: TaskExecutor):
        self.executor = executor

    def propose(self, context: RepairContext, task: RepairTask) -> RepairProposal | None:
        task_spec = task.as_task_spec(context)
        self.executor.prompts.register(task_spec.prompt_template_id, _repair_prompt(task))
        bundle = ContextBundle(
            context.project_id, task_spec.id, context.graph_revision,
            context.local_entities, context.local_relations, context.evidence,
        )
        request = self.executor.request(task_spec, bundle, "v2.1", context.evidence)
        response = self.executor.execute(task_spec, bundle, "v2.1", evidence_bundle=context.evidence)
        if response.status is not StepStatus.COMPLETED or response.patch is None:
            return RepairProposal(None, "llm", task.target_task_id, response.diagnostics)
        return RepairProposal(response.patch, "llm", task.target_task_id, response.diagnostics + (f"repair_prompt_hash={request.prompt_hash}",))


class RuleFallbackRepairStrategy:
    def propose(self, graph: ModelGraph, context: RepairContext, task: RepairTask) -> RepairProposal:
        fallback_root = {
            "missing_stakeholder": "stakeholder", "missing_lifecycle": "lifecycle",
            "missing_scenario": "scenario", "missing_use_case": "scenario",
            "missing_requirement": "requirement", "missing_function": "function",
            "missing_verification": "verification", "incomplete_rflp_chain": "architecture",
            "broken_requirement_rflp_trace": "architecture",
            "broken_requirement_function_trace": "function",
            "broken_requirement_verification_trace": "verification",
        }.get(context.issue_code, "evidence")
        gap = CoverageGap(context.issue_code, fallback_root, context.root_entity_ids)
        plan = plan_repair(CoverageReport((gap,)), revision=graph.revision)
        patch = patch_for_plan(context.project_id, task.id, graph, plan)
        return RepairProposal(
            patch,
            "rule_fallback",
            task.target_task_id,
            (f"fallback_placeholder={canonical_hash((context.issue_code, context.root_entity_ids))[:12]}",),
        )
