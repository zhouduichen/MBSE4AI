from __future__ import annotations

import re

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import ActualModel, Baseline, Delta, DeltaItem, Evidence


_ASCII_TOKEN = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[一-鿿]+")
_MATCHABLE_ACTUAL_KINDS = {"class", "function", "api-operation"}


def calculate_delta(baseline: Baseline, evidence: tuple[Evidence, ...]) -> Delta:
    baseline_ids = {element.id for element in baseline.elements}
    actual_ids = {item.target_id for item in evidence}
    items: list[DeltaItem] = []
    for target_id in sorted(actual_ids - baseline_ids):
        items.append(
            DeltaItem(
                id=f"delta-extra-{canonical_hash(target_id)[:10]}",
                kind="EXTRA",
                target_id=target_id,
                description="actual evidence has no matching baseline element",
            )
        )
    implemented_names = " ".join(actual_ids).lower()
    for element in sorted(baseline.elements, key=lambda item: item.id):
        if element.layer not in {"R", "F"}:
            continue
        key_terms = [term.lower() for term in element.name.split() if len(term) > 5]
        if key_terms and not any(term in implemented_names for term in key_terms):
            items.append(
                DeltaItem(
                    id=f"delta-missing-{element.id}",
                    kind="MISSING",
                    target_id=element.id,
                    description="baseline obligation has no direct implementation evidence",
                )
            )
    ordered = tuple(sorted(items, key=lambda item: item.id))
    digest = canonical_hash((baseline.hash, ordered))
    return Delta(id=f"delta-{digest[:12]}", baseline_hash=baseline.hash, items=ordered)


def _tokens(name: str) -> frozenset[str]:
    lowered = name.casefold()
    ascii_tokens = {token for token in _ASCII_TOKEN.findall(lowered) if len(token) >= 3}
    cjk_tokens = {run for run in _CJK_RUN.findall(lowered) if len(run) >= 2}
    return frozenset(ascii_tokens | cjk_tokens)


def compare_baseline_with_actual(
    baseline: Baseline, model: ActualModel
) -> tuple[Delta, tuple[dict, ...]]:
    actual_candidates = tuple(
        element for element in model.elements if element.kind in _MATCHABLE_ACTUAL_KINDS
    )
    actual_tokens = tuple(
        (element, _tokens(element.name)) for element in actual_candidates
    )
    matches: list[dict] = []
    matched_baseline_ids: set[str] = set()
    matched_actual_ids: set[str] = set()
    for element in sorted(baseline.elements, key=lambda item: item.id):
        if element.layer not in {"R", "F"}:
            continue
        baseline_tokens = _tokens(element.name)
        if not baseline_tokens:
            continue
        for actual, tokens in actual_tokens:
            shared = baseline_tokens & tokens
            if not shared:
                continue
            matches.append(
                {
                    "baseline_id": element.id,
                    "baseline_name": element.name,
                    "layer": element.layer,
                    "actual_id": actual.id,
                    "actual_name": actual.name,
                    "actual_kind": actual.kind,
                    "shared": sorted(shared),
                }
            )
            matched_baseline_ids.add(element.id)
            matched_actual_ids.add(actual.id)
    matches.sort(key=lambda item: (item["baseline_id"], item["actual_id"]))
    items: list[DeltaItem] = []
    for element in sorted(baseline.elements, key=lambda item: item.id):
        if element.layer in {"R", "F"} and element.id not in matched_baseline_ids:
            items.append(
                DeltaItem(
                    id=f"delta-missing-{element.id}",
                    kind="MISSING",
                    target_id=element.id,
                    description=f"基线义务未找到实现证据：{element.name}",
                )
            )
    for element in sorted(actual_candidates, key=lambda item: item.id):
        if element.id not in matched_actual_ids:
            items.append(
                DeltaItem(
                    id=f"delta-extra-{element.id}",
                    kind="EXTRA",
                    target_id=element.id,
                    description=f"实际实现未对应基线义务：{element.name}",
                )
            )
    ordered = tuple(sorted(items, key=lambda item: item.id))
    digest = canonical_hash((baseline.hash, model.hash, ordered))
    delta = Delta(id=f"delta-{digest[:12]}", baseline_hash=baseline.hash, items=ordered)
    return delta, tuple(matches)

