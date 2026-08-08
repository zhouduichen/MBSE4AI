"""Acceptance metrics for requirement extraction and provenance."""

from __future__ import annotations


def evaluate_requirement_extraction(actual, expected) -> dict[str, object]:
    actual_items = tuple(actual)
    expected_items = tuple(expected)
    expected_keys = {
        (str(item.get("statement", item.get("object", ""))), str(item.get("source_region_id", item.get("source_span_id", ""))))
        for item in expected_items
    }
    actual_keys = {
        (str(item.get("statement", item.get("object", ""))), str(item.get("source_region_id", item.get("source_span_id", ""))))
        for item in actual_items
    }
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

