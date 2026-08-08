from __future__ import annotations

from typing import Any

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


def _event(
    scenario_id: str,
    sequence: int,
    kind: str,
    text: str,
    status: str,
) -> dict[str, object]:
    return {
        "id": f"scenario-event-{canonical_hash((scenario_id, sequence, kind, text))[:12]}",
        "sequence": sequence,
        "kind": kind,
        "text": text,
        "status": status,
    }


def execute_scenario(
    state: dict[str, object], scenario_id: str, *, run_id: str | None = None
) -> dict[str, object]:
    """Create a safe, deterministic trace for a structured scenario.

    This is deliberately declarative: it never evaluates scenario text or calls
    an external system. A future runtime adapter can consume the same scenario
    contract and replace this trace producer.
    """
    scenario = next(
        (item for item in state.get("scenarios", ()) if item.get("id") == scenario_id),
        None,
    )
    if scenario is None:
        raise ContractViolation("场景不存在")

    generated_run_id = run_id or f"scenario-run-{canonical_hash((scenario_id, scenario.get('hash')))[:12]}"
    events: list[dict[str, object]] = []
    sequence = 1
    for text in scenario.get("preconditions", ()):
        events.append(_event(scenario_id, sequence, "precondition", str(text), "ready"))
        sequence += 1
    for text in scenario.get("steps", ()):
        events.append(_event(scenario_id, sequence, "step", str(text), "executed"))
        sequence += 1
    for text in scenario.get("faults", ()):
        events.append(_event(scenario_id, sequence, "fault", str(text), "injected"))
        sequence += 1

    assertions: list[dict[str, object]] = []
    for index, text in enumerate(scenario.get("expected_outcomes", ()), start=1):
        outcome = str(text)
        assertions.append(
            {
                "id": f"scenario-assertion-{canonical_hash((scenario_id, index, outcome))[:12]}",
                "expected": outcome,
                "status": "not_verified",
                "reason": "仅生成声明性轨迹，尚未连接运行时系统",
            }
        )
        events.append(_event(scenario_id, sequence, "expected_outcome", outcome, "declared"))
        sequence += 1

    status = "completed_with_faults" if scenario.get("faults") else "completed"
    trace = {
        "schema_version": 1,
        "run_id": generated_run_id,
        "scenario_id": scenario_id,
        "status": status,
        "verification": "declarative-only",
        "events": events,
        "assertions": assertions,
    }
    trace_hash = canonical_hash(trace)
    evidence = {
        "id": f"scenario-evidence-{trace_hash[:12]}",
        "kind": "scenario-run",
        "status": status,
        "source_id": scenario_id,
        "trace_hash": trace_hash,
        "verification": "declarative-only",
    }
    return {
        **trace,
        "trace_hash": trace_hash,
        "evidence": [evidence],
    }


def append_scenario_run(
    state: dict[str, object], result: dict[str, object]
) -> dict[str, object]:
    """Return a JSON-safe workbench state with the latest run retained."""
    import json

    value = json.loads(json.dumps(state, ensure_ascii=False))
    runs = [item for item in value.get("scenario_runs", ()) if item.get("run_id") != result["run_id"]]
    runs.append(result)
    value["scenario_runs"] = sorted(runs, key=lambda item: str(item["run_id"]))
    return value


def scenario_run_map(state: dict[str, object]) -> dict[str, dict[str, Any]]:
    return {str(item["run_id"]): item for item in state.get("scenario_runs", ())}
