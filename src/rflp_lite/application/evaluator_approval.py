"""Customer-auditable approval evidence for multidisciplinary evaluators."""

from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


_REQUIRED_FIELDS = (
    "adapter_version",
    "implementation_hash",
    "source_kind",
    "validity_domain",
    "validation_dataset_id",
    "validation_dataset_version",
    "validation_dataset_hash",
    "error_metrics",
    "acceptance_limits",
    "approved_for_formal",
    "approved_by",
    "approved_at",
    "basis",
)


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    approved: bool
    diagnostics: tuple[str, ...] = ()
    profile_hash: str = ""


def validate_approval_profile(payload: object) -> dict[str, Any]:
    """Validate the strict approval evidence contract.

    An empty approval map is valid and deliberately denotes development-only
    evidence. Any non-empty entry must contain the complete customer audit
    record; incomplete entries cannot be silently promoted to formal status.
    """

    if not isinstance(payload, Mapping):
        raise ContractViolation("evaluator profile must be an object")
    approvals = payload.get("approvals", {})
    if not isinstance(approvals, Mapping):
        raise ContractViolation("evaluator profile approvals must be an object")
    normalized: dict[str, Any] = {
        "id": str(payload.get("id", "")),
        "version": payload.get("version"),
        "approvals": {},
    }
    if not normalized["id"] or not isinstance(normalized["version"], int) or isinstance(normalized["version"], bool) or normalized["version"] < 1:
        raise ContractViolation("evaluator profile id/version is invalid")
    for adapter_id, raw in approvals.items():
        if not isinstance(adapter_id, str) or not adapter_id.strip() or not isinstance(raw, Mapping):
            raise ContractViolation("evaluator approval entry is invalid")
        missing = [field for field in _REQUIRED_FIELDS if field not in raw]
        if missing:
            raise ContractViolation(f"approval for {adapter_id} missing: {', '.join(missing)}")
        for field in ("adapter_version", "implementation_hash", "source_kind", "validation_dataset_id", "validation_dataset_version", "validation_dataset_hash", "approved_by", "approved_at", "basis"):
            if not isinstance(raw.get(field), str) or not str(raw.get(field)).strip():
                raise ContractViolation(f"approval for {adapter_id} field {field} is required")
        if not isinstance(raw.get("approved_for_formal"), bool):
            raise ContractViolation(f"approval for {adapter_id} approved_for_formal must be boolean")
        validity = raw.get("validity_domain")
        if not isinstance(validity, Mapping):
            raise ContractViolation(f"approval for {adapter_id} validity_domain must be an object")
        for name, bound in validity.items():
            if not isinstance(bound, Mapping) or "minimum" not in bound or "maximum" not in bound:
                raise ContractViolation(f"approval for {adapter_id} validity bound {name} is invalid")
            for key in ("minimum", "maximum"):
                value = bound[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ContractViolation(f"approval for {adapter_id} validity bound {name}.{key} is invalid")
            if float(bound["minimum"]) > float(bound["maximum"]):
                raise ContractViolation(f"approval for {adapter_id} validity bound {name} is reversed")
        error_metrics = raw.get("error_metrics")
        limits = raw.get("acceptance_limits")
        if not isinstance(error_metrics, Mapping) or not isinstance(limits, Mapping):
            raise ContractViolation(f"approval for {adapter_id} error metrics/limits must be objects")
        for metric, value in error_metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ContractViolation(f"approval for {adapter_id} error metric {metric} is invalid")
            limit = limits.get(metric)
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(float(limit)):
                raise ContractViolation(f"approval for {adapter_id} acceptance limit {metric} is invalid")
            if float(value) > float(limit):
                raise ContractViolation(f"approval for {adapter_id} error metric {metric} exceeds its limit")
        normalized["approvals"][adapter_id] = dict(raw)
    return normalized


def adapter_implementation_hash(adapter: object) -> str:
    """Return a stable algorithm identity, never a process-dependent hash."""

    declared = str(getattr(adapter, "implementation_hash", "") or "").strip()
    if declared:
        return declared
    return canonical_hash({
        "module": str(getattr(adapter.__class__, "__module__", "")),
        "class": str(getattr(adapter.__class__, "__qualname__", "")),
        "id": str(getattr(adapter, "id", "")),
        "version": str(getattr(adapter, "version", "")),
    })


def _domain_diagnostics(entry: Mapping[str, object], parameters: Mapping[str, object]) -> list[str]:
    diagnostics: list[str] = []
    domain = entry.get("validity_domain")
    if not isinstance(domain, Mapping):
        return ["validity_domain missing"]
    for name, bound in domain.items():
        value = parameters.get(str(name))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            diagnostics.append(f"parameter outside validity domain: {name}")
            continue
        if not isinstance(bound, Mapping) or float(value) < float(bound["minimum"]) or float(value) > float(bound["maximum"]):
            diagnostics.append(f"parameter outside validity domain: {name}")
    return diagnostics


def formal_approval_for(
    adapter: object,
    discipline: Mapping[str, object],
    profile: Mapping[str, object],
    parameters: Mapping[str, object],
) -> ApprovalDecision:
    """Evaluate one adapter against the complete customer approval record."""

    profile_hash = canonical_hash(profile)
    try:
        validated = validate_approval_profile(profile)
    except ContractViolation as exc:
        return ApprovalDecision(False, (str(exc),), profile_hash)
    approvals = validated.get("approvals", {})
    entry = approvals.get(str(getattr(adapter, "id", ""))) if isinstance(approvals, Mapping) else None
    if not isinstance(entry, Mapping):
        return ApprovalDecision(False, ("no customer approval entry",), profile_hash)
    diagnostics: list[str] = []
    if str(entry.get("adapter_version")) != str(getattr(adapter, "version", "")):
        diagnostics.append("adapter version mismatch")
    if str(entry.get("implementation_hash")) != adapter_implementation_hash(adapter):
        diagnostics.append("adapter implementation hash mismatch")
    if str(entry.get("source_kind")) != str(getattr(adapter, "source_kind", "")):
        diagnostics.append("adapter source kind mismatch")
    discipline_id = str(discipline.get("id", ""))
    if discipline_id and str(getattr(adapter, "id", "")) not in discipline_id and str(discipline.get("adapter", "")) not in {"", str(getattr(adapter, "id", ""))}:
        diagnostics.append("adapter is not assigned to the requested discipline")
    diagnostics.extend(_domain_diagnostics(entry, parameters))
    if entry.get("approved_for_formal") is not True:
        diagnostics.append("approval is not marked for formal use")
    return ApprovalDecision(not diagnostics, tuple(diagnostics), profile_hash)


__all__ = ["ApprovalDecision", "adapter_implementation_hash", "formal_approval_for", "validate_approval_profile"]
