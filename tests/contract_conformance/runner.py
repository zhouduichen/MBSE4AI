"""Small contract benchmark for the structured LLM output boundary."""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.entities import EntityKind, make_entity
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
    "json_parse_rate",
    "schema_pass_rate",
    "proposal_compile_rate",
    "domain_validation_rate",
    "first_pass_success_rate",
    "structural_retry_rate",
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
    duration_ms: int = 0
    diagnostics: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "diagnostics": list(self.diagnostics),
        }


def summarize(samples: list[SampleResult] | tuple[SampleResult, ...]) -> dict[str, float]:
    """Calculate the six conformance rates using all samples as denominator."""

    total = len(samples)
    if total == 0:
        return {name: 0.0 for name in METRIC_NAMES}
    return {
        "json_parse_rate": sum(item.json_parsed for item in samples) / total,
        "schema_pass_rate": sum(item.schema_passed for item in samples) / total,
        "proposal_compile_rate": sum(item.compiled for item in samples) / total,
        "domain_validation_rate": sum(item.domain_valid for item in samples) / total,
        "first_pass_success_rate": sum(
            item.json_parsed and item.schema_passed and item.compiled and item.domain_valid and item.structural_retries == 0
            for item in samples
        ) / total,
        "structural_retry_rate": sum(item.structural_retries > 0 for item in samples) / total,
    }


class _OfflineProposalModel:
    """Schema-shaped fake used for the non-live smoke command."""

    def complete_json(self, request):
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
        for kind in task.input_kinds | task.output_kinds
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


def _sample_from_response(executor: TaskExecutor, task, graph: ModelGraph, context, response) -> SampleResult:
    diagnostics = tuple(response.diagnostics)
    payloads = _diagnostic_payloads(diagnostics)
    structural = next((item for item in payloads if item.get("stage") == FailureStage.STRUCTURAL.value), {})
    retry_count = int(structural.get("retry_count", 0) or 0)
    raw = str(structural.get("raw_response", ""))
    json_parsed = response.status is StepStatus.COMPLETED
    if structural:
        try:
            json.loads(raw)
            json_parsed = True
        except (TypeError, ValueError):
            json_parsed = False
    schema_passed = response.status is StepStatus.COMPLETED
    compiled = response.status is StepStatus.COMPLETED
    domain_valid = False
    if response.status is StepStatus.COMPLETED:
        try:
            executor.validate_response(graph.project_id, task, graph, context, response)
            domain_valid = True
        except Exception as exc:
            diagnostics += (f"domain_validation: {exc}",)
    elif response.failure_stage is FailureStage.COMPILER:
        json_parsed = True
        schema_passed = True
    elif response.failure_stage is FailureStage.STRUCTURAL:
        schema_passed = False
    return SampleResult(
        task_id=task.id,
        iteration=0,
        json_parsed=json_parsed,
        schema_passed=schema_passed,
        compiled=compiled,
        domain_valid=domain_valid,
        structural_retries=retry_count,
        diagnostics=diagnostics,
    )


def _runtime_and_metadata(live: bool):
    if not live:
        return StructuredModelRuntime(_OfflineProposalModel()), {
            "provider_id": "offline-conformance",
            "model_id": "proposal-fixture",
            "profile_id": "offline-conformance",
            "mode": "fixture",
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
        "sampling": {
            "temperature": 0, "think": False, "stream": False,
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
    selected = {task.id: task for task in task_catalog() if task.id in TASK_IDS}
    if tuple(selected) != TASK_IDS:
        raise RuntimeError("conformance task catalog does not contain the required three tasks")
    samples: list[SampleResult] = []
    output_root = Path(os.getenv("PR09_ARTIFACT_ROOT", "docs/superpowers/artifacts/pr09")).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"contract-conformance-{time.time_ns()}.json"
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    schema_hashes = {
        task_id: _schema_hash(executor.request(selected[task_id], context_builder.build(graph, selected[task_id]), "v2.1").output_contract)
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
                context = context_builder.build(graph, task)
                sample_number = len(samples) + 1
                print(f"[PR09] start {sample_number}/{repetitions * len(TASK_IDS)} {task.id}", flush=True)
                started = time.monotonic()
                response = executor.execute(task, context, "v2.1", retry_policy=RetryPolicy(1))
                sample = _sample_from_response(executor, task, graph, context, response)
                samples.append(SampleResult(
                    task_id=sample.task_id,
                    iteration=iteration,
                    json_parsed=sample.json_parsed,
                    schema_passed=sample.schema_passed,
                    compiled=sample.compiled,
                    domain_valid=sample.domain_valid,
                    structural_retries=sample.structural_retries,
                    duration_ms=max(sample.duration_ms, int((time.monotonic() - started) * 1000)),
                    diagnostics=sample.diagnostics,
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
