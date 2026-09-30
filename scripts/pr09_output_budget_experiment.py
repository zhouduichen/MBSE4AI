"""Run the narrow sequential PR09 output-budget experiment.

The experiment deliberately keeps the context planner at the previous
effective budget while changing only the provider output budget.  It is an
experiment driver, not part of the Harness runtime.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from rflp_lite.adapters.llm_client import chat_completion
from rflp_lite.adapters.openai_compatible_model import OpenAICompatibleModel
from rflp_lite.application.llm_profiles import LLMProfileService
from rflp_lite.bootstrap.v2 import build_v2_services
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.methodology.context import ContextBuilder
from rflp_lite.methodology.contracts import Phase, StepStatus
from rflp_lite.methodology.tasks import task_catalog
from rflp_lite.methodology.workflow import WorkflowRunner
from rflp_lite.repository.sqlite import SQLiteModelRepository
from rflp_lite.retrieval.evidence import RetrievalEngine
from rflp_lite.runtime.factory import RuntimeSelection
from rflp_lite.runtime.structured_model import StructuredModelRuntime


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/e2e/fixtures/campus_delivery_robot.json"
CHAIN_TASK_IDS = (
    "system_definition",
    "stakeholder_analysis",
    "stakeholder_requirements",
)


class FixedContextWorkflowRunner(WorkflowRunner):
    """Keep the historical default context reserve while varying output cap."""

    def _configured_output_budget(self) -> bool:
        return False


class CompletionRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self._task_counts: Counter[str] = Counter()

    @staticmethod
    def _task_id(messages: list[dict[str, str]]) -> str:
        for message in reversed(messages):
            try:
                value = json.loads(message.get("content", ""))
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict) and isinstance(value.get("input"), dict):
                task_id = value["input"].get("task_id")
                if isinstance(task_id, str) and task_id:
                    return task_id
        return ""

    def complete(
        self,
        config: dict[str, object],
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> str:
        task_id = self._task_id(messages)
        call_number = self._task_counts[task_id]
        self._task_counts[task_id] += 1
        started = time.monotonic()
        try:
            raw = chat_completion(config, messages, max_tokens=max_tokens)
        except Exception as exc:
            self.calls.append({
                "task_id": task_id,
                "call": "initial" if call_number == 0 else "repair",
                "max_tokens": max_tokens,
                "exception_type": type(exc).__name__,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
            })
            raise
        text = str(raw or "")
        usage = getattr(raw, "usage", {}) or {}
        self.calls.append({
            "task_id": task_id,
            "call": "initial" if call_number == 0 else "repair",
            "max_tokens": max_tokens,
            "finish_reason": str(getattr(raw, "done_reason", "")),
            "prompt_eval_count": usage.get("prompt_eval_count"),
            "eval_count": usage.get("eval_count"),
            "total_duration_ms": round((usage.get("total_duration", 0) or 0) / 1_000_000, 3),
            "response_size": len(text),
            "response_hash": canonical_hash(text),
            "wall_duration_ms": round((time.monotonic() - started) * 1000, 3),
        })
        return raw


def _json_objects(raw: object) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    if not raw:
        return result
    try:
        items = json.loads(str(raw))
    except (TypeError, ValueError):
        return result
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, str):
            continue
        try:
            value = json.loads(item)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _usage_from_diagnostics(raw: object) -> dict[str, object]:
    if not raw:
        return {}
    try:
        items = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    if not isinstance(items, list):
        return {}
    for item in items:
        if not isinstance(item, str):
            continue
        match = re.search(r"usage=(\{.*\})$", item)
        if match:
            try:
                value = json.loads(match.group(1))
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    return {}


def _load_ledger(db_path: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    project = connection.execute("select revision from projects limit 1").fetchone()
    entities = connection.execute("select count(*) from entities").fetchone()[0]
    relations = connection.execute("select count(*) from relations").fetchone()[0]
    steps: list[dict[str, object]] = []
    for row in connection.execute(
        "select task_id,status,attempt,output_patch_id,diagnostics,output_hash,provider_id,model_id "
        "from steps order by rowid"
    ):
        objects = _json_objects(row["diagnostics"])
        object_diag = objects[0] if objects else {}
        usage = object_diag.get("usage") if isinstance(object_diag.get("usage"), dict) else _usage_from_diagnostics(row["diagnostics"])
        code = str(object_diag.get("code", ""))
        stage = str(object_diag.get("stage", ""))
        failure_class = ""
        if stage and code:
            failure_class = f"{stage}.{code}"
        duplicate_ref = ""
        match = re.search(
            r"duplicate task proposal local_ref: ([^\s]+)",
            str(object_diag.get("message", "")),
        )
        if match:
            duplicate_ref = match.group(1)
        steps.append({
            "task_id": row["task_id"],
            "status": row["status"],
            "attempt": row["attempt"],
            "output_patch_id": row["output_patch_id"],
            "output_hash": row["output_hash"],
            "provider_id": row["provider_id"],
            "model_id": row["model_id"],
            "stage": stage,
            "code": code,
            "failure_class": failure_class,
            "finish_reason": str(object_diag.get("finish_reason", "")),
            "retry_count": int(object_diag.get("retry_count", 0) or 0),
            "raw_response_hash": object_diag.get("raw_response_hash"),
            "raw_response_size": object_diag.get("raw_response_size"),
            "initial_raw_response_hash": object_diag.get("initial_raw_response_hash"),
            "initial_raw_response_size": object_diag.get("initial_raw_response_size"),
            "schema_hash": object_diag.get("schema_hash"),
            "usage": usage,
            "duplicate_local_ref": duplicate_ref,
        })
    run = connection.execute("select id,status,provider_id,model_id from runs limit 1").fetchone()
    connection.close()
    return {
        "run_id": run["id"],
        "run_status": run["status"],
        "provider_id": run["provider_id"],
        "model_id": run["model_id"],
        "revision": int(project["revision"]),
        "entities": int(entities),
        "relations": int(relations),
        "steps": steps,
    }


def _runtime_config(budget: int) -> dict[str, object]:
    profile = LLMProfileService().active_config()
    if not profile:
        raise RuntimeError("no active LLM profile")
    return {
        "id": str(profile["id"]),
        "label": str(profile.get("label", profile["id"])),
        "provider": str(profile.get("provider", "ollama")),
        "kind": str(profile.get("kind", "local")),
        "protocol": str(profile.get("protocol", "openai-chat")),
        "base_url": str(profile["base_url"]),
        "model": str(profile["model"]),
        "timeout_seconds": int(profile.get("timeout_seconds", 300)),
        "temperature": float(profile.get("temperature", 0.0) or 0.0),
        "structured_output_mode": str(profile.get("structured_output_mode", "json_schema")),
        "max_output_tokens": budget,
    }


def _one_run(budget: int, repetition: int, root: Path) -> dict[str, object]:
    workspace = root / f"budget-{budget}" / f"repeat-{repetition:02d}"
    workspace.mkdir(parents=True, exist_ok=True)
    config = _runtime_config(budget)
    recorder = CompletionRecorder()
    model = OpenAICompatibleModel(config, complete=recorder.complete)
    runtime = StructuredModelRuntime(model)
    selection = RuntimeSelection(
        runtime,
        str(config["id"]),
        str(config["provider"]),
        str(config["model"]),
        "configured",
        None,
        budget,
        float(config["temperature"]),
        None,
        str(config["structured_output_mode"]),
    )
    services = build_v2_services(
        workspace,
        runtime_config=config,
        config_dir=workspace / "empty-config",
    )
    services.projects.create("campus", "校园无人配送机器人")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    services.projects.seed_fixture("campus", fixture, source_path=FIXTURE)
    repository = services.repository("campus")
    runner = FixedContextWorkflowRunner(
        repository,
        repository,
        runtime,
        ContextBuilder(RetrievalEngine(repository)),
        runtime_selection=selection,
    )
    selected = tuple(task for task in task_catalog() if task.id in CHAIN_TASK_IDS)
    if tuple(task.id for task in selected) != CHAIN_TASK_IDS:
        raise RuntimeError("narrow chain task catalog order changed")
    import rflp_lite.methodology.workflow as workflow_module

    original_tasks_for_phase = workflow_module.tasks_for_phase

    def narrow_tasks_for_phase(phase: Phase):
        if phase is Phase.OPERATIONAL:
            return selected
        return original_tasks_for_phase(phase)

    workflow_module.tasks_for_phase = narrow_tasks_for_phase
    try:
        summary = runner.run("campus", Phase.OPERATIONAL, force_run=True)
    finally:
        workflow_module.tasks_for_phase = original_tasks_for_phase
    ledger = _load_ledger(workspace / "campus" / ".rflp" / "model.db")
    task_records = []
    calls_by_task: dict[str, list[dict[str, object]]] = defaultdict(list)
    for call in recorder.calls:
        calls_by_task[str(call.get("task_id", ""))].append(call)
    for step in ledger["steps"]:
        task_id = str(step["task_id"])
        calls = calls_by_task.get(task_id, [])
        output_tokens = [call.get("eval_count") for call in calls if isinstance(call.get("eval_count"), int)]
        utilization = [
            round(float(call["eval_count"]) / float(call["max_tokens"]), 6)
            for call in calls
            if isinstance(call.get("eval_count"), int) and isinstance(call.get("max_tokens"), int) and call["max_tokens"] > 0
        ]
        task_records.append({
            **step,
            "json_parsed": step["status"] == StepStatus.COMPLETED.value or step["stage"] == "compiler",
            "schema_passed": step["status"] == StepStatus.COMPLETED.value or step["stage"] == "compiler",
            "compile_pass": step["status"] == StepStatus.COMPLETED.value,
            "domain_validation_pass": step["status"] == StepStatus.COMPLETED.value,
            "structural_repair_invoked": len(calls) > 1,
            "structural_retry_recovered": len(calls) > 1 and step["status"] == StepStatus.COMPLETED.value,
            "duplicate_local_ref": step["duplicate_local_ref"],
            "provider_calls": calls,
            "initial_max_tokens": calls[0].get("max_tokens") if calls else None,
            "repair_max_tokens": calls[1].get("max_tokens") if len(calls) > 1 else None,
            "output_utilization": utilization,
            "output_tokens": output_tokens,
        })
    result = {
        "repetition": repetition,
        "budget": budget,
        "workspace": str(workspace),
        "summary": {
            "run_id": summary.run_id,
            "phase": summary.phase.value,
            "status": summary.status.value,
            "completed_tasks": list(summary.completed_tasks),
            "failure_stage": summary.failure_stage.value if summary.failure_stage else None,
            "diagnostics": list(summary.diagnostics),
        },
        "task_records": task_records,
        "provider_calls": recorder.calls,
        "ledger": ledger,
        "safety": {
            "failed_task_with_patch": any(item["status"] == "failed" and item["output_patch_id"] for item in task_records),
            "blocked_task_with_patch": any(item["status"] == "blocked" and item["output_patch_id"] for item in task_records),
            "initial_revision": 1,
            "final_revision": ledger["revision"],
            "initial_entities": 16,
            "final_entities": ledger["entities"],
            "initial_relations": 28,
            "final_relations": ledger["relations"],
        },
    }
    print(json.dumps({
        "budget": budget,
        "repetition": repetition,
        "status": summary.status.value,
        "task_statuses": {item["task_id"]: item["status"] for item in task_records},
        "provider_calls": len(recorder.calls),
        "finish_reasons": [call.get("finish_reason", "") for call in recorder.calls],
    }, ensure_ascii=False), flush=True)
    return result


def _aggregate(budget: int, runs: list[dict[str, object]]) -> dict[str, object]:
    tasks = [task for run in runs for task in run["task_records"]]
    calls = [call for run in runs for call in run["provider_calls"]]
    statuses = Counter(str(task["status"]) for task in tasks)
    classes = Counter(str(task["failure_class"]) for task in tasks if task["failure_class"])
    finish_reasons = Counter(str(call.get("finish_reason", "")) for call in calls if call.get("finish_reason"))
    utilization = [value for task in tasks for value in task["output_utilization"]]
    latency = [float(call["total_duration_ms"]) for call in calls if isinstance(call.get("total_duration_ms"), (int, float)) and call.get("total_duration_ms")]
    retries = [task for task in tasks if task["structural_repair_invoked"]]
    return {
        "budget": budget,
        "repetitions": len(runs),
        "chain": list(CHAIN_TASK_IDS),
        "runs": runs,
        "aggregate": {
            "task_status": dict(statuses),
            "run_status": dict(Counter(str(run["summary"]["status"]) for run in runs)),
            "provider_calls": len(calls),
            "provider_transport_failures": sum(1 for call in calls if call.get("exception_type")),
            "finish_reason": dict(finish_reasons),
            "failure_classes": dict(classes),
            "structural_retry_invoked": len(retries),
            "structural_retry_recovered": sum(1 for task in retries if task["structural_retry_recovered"]),
            "structural_retry_exhausted": sum(1 for task in retries if not task["structural_retry_recovered"]),
            "compiler_failures": sum(1 for task in tasks if task["failure_class"] == "compiler.proposal_compile"),
            "duplicate_local_ref_count": sum(1 for task in tasks if task["duplicate_local_ref"]),
            "semantic_rejections": sum(1 for task in tasks if task["status"] == "degraded" and task["stage"] == ""),
            "semantic_repair_invoked": 0,
            "output_utilization": {
                "samples": len(utilization),
                "average": round(sum(utilization) / len(utilization), 6) if utilization else 0.0,
                "min": min(utilization) if utilization else None,
                "max": max(utilization) if utilization else None,
            },
            "latency_ms": {
                "samples": len(latency),
                "average": round(sum(latency) / len(latency), 3) if latency else 0.0,
                "min": min(latency) if latency else None,
                "max": max(latency) if latency else None,
            },
            "initial_max_tokens": sorted({task["initial_max_tokens"] for task in tasks if task["initial_max_tokens"] is not None}),
            "repair_max_tokens": sorted({task["repair_max_tokens"] for task in tasks if task["repair_max_tokens"] is not None}),
            "failed_or_blocked_with_patch": sum(1 for task in tasks if task["status"] in {"failed", "blocked"} and task["output_patch_id"]),
            "dependent_blocking_observed": any(task["status"] == "blocked" for task in tasks),
            "revision_deltas": [run["safety"]["final_revision"] - run["safety"]["initial_revision"] for run in runs],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=int, required=True, choices=(3000, 4000))
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root or Path(tempfile.mkdtemp(prefix="ai4mbse-pr09-budget-"))
    runs = [_one_run(args.budget, repetition, root) for repetition in range(1, args.repetitions + 1)]
    result = {
        "experiment": "pr09-output-budget-narrow-sequential-chain",
        "date": "2026-09-13",
        "baseline_commit": "7bf00c2f9ab2e31287a7539b08e2ad7ee25258e4",
        "fixture": str(FIXTURE),
        "provider": {
            "display_name": "Windows 5080 Ollama",
            "provider_id": "ollama",
            "runtime_provider_id": "windows-5080-ollama",
            "model": "qwen3.5:9b-q8_0",
            "temperature": 0.0,
            "seed": None,
            "structured_output_mode": "json_schema",
        },
        "fixed_context": {
            "effective_context_budget": 2000,
            "output_reserve": "historical default (profile output budget omitted)",
            "prompt_reserve": 256,
        },
        "variable": "max_output_tokens",
        "known_2000_baseline": "See structured-execution-forensics-20260913.json; not rerun.",
        **_aggregate(args.budget, runs),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("AGGREGATE " + json.dumps({
        "budget": args.budget,
        "repetitions": args.repetitions,
        "aggregate": result["aggregate"],
        "output": str(args.output) if args.output else None,
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
