from __future__ import annotations

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.models import Baseline, Delta, DeltaItem, Evidence


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

