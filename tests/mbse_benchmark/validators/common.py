"""Shared normalization, graph, and finding helpers for benchmark validators."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping


def entities(graph: Mapping[str, object]) -> list[dict[str, Any]]:
    return [item for item in graph.get("entities", ()) if isinstance(item, dict)]


def relations(graph: Mapping[str, object]) -> list[dict[str, Any]]:
    return [item for item in graph.get("relations", ()) if isinstance(item, dict)]


def by_id(graph: Mapping[str, object]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id", "")): item for item in entities(graph) if item.get("id")}


def by_kind(graph: Mapping[str, object], kind: str) -> list[dict[str, Any]]:
    return [item for item in entities(graph) if str(item.get("kind", "")) == kind]


def payload(entity: Mapping[str, object]) -> dict[str, Any]:
    value = entity.get("payload", {})
    return dict(value) if isinstance(value, Mapping) else {}


def text_of(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return " ".join(text_of(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(text_of(item) for item in value)
    return "" if value is None else str(value)


def normalize(value: object) -> str:
    text = text_of(value).casefold()
    text = re.sub(r"[\s\u3000]+", "", text)
    return re.sub(r"[，。；、：:,.!?！？()（）/\\_-]+", "", text)


def entity_text(entity: Mapping[str, object]) -> str:
    return text_of({"name": entity.get("name", ""), "payload": payload(entity)})


def semantic_match(expected: object, actual: object, aliases: Iterable[Iterable[str]] = ()) -> bool:
    expected_text = normalize(expected)
    actual_text = normalize(actual)
    if not expected_text or not actual_text:
        return False
    if expected_text in actual_text or actual_text in expected_text:
        return True
    for group in aliases:
        values = {normalize(item) for item in group}
        if expected_text in values and any(value in actual_text or actual_text in value for value in values):
            return True
        if actual_text in values and expected_text in values:
            return True
    return False


def edge_map(graph: Mapping[str, object]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for relation in relations(graph):
        source = str(relation.get("source_id", ""))
        target = str(relation.get("target_id", ""))
        if source and target:
            outgoing[source].add(target)
            incoming[target].add(source)
    return dict(outgoing), dict(incoming)


def relation_map(graph: Mapping[str, object]) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = defaultdict(set)
    for relation in relations(graph):
        result[(str(relation.get("source_id", "")), str(relation.get("target_id", "")))].add(
            str(relation.get("predicate", ""))
        )
    return dict(result)


def reachable(graph: Mapping[str, object], start_id: str, target_kind: str, allowed_predicates: set[str] | None = None) -> set[str]:
    index = by_id(graph)
    outgoing, _ = edge_map(graph)
    seen: set[str] = set()
    queue = [start_id]
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        for target in outgoing.get(current, ()):
            if allowed_predicates is not None and not any(
                str(edge.get("predicate", "")) in allowed_predicates
                for edge in relations(graph)
                if edge.get("source_id") == current and edge.get("target_id") == target
            ):
                continue
            if str(index.get(target, {}).get("kind", "")) == target_kind:
                yield_id = target
                # A set is used to make the function deterministic while the
                # caller still receives all matching endpoints.
                seen.add(yield_id)
            if target not in seen:
                queue.append(target)
    return {item for item in seen if str(index.get(item, {}).get("kind", "")) == target_kind}


def numeric_values(value: object) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        return [float(item) for item in re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", value)]
    if isinstance(value, Mapping):
        result: list[float] = []
        for item in value.values():
            result.extend(numeric_values(item))
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            result.extend(numeric_values(item))
        return result
    return []


def finding(
    test_id: str,
    case_id: str,
    status: str,
    *,
    severity: str = "P2",
    category: str = "benchmark",
    expected: object = "",
    actual: object = "",
    related_elements: Iterable[str] = (),
    root_cause: str = "",
    recommended_fix: str = "",
) -> dict[str, object]:
    return {
        "test_id": test_id,
        "case_id": case_id,
        "status": status,
        "severity": severity,
        "category": category,
        "expected": expected,
        "actual": actual,
        "related_elements": list(dict.fromkeys(str(item) for item in related_elements if str(item))),
        "root_cause": root_cause,
        "recommended_fix": recommended_fix,
    }


def ratio(matched: int, total: int) -> float:
    return round(matched / total, 6) if total else 1.0


def json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def has_failure_signal(raw_result: Mapping[str, object], terms: Iterable[str]) -> bool:
    haystack = normalize({
        "issues": raw_result.get("issues", []),
        "run_summary": raw_result.get("run_summary", {}),
        "graph": raw_result.get("graph", {}),
        "audit": raw_result.get("audit", {}),
    })
    return any(normalize(term) in haystack for term in terms)


def validate_structural_graph(graph: Mapping[str, object]) -> list[dict[str, object]]:
    """Check graph references independently of semantic quality."""

    graph_id = str(graph.get("project_id", ""))
    index = by_id(graph)
    seen_ids: set[str] = set()
    findings: list[dict[str, object]] = []
    for entity in entities(graph):
        entity_id = str(entity.get("id", ""))
        if not entity_id:
            findings.append(finding("STRUCTURE", graph_id, "FAIL", severity="P0", category="schema", expected="non-empty entity ID", actual=entity, root_cause="entity ID is empty", recommended_fix="Generate stable typed entity IDs."))
        elif entity_id in seen_ids:
            findings.append(finding("STRUCTURE", graph_id, "FAIL", severity="P0", category="schema", expected="unique entity IDs", actual=entity_id, related_elements=[entity_id], root_cause="duplicate entity ID", recommended_fix="Use canonical identity for entity creation."))
        seen_ids.add(entity_id)
        if not str(entity.get("kind", "")) or not str(entity.get("name", "")).strip():
            findings.append(finding("STRUCTURE", graph_id, "FAIL", severity="P0", category="schema", expected="entity kind and name", actual=entity, related_elements=[entity_id], root_cause="entity metadata is incomplete", recommended_fix="Reject incomplete model entities before persistence."))
    relation_ids: set[str] = set()
    for relation in relations(graph):
        relation_id = str(relation.get("id", ""))
        source = str(relation.get("source_id", ""))
        target = str(relation.get("target_id", ""))
        if relation_id in relation_ids:
            findings.append(finding("STRUCTURE", graph_id, "FAIL", severity="P0", category="schema", expected="unique relation IDs", actual=relation_id, related_elements=[relation_id], root_cause="duplicate relation ID", recommended_fix="Generate canonical relation IDs."))
        relation_ids.add(relation_id)
        missing = [item for item in (source, target) if item not in index]
        if missing:
            findings.append(finding("STRUCTURE", graph_id, "FAIL", severity="P0", category="broken_reference", expected="relation endpoints exist", actual=missing, related_elements=[source, target], root_cause="relation points to an absent entity", recommended_fix="Validate relation endpoints before applying a patch."))
        if not str(relation.get("predicate", "")):
            findings.append(finding("STRUCTURE", graph_id, "FAIL", severity="P0", category="schema", expected="relation predicate", actual=relation, related_elements=[relation_id], root_cause="relation predicate is empty", recommended_fix="Use a closed relation vocabulary."))
    return findings
