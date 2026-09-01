from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from rflp_lite.application.dependencies import ApplicationDependencies, configured_dependencies
from rflp_lite.ports.test_execution import (
    DEFAULT_TEST_TIMEOUT,
    ResourceLimits,
    build_limits,
)
from rflp_lite.application.diff import compare_baseline_with_actual
from rflp_lite.application.tasks import build_task_contracts
from rflp_lite.domain.baseline import approve_baseline
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.domain.models import (
    ActualModel,
    Baseline,
    Delta,
    Evidence,
    ModelElement,
    Relation,
    TaskContract,
)


_EVIDENCE_KINDS = {
    "module": "python-module",
    "class": "python-class",
    "function": "python-function",
    "api-operation": "openapi-operation",
    "test-case": "test-case",
}
@dataclass(frozen=True, slots=True)
class BridgeArtifacts:
    baseline: Baseline
    actual: ActualModel
    evidence: tuple[Evidence, ...]
    delta: Delta
    tasks: tuple[TaskContract, ...]


def _clone(value: dict[str, object]) -> dict[str, object]:
    return __import__("json").loads(canonical_json(value))


def reconstruct_rflp(
    state: dict[str, object],
) -> tuple[tuple[ModelElement, ...], tuple[Relation, ...]]:
    """从工作台 state["rflp"] 的序列化结构重建领域对象。"""
    rflp = state.get("rflp") or {}
    elements = tuple(
        ModelElement(
            id=item["id"],
            layer=item["layer"],
            name=item["name"],
            status=item.get("status", "approved"),
            kind=item.get("kind", "element"),
            attributes=tuple((str(key), value) for key, value in item.get("attributes", ())),
        )
        for item in rflp.get("elements", ())
    )
    relations = tuple(
        Relation(
            id=item["id"],
            source_id=item["source_id"],
            predicate=item["predicate"],
            target_id=item["target_id"],
        )
        for item in rflp.get("relations", ())
    )
    return elements, relations


def _baseline_from_state(state: dict[str, object]) -> Baseline:
    data = state.get("baseline") or {}
    elements = tuple(
        ModelElement(
            id=item["id"],
            layer=item["layer"],
            name=item["name"],
            status=item.get("status", "approved"),
            kind=item.get("kind", "element"),
            attributes=tuple((str(key), value) for key, value in item.get("attributes", ())),
        )
        for item in data.get("elements", ())
    )
    relations = tuple(
        Relation(
            id=item["id"],
            source_id=item["source_id"],
            predicate=item["predicate"],
            target_id=item["target_id"],
        )
        for item in data.get("relations", ())
    )
    payload = (
        ("elements", elements),
        ("relations", relations),
    )
    return Baseline(
        id=data["id"],
        status=data["status"],
        elements=elements,
        relations=relations,
        payload=payload,
        hash=data["hash"],
    )


def approve_workbench_baseline(
    state: dict[str, object],
) -> tuple[dict[str, object], Baseline]:
    """人工显式批准工作台 RFLP 为基线。"""
    if not state.get("rflp"):
        raise ContractViolation("请先生成 RFLP 规划图")
    if state.get("draft"):
        raise ContractViolation("请先生成 RFLP 规划图；当前输出仍是快速草稿")
    elements, relations = reconstruct_rflp(state)
    baseline = approve_baseline(elements, relations)
    result = _clone(state)
    result["baseline"] = {
        "id": baseline.id,
        "status": baseline.status,
        "hash": baseline.hash,
        "elements": [asdict(item) for item in baseline.elements],
        "relations": [asdict(item) for item in baseline.relations],
    }
    result["project"] = None
    return result, baseline


def evidence_from_actual(model: ActualModel) -> tuple[Evidence, ...]:
    """为 ActualModel 中每个元素派生一条确定性观察证据。"""
    evidence = tuple(
        Evidence(
            id=f"evidence-{canonical_hash((model.hash, element.id))[:12]}",
            kind=_EVIDENCE_KINDS[element.kind],
            source=element.source,
            target_id=element.id,
            status=element.status,
            artifact_hash=element.artifact_hash,
            details=element.details
            + (("name", element.name), ("actual_model_id", model.id)),
        )
        for element in model.elements
    )
    return tuple(sorted(evidence, key=lambda item: item.id))


def analyze_project_state(
    state: dict[str, object],
    source: str | Path,
    *,
    dependencies: ApplicationDependencies | None = None,
) -> tuple[dict[str, object], BridgeArtifacts]:
    """扫描本地项目并与已批准基线做确定性对比。"""
    if not state.get("baseline"):
        raise ContractViolation("请先批准基线")
    baseline = _baseline_from_state(state)
    resolved = Path(source).expanduser().resolve()
    deps = configured_dependencies(dependencies)
    model, summary = deps.project_scanner(resolved)
    evidence = evidence_from_actual(model)
    delta, matches = compare_baseline_with_actual(baseline, model)
    tasks = build_task_contracts(delta)

    elements_by_kind: dict[str, int] = {}
    for element in model.elements:
        elements_by_kind[element.kind] = elements_by_kind.get(element.kind, 0) + 1
    matched_baseline_ids = {match["baseline_id"] for match in matches}
    project = {
        "source": str(resolved),
        "approved_baseline_id": baseline.id,
        "baseline_hash": baseline.hash,
        "actual": {
            "id": model.id,
            "source_root": model.source_root,
            "elements": [asdict(item) for item in model.elements],
            "hash": model.hash,
        },
        "matches": list(matches),
        "delta": asdict(delta),
        "tasks": [asdict(item) for item in tasks],
        "evidence": [asdict(item) for item in evidence],
        "summary": {
            "files_seen": summary["files_seen"],
            "files_used": summary["files_used"],
            "files_skipped_size": summary["files_skipped_size"],
            "files_skipped_limit": summary["files_skipped_limit"],
            "parse_errors": list(summary["parse_errors"]),
            "elements_by_kind": dict(sorted(elements_by_kind.items())),
            "matched": len(matched_baseline_ids),
            "missing": sum(1 for item in delta.items if item.kind == "MISSING"),
            "extra": sum(1 for item in delta.items if item.kind == "EXTRA"),
            "tests_passed": sum(
                1
                for element in model.elements
                if element.kind == "test-case" and element.status == "passed"
            ),
            "tests_failed": sum(
                1
                for element in model.elements
                if element.kind == "test-case" and element.status == "failed"
            ),
        },
    }
    result = _clone(state)
    result["project"] = project
    return result, BridgeArtifacts(
        baseline=baseline, actual=model, evidence=evidence, delta=delta, tasks=tasks
    )


@dataclass(frozen=True, slots=True)
class VerifyResult:
    model: ActualModel
    evidence: tuple[Evidence, ...]
    delta: Delta
    matches: tuple[dict, ...]
    statuses: tuple[dict, ...]
    hash: str


def _build_execution(
    state: dict[str, object],
    baseline: Baseline,
    source: Path,
    model: ActualModel,
    evidence: tuple[Evidence, ...],
    files_used: int,
    extra_summary: dict[str, object] | None = None,
) -> tuple[dict[str, object], VerifyResult]:
    task_items = state["project"]["tasks"]
    delta, matches = compare_baseline_with_actual(baseline, model)
    open_targets = {item.target_id for item in delta.items}
    statuses = sorted(
        (
            {
                "task_id": task["id"],
                "target": task["target_ids"][0],
                "status": "RESOLVED" if task["target_ids"][0] not in open_targets else "UNRESOLVED",
            }
            for task in task_items
        ),
        key=lambda item: item["task_id"],
    )
    resolved_count = sum(1 for item in statuses if item["status"] == "RESOLVED")
    summary = {
        "files_used": files_used,
        "matched": len(matches),
        "missing": sum(1 for item in delta.items if item.kind == "MISSING"),
        "extra": sum(1 for item in delta.items if item.kind == "EXTRA"),
        "tests_passed": sum(
            1
            for element in model.elements
            if element.kind == "test-case" and element.status == "passed"
        ),
        "tests_failed": sum(
            1
            for element in model.elements
            if element.kind == "test-case" and element.status == "failed"
        ),
        "resolved": resolved_count,
        "unresolved": len(statuses) - resolved_count,
    }
    if extra_summary is not None:
        summary.update(extra_summary)
    execution = {
        "source": str(source),
        "actual_model_id": model.id,
        "actual_model_hash": model.hash,
        "contract_statuses": statuses,
        "summary": summary,
    }
    stable_execution = _clone(execution)
    stable_summary = stable_execution["summary"]
    stable_test_run = stable_summary.get("test_run")
    if isinstance(stable_test_run, dict):
        stable_test_run.pop("cache_hit", None)
        stable_test_run.pop("stderr_tail", None)
        stable_test_run.pop("stdout_tail", None)
        for item in stable_test_run.get("runners", ()):
            if isinstance(item, dict):
                item.pop("cache_hit", None)
                item.pop("stderr_tail", None)
                item.pop("stdout_tail", None)
    execution["hash"] = canonical_hash(stable_execution)
    result = _clone(state)
    result["project"]["execution"] = execution
    result["project"]["evidence"] = [asdict(item) for item in evidence]
    result["project"]["delta"] = asdict(delta)
    result["project"]["matches"] = list(matches)
    return result, VerifyResult(
        model=model,
        evidence=evidence,
        delta=delta,
        matches=matches,
        statuses=tuple(statuses),
        hash=execution["hash"],
    )


def verify_contracts_state(
    state: dict[str, object],
    source: str | Path,
    *,
    dependencies: ApplicationDependencies | None = None,
) -> tuple[dict[str, object], VerifyResult]:
    """重扫描本地项目，判定每条既有任务契约是否已满足。只读、确定性。"""
    if not state.get("baseline"):
        raise ContractViolation("请先批准基线")
    project = state.get("project")
    if not project or not project.get("tasks"):
        raise ContractViolation("请先在项目接入中分析项目并生成任务契约")
    baseline = _baseline_from_state(state)
    resolved_path = Path(source).expanduser().resolve()
    deps = configured_dependencies(dependencies)
    model, summary = deps.project_scanner(resolved_path)
    evidence = evidence_from_actual(model)
    return _build_execution(
        state, baseline, resolved_path, model, evidence, summary["files_used"]
    )


def execute_tests_state(
    state: dict[str, object],
    project_dir: str | Path,
    timeout: int = DEFAULT_TEST_TIMEOUT,
    *,
    runners: tuple[str, ...] = ("pytest",),
    limits: ResourceLimits | None = None,
    cache_dir: str | Path | None = None,
    jobs: int = 1,
    dependencies: ApplicationDependencies | None = None,
) -> tuple[dict[str, object], VerifyResult]:
    """运行内置测试 runner 集合，把客观 Evidence 回填后重算执行状态。"""
    if not state.get("baseline"):
        raise ContractViolation("请先批准基线")
    project = state.get("project")
    if not project or not project.get("tasks"):
        raise ContractViolation("请先在项目接入中分析项目并生成任务契约")
    baseline = _baseline_from_state(state)
    resolved_path = Path(project_dir).expanduser().resolve()
    deps = configured_dependencies(dependencies)
    effective_limits = limits or build_limits(timeout_seconds=timeout)
    runs = deps.test_executor(
        resolved_path,
        runners=runners,
        limits=effective_limits,
        cache_dir=Path(cache_dir) if cache_dir is not None else None,
        jobs=jobs,
    )
    try:
        model, summary = deps.project_scanner(resolved_path)
        implementation_evidence = evidence_from_actual(model)
        test_evidence = tuple(
            sorted(
                (item for run in runs for item in run.evidence),
                key=lambda item: item.id,
            )
        )
        evidence = tuple(
            sorted(implementation_evidence + test_evidence, key=lambda item: item.id)
        )
        extra_summary = {"test_run": _test_run_summary(runs, jobs)}
        return _build_execution(
            state,
            baseline,
            resolved_path,
            model,
            evidence,
            summary["files_used"],
            extra_summary,
        )
    finally:
        for run in runs:
            if run.temp_dir is not None:
                shutil.rmtree(run.temp_dir, ignore_errors=True)


def _test_run_summary(runs: tuple, jobs: int) -> dict[str, object]:
    """把一个或多个 RunnerResult 映射为兼容旧页面的确定性摘要。"""
    per_runner: list[dict[str, object]] = []
    failed_tests: set[str] = set()
    stderr_parts: list[str] = []
    for run in runs:
        diagnostics = run.diagnostics
        runner_failed = list(diagnostics.get("failed_tests", ()))
        failed_tests.update(str(item) for item in runner_failed)
        stderr_tail = str(diagnostics.get("stderr_tail", ""))
        stdout_tail = str(diagnostics.get("stdout_tail", ""))
        diagnostic_tail = (
            stderr_tail or stdout_tail if run.returncode != 0 or run.timed_out else ""
        )
        if run.returncode != 0 or run.timed_out:
            detail = diagnostic_tail
            if detail:
                stderr_parts.append(f"[{run.runner}] {detail}")
        per_runner.append(
            {
                "runner": run.runner,
                "returncode": run.returncode,
                "timed_out": run.timed_out,
                "tests_passed": int(diagnostics.get("tests_passed", 0)),
                "tests_failed": int(diagnostics.get("tests_failed", 0)),
                "junit_evidence": len(run.evidence),
                "failed_tests": runner_failed,
                "stderr_tail": diagnostic_tail,
                "cache_hit": run.cache_hit,
                "resource_limits": run.resource_limits,
            }
        )
    returncode: int | None
    nonzero = [run.returncode for run in runs if run.returncode not in (None, 0)]
    if nonzero:
        returncode = nonzero[0]
    elif any(run.returncode is None for run in runs):
        returncode = None
    else:
        returncode = 0
    return {
        "runner": runs[0].runner if len(runs) == 1 else "multiple",
        "runners": per_runner,
        "jobs": jobs,
        "cache_hit": bool(runs) and all(run.cache_hit for run in runs),
        "returncode": returncode,
        "timed_out": any(run.timed_out for run in runs),
        "tests_passed": sum(int(run.diagnostics.get("tests_passed", 0)) for run in runs),
        "tests_failed": sum(int(run.diagnostics.get("tests_failed", 0)) for run in runs),
        "junit_evidence": sum(len(run.evidence) for run in runs),
        "failed_tests": sorted(failed_tests),
        "stderr_tail": "\n".join(stderr_parts),
        "resource_limits": (
            runs[0].resource_limits
            if len(runs) == 1
            else {run.runner: run.resource_limits for run in runs}
        ),
    }
