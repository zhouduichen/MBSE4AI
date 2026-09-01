"""Build one canonical flow for Use Case, activity, and sequence projections."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash


def flow_step(*, order: int, sender: str, receiver: str, message: str, guard: str = "", branch: str = "main", requirement_ids=()) -> dict[str, object]:
    return {
        "id": f"flow-step-{canonical_hash((order, sender, receiver, message, guard, branch, tuple(requirement_ids)))[:12]}",
        "order": order,
        "sender": sender,
        "receiver": receiver,
        "message": message,
        "guard": guard,
        "branch": branch,
        "requirement_ids": sorted({str(value) for value in requirement_ids if str(value)}),
    }


def _steps(item: Mapping[str, object], requirement_ids: tuple[str, ...]):
    raw = item.get("interaction_steps") or item.get("steps") or item.get("main_flow") or ()
    if isinstance(raw, str):
        raw = tuple(value.strip() for value in raw.splitlines() if value.strip())
    flows = []
    for order, value in enumerate(raw if isinstance(raw, (list, tuple)) else (), 1):
        if isinstance(value, Mapping):
            flows.append(flow_step(order=order, sender=str(value.get("sender", "使用者")), receiver=str(value.get("receiver", "系统")), message=str(value.get("message", value.get("name", "步骤"))), guard=str(value.get("guard", "")), branch=str(value.get("branch", "main")), requirement_ids=tuple(value.get("requirement_ids", requirement_ids))))
        else:
            text = str(value).strip()
            if text:
                flows.append(flow_step(order=order, sender="使用者", receiver="系统", message=text, requirement_ids=requirement_ids))
    return flows


def build_use_case_drafts(state: Mapping[str, object]) -> tuple[dict[str, object], ...]:
    scenarios = [item for item in state.get("scenarios", ()) if isinstance(item, Mapping) and str(item.get("status", "accepted")) == "accepted"]
    if not scenarios:
        scenarios = [item for item in state.get("scenario_recommendations", ()) if isinstance(item, Mapping)]
    drafts = []
    for index, scenario in enumerate(scenarios, 1):
        requirement_ids = tuple(str(value) for value in scenario.get("requirement_ids", ()) if str(value))
        flows = _steps(scenario, requirement_ids)
        if not flows:
            continue
        scenario_id = str(scenario.get("id", "")) or f"scenario-{index}"
        flow_ids = tuple(str(step["id"]) for step in flows)
        drafts.append({
            "id": f"use-case-{canonical_hash((scenario_id, flow_ids))[:12]}",
            "name": str(scenario.get("title", scenario.get("name", "用例"))).strip() or "用例",
            "title": str(scenario.get("title", scenario.get("name", "用例"))).strip() or "用例",
            "scenario_id": scenario_id,
            "actors": [str(value) for value in scenario.get("actors", ()) if str(value)],
            "requirement_ids": list(requirement_ids),
            "preconditions": list(scenario.get("preconditions", ())),
            "postconditions": list(scenario.get("expected_outcomes", scenario.get("postconditions", ()))),
            "main_flow": flows,
            "status": "accepted",
            "producer": str(scenario.get("producer", "rule")),
        })
    return tuple(drafts)


__all__ = ["flow_step", "build_use_case_drafts"]
