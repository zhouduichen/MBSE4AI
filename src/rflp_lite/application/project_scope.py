"""Workspace-boundary helpers for the requirements workbench."""

from __future__ import annotations

import json

from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _clone(state: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(state))


def bind_project_scope(state: dict[str, object], workspace_name: str) -> dict[str, object]:
    """Stamp a workbench with its owning workspace and current input hash."""

    clean_name = str(workspace_name).strip()
    if not clean_name:
        raise ContractViolation("项目作用域不能为空")
    result = _clone(state)
    regions = result.get("document_regions") or result.get("spans") or []
    source = tuple(
        (str(item.get("id", "")), str(item.get("text", "")))
        for item in regions
        if isinstance(item, dict)
    )
    result["project_scope"] = {
        "workspace": clean_name,
        "input_hash": canonical_hash(source),
    }
    return result


def validate_project_scope(state: dict[str, object], workspace_name: str) -> None:
    """Reject a workbench that was stamped for another workspace."""

    scope = state.get("project_scope")
    if not isinstance(scope, dict) or not str(scope.get("workspace", "")):
        return
    if str(scope["workspace"]) != str(workspace_name):
        raise ContractViolation("项目作用域不匹配，禁止跨项目读取或保存")


def _ids(values: object) -> set[str]:
    if not isinstance(values, (list, tuple)):
        return set()
    return {
        str(item.get("id"))
        for item in values
        if isinstance(item, dict) and str(item.get("id", ""))
    }


def validate_project_references(state: dict[str, object]) -> None:
    """Ensure every stored relation points at an object in this workbench."""

    known_ids: set[str] = set()
    for group in (
        "document_regions",
        "spans",
        "stakeholders",
        "concerns",
        "needs",
        "claims",
        "structured_requirements",
        "scenarios",
    ):
        known_ids.update(_ids(state.get(group)))

    rflp = state.get("rflp")
    if isinstance(rflp, dict):
        known_ids.update(_ids(rflp.get("elements")))

    mbse = state.get("mbse")
    if isinstance(mbse, dict):
        for group in ("actors", "use_cases", "activities", "lifelines", "messages"):
            known_ids.update(_ids(mbse.get(group)))
        semantic_model = mbse.get("semantic_model")
        if isinstance(semantic_model, dict):
            from rflp_lite.application.mbse_semantics import mbse_entity_index

            try:
                known_ids.update(mbse_entity_index(semantic_model))
            except ContractViolation:
                raise

    discovery = state.get("discovery")
    if isinstance(discovery, dict):
        graph = discovery.get("accepted_graph")
        if isinstance(graph, dict):
            known_ids.update(_ids(graph.get("elements")))
            for relation in graph.get("relations", ()):
                check_relation = relation
                if isinstance(check_relation, dict):
                    endpoints = {
                        str(check_relation.get("source_id", "")),
                        str(check_relation.get("target_id", "")),
                    }
                    endpoints.discard("")
                    if not endpoints <= known_ids:
                        raise ContractViolation(
                            "accepted graph 关系包含当前项目之外或不存在的对象"
                        )
        for candidate_set in discovery.get("candidate_sets", ()):
            if isinstance(candidate_set, dict):
                known_ids.update(_ids(candidate_set.get("items")))

    claim_ids = _ids(state.get("claims"))
    for scenario in state.get("scenarios", ()):
        if not isinstance(scenario, dict):
            continue
        unknown = {
            str(value)
            for value in scenario.get("requirement_ids", ())
            if str(value)
        } - claim_ids
        if unknown:
            raise ContractViolation(
                f"场景引用了当前项目不存在的需求: {', '.join(sorted(unknown))}"
            )

    def check_relation(relation: object, label: str) -> None:
        if not isinstance(relation, dict):
            return
        endpoints = {
            str(relation.get("source_id", "")),
            str(relation.get("target_id", "")),
        }
        endpoints.discard("")
        if not endpoints <= known_ids:
            raise ContractViolation(
                f"{label}包含当前项目之外或不存在的对象"
            )

    if isinstance(rflp, dict):
        for relation in rflp.get("relations", ()):
            check_relation(relation, "RFLP 关系")
    for link in state.get("trace_links", ()):
        check_relation(link, "追溯关系")
