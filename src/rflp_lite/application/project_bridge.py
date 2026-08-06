from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from rflp_lite.adapters.evidence_readers import read_junit
from rflp_lite.adapters.project_scanner import scan_project
from rflp_lite.adapters.test_executor import DEFAULT_TEST_TIMEOUT, run_project_tests
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
_TIMING_LINE = re.compile(r" in \d+\.\d+s$")


def _output_tail(path: Path, max_lines: int = 15, max_chars: int = 2000) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    kept = [line for line in lines[-max_lines:] if not _TIMING_LINE.search(line.strip())]
    return "\n".join(kept).strip()[:max_chars]


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
    state: dict[str, object], source: str | Path
) -> tuple[dict[str, object], BridgeArtifacts]:
    """扫描本地项目并与已批准基线做确定性对比。"""
    if not state.get("baseline"):
        raise ContractViolation("请先批准基线")
    baseline = _baseline_from_state(state)
    resolved = Path(source).expanduser().resolve()
    model, summary = scan_project(resolved)
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
    execution["hash"] = canonical_hash(execution)
    result = _clone(state)
    result["project"]["execution"] = execution
    result["project"]["evidence"] = [asdict(item) for item in evidence]
    return result, VerifyResult(
        model=model,
        evidence=evidence,
        delta=delta,
        matches=matches,
        statuses=tuple(statuses),
        hash=execution["hash"],
    )


def verify_contracts_state(
    state: dict[str, object], source: str | Path
) -> tuple[dict[str, object], VerifyResult]:
    """重扫描本地项目，判定每条既有任务契约是否已满足。只读、确定性。"""
    if not state.get("baseline"):
        raise ContractViolation("请先批准基线")
    project = state.get("project")
    if not project or not project.get("tasks"):
        raise ContractViolation("请先在项目接入中分析项目并生成任务契约")
    baseline = _baseline_from_state(state)
    resolved_path = Path(source).expanduser().resolve()
    model, summary = scan_project(resolved_path)
    evidence = evidence_from_actual(model)
    return _build_execution(
        state, baseline, resolved_path, model, evidence, summary["files_used"]
    )


def execute_tests_state(
    state: dict[str, object],
    project_dir: str | Path,
    timeout: int = DEFAULT_TEST_TIMEOUT,
) -> tuple[dict[str, object], VerifyResult]:
    """运行项目 pytest 沙箱，把归一化 JUnit 回填为 Evidence，再重算执行状态。"""
    if not state.get("baseline"):
        raise ContractViolation("请先批准基线")
    project = state.get("project")
    if not project or not project.get("tasks"):
        raise ContractViolation("请先在项目接入中分析项目并生成任务契约")
    baseline = _baseline_from_state(state)
    resolved_path = Path(project_dir).expanduser().resolve()
    run = run_project_tests(resolved_path, timeout)
    try:
        model, summary = scan_project(resolved_path)
        implementation_evidence = evidence_from_actual(model)
        test_evidence = read_junit(run.junit_path) if run.junit_path is not None else ()
        evidence = tuple(
            sorted(
                implementation_evidence + test_evidence, key=lambda item: item.id
            )
        )
        tests_passed = sum(1 for item in test_evidence if item.status == "passed")
        tests_failed = sum(1 for item in test_evidence if item.status == "failed")
        failed_tests = sorted(
            item.source.rsplit("/", 1)[-1]
            for item in test_evidence
            if item.status == "failed"
        )
        stderr_tail = ""
        if run.returncode != 0 or run.timed_out:
            stderr_tail = _output_tail(run.stderr_path) or _output_tail(run.stdout_path)
        extra_summary = {
            "test_run": {
                "returncode": run.returncode,
                "timed_out": run.timed_out,
                "tests_passed": tests_passed,
                "tests_failed": tests_failed,
                "junit_evidence": len(test_evidence),
                "failed_tests": failed_tests,
                "stderr_tail": stderr_tail,
            }
        }
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
        shutil.rmtree(run.temp_dir, ignore_errors=True)
