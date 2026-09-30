"""Small contract benchmark for the structured LLM output boundary."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping

from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.errors import MethodologyValidationError
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import FailureStage, StepStatus
from rflp_lite.methodology.executor import TaskExecutor
from rflp_lite.methodology.registries import RetryPolicy
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.runtime.factory import RuntimeFactory
from rflp_lite.runtime.structured_model import StructuredModelRuntime
from rflp_lite.ports.generative_model import GenerationResponse


TASK_IDS = (
    "system_definition",
    "stakeholder_requirements",
    "function_identification",
)
METRIC_NAMES = (
    "provider_success_rate",
    "json_parse_rate",
    "schema_pass_rate",
    "proposal_compile_rate",
    "domain_validation_rate",
    "first_pass_success_rate",
    "structural_retry_rate",
    "retry_recovery_rate",
    "semantic_rejection_rate",
    "blocked_count",
    "mean_output_tokens",
    "mean_latency_ms",
)


@dataclass(frozen=True, slots=True)
class SampleResult:
    task_id: str = ""
    iteration: int = 0
    json_parsed: bool = False
    schema_passed: bool = False
    compiled: bool = False
    domain_valid: bool = False
    structural_retries: int = 0
    retry_recovered: bool = False
    semantic_rejected: bool = False
    blocked: bool = False
    provider_success: bool = False
    status: str = ""
    failure_stage: str = ""
    output_tokens: int = 0
    duration_ms: int = 0
    diagnostics: tuple[str, ...] = ()
    provider_id: str = ""
    model_id: str = ""
    prompt_hash: str = ""
    schema_hash: str = ""
    finish_reason: str = ""
    usage: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "diagnostics": list(self.diagnostics),
        }


def summarize(samples: list[SampleResult] | tuple[SampleResult, ...]) -> dict[str, float]:
    """Calculate funnel metrics without counting blocked tasks as executions."""

    total = len(samples)
    if total == 0:
        return {name: 0.0 for name in METRIC_NAMES}
    compiled = [item for item in samples if item.compiled and not item.blocked]
    retry_samples = [item for item in samples if item.structural_retries > 0]
    return {
        "provider_success_rate": sum(item.provider_success for item in samples) / total,
        "json_parse_rate": sum(item.json_parsed for item in samples) / total,
        "schema_pass_rate": sum(item.schema_passed for item in samples) / total,
        "proposal_compile_rate": sum(item.compiled for item in samples) / total,
        "domain_validation_rate": sum(item.domain_valid for item in samples) / total,
        "first_pass_success_rate": sum(
            item.provider_success
            and item.json_parsed
            and item.schema_passed
            and item.compiled
            and item.domain_valid
            and item.structural_retries == 0
            for item in samples
        ) / total,
        "structural_retry_rate": sum(item.structural_retries > 0 for item in samples) / total,
        "retry_recovery_rate": (
            sum(item.retry_recovered for item in retry_samples) / len(retry_samples)
            if retry_samples else 0.0
        ),
        "semantic_rejection_rate": (
            sum(item.semantic_rejected for item in compiled) / len(compiled)
            if compiled else 0.0
        ),
        "blocked_count": float(sum(item.blocked for item in samples)),
        "mean_output_tokens": sum(item.output_tokens for item in samples) / total,
        "mean_latency_ms": sum(item.duration_ms for item in samples) / total,
    }


class _OfflineProposalModel:
    """Schema-shaped fake used for the non-live smoke command."""

    def complete_json(self, request):
        if request.lens_id == "system_definition":
            payload = {
                "entities": [{
                    "local_ref": "new:system:1",
                    "name": "conformance-system",
                    "payload": {
                        "mission": "完成 conformance smoke",
                        "system_boundary": {"inside": [], "outside": []},
                        "objectives": ["通过结构化契约检查"],
                        "environment_assumptions": [],
                        "exclusions": [],
                        "open_questions": [],
                    },
                }],
                "relations": [],
                "updates": [],
                "deprecations": [],
                "reason": "创建 conformance system",
            }
        elif request.lens_id == "stakeholder_requirements":
            concern = next(
                item
                for item in request.user_payload["context"]["entities"]
                if item["kind"] == EntityKind.CONCERN.value
            )
            payload = {
                "entities": [{
                    "local_ref": "new:requirement:1",
                    "name": "conformance-stakeholder-requirement",
                    "payload": {
                        "level": "stakeholder",
                        "type": "functional",
                        "obligation": "系统应支持 conformance smoke",
                        "verification_method": "review",
                        "rationale": "来源于 conformance concern",
                    },
                }],
                "relations": [{
                    "source_ref": "new:requirement:1",
                    "predicate": "derivedFrom",
                    "target_ref": concern["id"],
                    "evidence_ids": [],
                }],
                "updates": [],
                "deprecations": [],
                "reason": "创建 conformance stakeholder requirement",
            }
        else:
            payload = {"entities": [], "relations": [], "updates": [], "deprecations": [], "reason": "无变化"}
        return GenerationResponse(
            request.lens_id,
            payload,
            canonical_hash(request.user_payload),
            canonical_hash(payload),
            False,
            "offline-conformance",
            "proposal-fixture",
        )


def _seed_graph() -> ModelGraph:
    kinds = {
        kind
        for task in task_catalog()
        if task.id in TASK_IDS
        for kind in task.input_kinds
        if kind not in task.output_kinds
    }
    entities = tuple(
        make_entity(kind, f"conformance-{kind.value}", {"source": "pr09-conformance"})
        for kind in sorted(kinds, key=lambda item: item.value)
    )
    return ModelGraph("pr09-conformance", entities, (), 0)


def _diagnostic_payloads(diagnostics: tuple[str, ...]) -> list[Mapping[str, object]]:
    result = []
    for item in diagnostics:
        try:
            value = json.loads(item)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _schema_hash(contract: Mapping[str, object]) -> str:
    return canonical_hash({
        key: contract[key]
        for key in ("type", "additionalProperties", "required", "properties", "allOf")
        if key in contract
    })


def _sample_from_response(
    executor: TaskExecutor,
    task,
    graph: ModelGraph,
    context,
    response,
    request=None,
) -> SampleResult:
    diagnostics = tuple(response.diagnostics)
    payloads = _diagnostic_payloads(diagnostics)
    structural = next((item for item in payloads if item.get("stage") == FailureStage.STRUCTURAL.value), {})
    retry_count = int(structural.get("retry_count", 0) or 0)
    code = str(structural.get("code", ""))
    json_parsed = response.status is StepStatus.COMPLETED or (
        bool(structural) and code not in {"json_decode", "truncated"}
    )
    schema_passed = response.status is StepStatus.COMPLETED
    compiled = response.status is StepStatus.COMPLETED
    domain_valid = False
    semantic_rejected = False
    if response.status is StepStatus.COMPLETED:
        try:
            executor.validate_response(graph.project_id, task, graph, context, response)
            domain_valid = True
        except MethodologyValidationError as exc:
            semantic_rejected = exc.code == "semantic_invalid"
            diagnostics += (f"domain_validation: {exc}",)
        except Exception as exc:
            diagnostics += (f"domain_validation: {exc}",)
    elif response.failure_stage is FailureStage.COMPILER:
        json_parsed = True
        schema_passed = True
    elif response.failure_stage is FailureStage.STRUCTURAL:
        schema_passed = False
    structural_retries = max(retry_count, int(response.repaired))
    usage = dict(response.usage or {})
    output_tokens = next(
        (
            int(usage[key])
            for key in ("completion_tokens", "output_tokens", "eval_count")
            if usage.get(key) is not None and str(usage[key]).lstrip("-").isdigit()
        ),
        0,
    )
    failure_stage = (
        response.failure_stage.value
        if response.failure_stage is not None
        else str(structural.get("stage", ""))
    )
    return SampleResult(
        task_id=task.id,
        iteration=0,
        json_parsed=json_parsed,
        schema_passed=schema_passed,
        compiled=compiled,
        domain_valid=domain_valid,
        structural_retries=structural_retries,
        retry_recovered=structural_retries > 0 and compiled and domain_valid,
        semantic_rejected=compiled and semantic_rejected,
        blocked=response.status is StepStatus.BLOCKED,
        provider_success=response.failure_stage is not FailureStage.TRANSPORT,
        status=response.status.value,
        failure_stage=failure_stage,
        output_tokens=output_tokens,
        diagnostics=diagnostics,
        provider_id=response.provider_id,
        model_id=response.model_id,
        prompt_hash=request.prompt_hash if request is not None else "",
        schema_hash=_schema_hash(request.output_contract) if request is not None else "",
        finish_reason=response.finish_reason,
        usage=response.usage,
    )


def _runtime_and_metadata(live: bool):
    if not live:
        return StructuredModelRuntime(_OfflineProposalModel()), {
            "provider_id": "offline-conformance",
            "model_id": "proposal-fixture",
            "profile_id": "offline-conformance",
            "mode": "fixture",
            "context_window": None,
            "max_output_tokens": None,
            "sampling": {"temperature": 0},
        }
    config = LLMProfileService().active_config()
    if not config:
        raise RuntimeError("no active LLM profile; configure the Ollama profile before --live")
    benchmark_config = dict(config)
    try:
        configured_timeout = int(benchmark_config.get("timeout_seconds", 300))
    except (TypeError, ValueError):
        configured_timeout = 300
    try:
        benchmark_timeout = int(os.getenv("PR09_LIVE_TIMEOUT_SECONDS", "60"))
    except ValueError:
        benchmark_timeout = 60
    benchmark_config["timeout_seconds"] = max(5, min(configured_timeout, benchmark_timeout, 300))
    selection = RuntimeFactory().select(benchmark_config)
    return selection.runtime, {
        "provider_id": selection.provider_id,
        "model_id": selection.model_id,
        "profile_id": selection.profile_id,
        "mode": selection.mode,
        "context_window": selection.context_window,
        "max_output_tokens": selection.max_output_tokens,
        "sampling": {
            "temperature": selection.temperature,
            "seed": selection.seed,
            "think": False, "stream": False,
            "timeout_seconds": benchmark_config["timeout_seconds"],
        },
    }


def run_conformance(repetitions: int = 20, live: bool = False) -> dict[str, object]:
    """Run exactly three tasks and return an auditable conformance report."""

    repetitions = int(repetitions)
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    live = bool(live or os.getenv("RFLP_RUN_LIVE_LLM", "") == "1")
    runtime, metadata = _runtime_and_metadata(live)
    executor = TaskExecutor(runtime)
    graph = _seed_graph()
    context_builder = ContextBuilder()
    try:
        context_budget = int(metadata.get("context_window") or 2000)
    except (TypeError, ValueError):
        context_budget = 2000
    try:
        output_budget = int(metadata.get("max_output_tokens") or 2000)
    except (TypeError, ValueError):
        output_budget = 2000
    selected = {task.id: task for task in task_catalog() if task.id in TASK_IDS}
    if tuple(selected) != TASK_IDS:
        raise RuntimeError("conformance task catalog does not contain the required three tasks")
    samples: list[SampleResult] = []
    output_root = Path(os.getenv("PR09_ARTIFACT_ROOT", "docs/superpowers/artifacts/pr09")).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"contract-conformance-{time.time_ns()}.json"
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    schema_hashes = {
        task_id: _schema_hash(executor.request(
            selected[task_id],
            context_builder.build(
                graph,
                selected[task_id],
                token_budget=context_budget,
                output_reserve=output_budget,
                prompt_reserve=256,
            ),
            "v2.1",
            token_budget=output_budget,
        ).output_contract)
        for task_id in TASK_IDS
    }

    def write_report(status: str) -> dict[str, object]:
        result: dict[str, object] = {
            "benchmark": "pr09-contract-conformance",
            "status": status,
            "created_at": created_at,
            "repetitions": repetitions,
            "tasks": list(TASK_IDS),
            "sample_count": len(samples),
            **metadata,
            "schema_hashes": schema_hashes,
            "metrics": summarize(samples),
            "status_counts": dict(Counter(sample.status for sample in samples)),
            "failure_stage_counts": dict(Counter(sample.failure_stage for sample in samples if sample.failure_stage)),
            "finish_reason_counts": dict(Counter(sample.finish_reason for sample in samples if sample.finish_reason)),
            "samples": [sample.as_dict() for sample in samples],
            "result_path": str(output_path),
        }
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return result

    write_report("running")
    try:
        for iteration in range(1, repetitions + 1):
            for task_id in TASK_IDS:
                task = selected[task_id]
                context = context_builder.build(
                    graph,
                    task,
                    token_budget=context_budget,
                    output_reserve=output_budget,
                    prompt_reserve=256,
                )
                sample_number = len(samples) + 1
                print(f"[PR09] start {sample_number}/{repetitions * len(TASK_IDS)} {task.id}", flush=True)
                started = time.monotonic()
                request = executor.request(
                    task,
                    context,
                    "v2.1",
                    token_budget=output_budget,
                )
                response = executor.execute(
                    task,
                    context,
                    "v2.1",
                    token_budget=output_budget,
                    retry_policy=RetryPolicy(1),
                )
                sample = _sample_from_response(executor, task, graph, context, response, request)
                samples.append(SampleResult(
                    task_id=sample.task_id,
                    iteration=iteration,
                    json_parsed=sample.json_parsed,
                    schema_passed=sample.schema_passed,
                    compiled=sample.compiled,
                    domain_valid=sample.domain_valid,
                    structural_retries=sample.structural_retries,
                    retry_recovered=sample.retry_recovered,
                    semantic_rejected=sample.semantic_rejected,
                    blocked=sample.blocked,
                    provider_success=sample.provider_success,
                    status=sample.status,
                    failure_stage=sample.failure_stage,
                    output_tokens=sample.output_tokens,
                    duration_ms=max(sample.duration_ms, int((time.monotonic() - started) * 1000)),
                    diagnostics=sample.diagnostics,
                    provider_id=sample.provider_id or metadata["provider_id"],
                    model_id=sample.model_id or metadata["model_id"],
                    prompt_hash=sample.prompt_hash,
                    schema_hash=sample.schema_hash,
                    finish_reason=sample.finish_reason,
                    usage=sample.usage,
                ))
                write_report("running")
                print(
                    f"[PR09] done {sample_number}/{repetitions * len(TASK_IDS)} {task.id} "
                    f"parse={sample.json_parsed} schema={sample.schema_passed} "
                    f"compile={sample.compiled} duration_ms={samples[-1].duration_ms}",
                    flush=True,
                )
    except KeyboardInterrupt:
        write_report("interrupted")
        raise
    return write_report("completed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the PR09 three-task contract conformance benchmark")
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--live", action="store_true", help="use the active configured LLM profile")
    args = parser.parse_args()
    result = run_conformance(args.repetitions, args.live)
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
