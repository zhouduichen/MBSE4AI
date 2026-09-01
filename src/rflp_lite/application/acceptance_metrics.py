"""Acceptance metrics for requirement extraction and provenance."""

from __future__ import annotations

from collections.abc import Mapping

from rflp_lite.application.acceptance_gold import (
    GoldContract,
    match_requirement_items,
    normalize_acceptance_text,
)


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

    return normalize_acceptance_text(value)


def _item_key(item: object) -> tuple[str, str, str]:
    value = item if isinstance(item, dict) else {}
    statement = str(value.get("statement", value.get("object", "")))
    if "source_text" in value:
        return ("source_text", statement, _text_key(value.get("source_text")))
    if "source_region_id" in value:
        return ("source_region_id", statement, str(value.get("source_region_id", "")))
    return ("source_span_id", statement, str(value.get("source_span_id", "")))


def _detail_records(item: object) -> tuple[object, ...]:
    if not isinstance(item, Mapping):
        return ()
    direct = item.get("details")
    if isinstance(direct, (list, tuple)):
        return tuple(direct)
    records: list[object] = []
    for name in ("attributes", "constraints"):
        value = item.get(name)
        if isinstance(value, (list, tuple)):
            records.extend(value)
    return tuple(records)


def _detail_key(value: object) -> str:
    if isinstance(value, Mapping):
        return repr(sorted((str(key), normalize_acceptance_text(raw)) for key, raw in value.items() if key not in {"id", "status", "confidence"}))
    return normalize_acceptance_text(value)


def _detail_metrics(actual, expected, contract: GoldContract) -> dict[str, object]:
    expected_by_key = {item.key: item for item in contract.requirements}
    actual_by_key: dict[str, Mapping[str, object]] = {}
    for item in actual:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("gold_key", ""))
        if key:
            actual_by_key[key] = item
    expected_details = {
        (key, _detail_key(detail))
        for key, item in expected_by_key.items()
        for detail in item.details
    }
    actual_details = {
        (key, _detail_key(detail))
        for key, item in actual_by_key.items()
        for detail in _detail_records(item)
    }
    true_positive = len(expected_details & actual_details)
    precision = true_positive / len(actual_details) if actual_details else (1.0 if not expected_details else 0.0)
    recall = true_positive / len(expected_details) if expected_details else (1.0 if not actual_details else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "predicted": len(actual_details),
        "expected": len(expected_details),
        "micro_precision": round(precision, 4),
        "micro_recall": round(recall, 4),
        "micro_f1": round(f1, 4),
        "unmatched_actual": sorted(actual_details - expected_details),
        "unmatched_expected": sorted(expected_details - actual_details),
    }


def evaluate_requirement_extraction(
    actual,
    expected,
    *,
    source_text_by_region=None,
    contract: GoldContract | None = None,
) -> dict[str, object]:
    """Evaluate requirements, preserving the v1/v2 call shape.

    A v3 contract uses source anchors and stable gold keys.  Without one the
    legacy statement/source-id comparison remains unchanged for existing
    callers and fixtures.
    """

    if contract is not None:
        report = match_requirement_items(actual, contract.requirements, source_text_by_region)
        actual_items = tuple(actual)
        expected_items = tuple(contract.requirements)
        matched_count = len(report.matched)
        precision = matched_count / len(actual_items) if actual_items else 0.0
        recall = matched_count / len(expected_items) if expected_items else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        gold_key_by_actual_id: dict[str, str] = {}
        for diagnostic in report.pair_diagnostics:
            actual_id = str(diagnostic.get("actual_id", ""))
            key = str(diagnostic.get("matched_key", ""))
            if actual_id and key:
                gold_key_by_actual_id[actual_id] = key
        keyed_actual = []
        for index, item in enumerate(actual_items):
            value = dict(item) if isinstance(item, Mapping) else {}
            value["gold_key"] = gold_key_by_actual_id.get(
                str(value.get("id") or value.get("source_region_id") or value.get("source_span_id") or f"actual-{index + 1}"),
                "",
            )
            keyed_actual.append(value)
        detail = _detail_metrics(keyed_actual, expected_items, contract)
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "provenance_complete": report.provenance_complete,
            "matched": matched_count,
            "unmatched_actual": list(report.unmatched_actual),
            "unmatched_expected": list(report.unmatched_expected),
            "gold_contract_status": "valid",
            "requirement_matches": list(report.pair_diagnostics),
            "detail_metrics": detail,
            "detail_micro_f1": detail["micro_f1"],
            "provenance_diagnostics": list(report.pair_diagnostics),
        }

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
