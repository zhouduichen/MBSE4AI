"""Acceptance metrics for requirement extraction and provenance."""

from __future__ import annotations


# Keep the quality gates in application code so a caller cannot make a formal
# acceptance pass by omitting or weakening thresholds in a gold file.
FORMAL_THRESHOLDS = {
    "requirement_precision": 0.90,
    "requirement_recall": 0.90,
    "detail_micro_f1": 0.85,
    "provenance_complete": 100,
}


def formal_acceptance_status(metrics: dict[str, object] | None) -> str:
    """Return the formal status for an optional gold-set comparison.

    A missing metric is treated as a failed quality gate when it is supplied
    by a caller, rather than being truthy by accident.  ``detail_micro_f1``
    remains optional for backwards compatibility with the v1 gold contract;
    later contracts can provide it and it will then be enforced.
    """

    if metrics is None:
        return "not_evaluated"

    def _number(name: str, default: float = 0.0) -> float:
        try:
            return float(metrics.get(name, default))
        except (TypeError, ValueError):
            return default

    try:
        provenance_complete = int(metrics.get("provenance_complete", 0))
    except (TypeError, ValueError):
        provenance_complete = 0

    passed = (
        _number("precision") >= FORMAL_THRESHOLDS["requirement_precision"]
        and _number("recall") >= FORMAL_THRESHOLDS["requirement_recall"]
        and provenance_complete == FORMAL_THRESHOLDS["provenance_complete"]
    )
    if "detail_micro_f1" in metrics:
        passed = passed and _number("detail_micro_f1") >= FORMAL_THRESHOLDS["detail_micro_f1"]
    return "passed" if passed else "failed"


def _text_key(value: object) -> str:
    """Normalize source text enough to ignore formatting punctuation noise."""

    text = "" if value is None else str(value)
    return "".join(text.split()).rstrip("。.!！?？;；")


def _item_key(item: object) -> tuple[str, str, str]:
    value = item if isinstance(item, dict) else {}
    statement = str(value.get("statement", value.get("object", "")))
    if "source_text" in value:
        return ("source_text", statement, _text_key(value.get("source_text")))
    if "source_region_id" in value:
        return ("source_region_id", statement, str(value.get("source_region_id", "")))
    return ("source_span_id", statement, str(value.get("source_span_id", "")))


def evaluate_requirement_extraction(actual, expected) -> dict[str, object]:
    actual_items = tuple(actual)
    expected_items = tuple(expected)
    expected_keys = {_item_key(item) for item in expected_items}
    actual_keys = {_item_key(item) for item in actual_items}
    matched = actual_keys & expected_keys
    precision = len(matched) / len(actual_keys) if actual_keys else 0.0
    recall = len(matched) / len(expected_keys) if expected_keys else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    provenance_complete = (
        round(sum(bool(item.get("source_region_id", item.get("source_span_id", ""))) for item in actual_items) * 100 / len(actual_items))
        if actual_items else 0
    )
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "provenance_complete": provenance_complete,
        "matched": len(matched),
        "unmatched_actual": sorted(actual_keys - expected_keys),
        "unmatched_expected": sorted(expected_keys - actual_keys),
    }
