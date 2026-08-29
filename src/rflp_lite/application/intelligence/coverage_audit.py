"""Deterministic completeness checks for requirements analysis."""

from __future__ import annotations

from collections.abc import Mapping


CORE_SCENARIO_TYPES = frozenset({"normal", "boundary", "failure", "recovery", "misuse"})
CORE_SCENARIO_DIMENSIONS = frozenset(
    {
        "external_system_failure",
        "human_interaction_error",
        "performance_capacity_boundary",
        "safety",
        "cybersecurity",
        "regulatory",
    }
)
CORE_STAKEHOLDER_CATEGORIES = frozenset(
    {
        "customer",
        "end_user",
        "operator",
        "engineering",
        "supplier",
        "regulator",
        "external_system",
        "environment",
    }
)


def _items(state: Mapping[str, object], key: str) -> list[dict[str, object]]:
    return [item for item in state.get(key, ()) if isinstance(item, Mapping)]


def _valid_not_applicable(
    decisions: list[dict[str, object]],
    *,
    decision_type: str,
    valid_requirement_ids: set[str],
) -> set[str]:
    return {
        str(item.get("key", ""))
        for item in decisions
        if item.get("decision_type") == decision_type
        and item.get("status") == "not_applicable"
        and str(item.get("rationale", "")).strip()
        and bool(item.get("source_requirement_ids"))
        and set(str(value) for value in item.get("source_requirement_ids", ()))
        <= valid_requirement_ids
    }


def _not_applicable_requirement_ids(
    decisions: list[dict[str, object]],
    *,
    decision_type: str,
    key: str,
    valid_requirement_ids: set[str],
) -> set[str]:
    return {
        str(requirement_id)
        for item in decisions
        if item.get("decision_type") == decision_type
        and item.get("key") == key
        and item.get("status") == "not_applicable"
        and str(item.get("rationale", "")).strip()
        for requirement_id in item.get("source_requirement_ids", ())
        if str(requirement_id) in valid_requirement_ids
    }


def _missing_stakeholder_categories(
    stakeholders: list[dict[str, object]],
    pack: Mapping[str, object],
    decisions: list[dict[str, object]],
    requirement_ids: set[str],
) -> list[str]:
    configured = {
        str(value)
        for value in pack.get("stakeholder_categories", ())
        if str(value).strip()
    }
    expected = CORE_STAKEHOLDER_CATEGORIES | configured
    present = {str(item.get("category", "other")) for item in stakeholders}
    not_applicable = _valid_not_applicable(
        decisions,
        decision_type="stakeholder_category",
        valid_requirement_ids=requirement_ids,
    )
    return sorted(expected - present - not_applicable)


def evaluate_project_coverage(
    state: dict[str, object], pack: dict[str, object]
) -> dict[str, object]:
    """Return stable, machine-readable gaps while respecting valid waivers."""

    stakeholders = _items(state, "stakeholders")
    scenarios = [
        item
        for item in _items(state, "scenarios")
        if item.get("status") != "rejected"
    ]
    requirements = [
        item for item in _items(state, "claims") if item.get("status") != "rejected"
    ]
    requirement_ids = {str(item.get("id", "")) for item in requirements if item.get("id")}
    decisions = _items(state, "coverage_decisions")

    covered_types = {str(item.get("scenario_type", "normal")) for item in scenarios}
    covered_dimensions = {
        str(value)
        for item in scenarios
        for value in item.get("coverage_dimensions", item.get("dimensions", ()))
    }
    expected_lifecycle = {
        str(value) for value in pack.get("lifecycle_phases", ()) if str(value).strip()
    }
    covered_lifecycle = {
        str(item.get("lifecycle_phase", ""))
        for item in scenarios
        if str(item.get("lifecycle_phase", ""))
    }
    na_types = _valid_not_applicable(
        decisions, decision_type="scenario_type", valid_requirement_ids=requirement_ids
    )
    na_dimensions = _valid_not_applicable(
        decisions,
        decision_type="scenario_dimension",
        valid_requirement_ids=requirement_ids,
    )
    na_lifecycle = _valid_not_applicable(
        decisions,
        decision_type="lifecycle_phase",
        valid_requirement_ids=requirement_ids,
    )

    stakeholder_ids = {str(item.get("id", "")) for item in stakeholders if item.get("id")}
    concern_ids = {
        str(item.get("stakeholder_id", "")) for item in _items(state, "concerns")
    }
    need_ids = {str(item.get("stakeholder_id", "")) for item in _items(state, "needs")}
    linked_scenario_requirement_ids = {
        str(requirement_id)
        for scenario in scenarios
        for requirement_id in scenario.get("requirement_ids", ())
    }
    need_to_stakeholder = {
        str(item.get("id", "")): str(item.get("stakeholder_id", ""))
        for item in _items(state, "needs")
    }
    linked_stakeholder_requirement_ids = {
        str(item.get("id", ""))
        for item in requirements
        if str(item.get("stakeholder_id", "")) in stakeholder_ids
        or need_to_stakeholder.get(str(item.get("need_id", ""))) in stakeholder_ids
    }

    discovery = state.get("discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    architecture = discovery.get("architecture")
    architecture = architecture if isinstance(architecture, Mapping) else {}

    def architecture_ids(key: str) -> set[str]:
        return {
            str(requirement_id)
            for item in architecture.get(key, ())
            if isinstance(item, Mapping)
            for requirement_id in item.get(
                "requirement_ids", item.get("source_requirement_ids", ())
            )
        }

    function_ids = architecture_ids("functions")
    logical_ids = architecture_ids("logical_components")
    physical_ids = architecture_ids("physical_components")
    interface_ids = architecture_ids("interfaces")
    verification_ids = {
        str(endpoint)
        for item in _items(state, "trace_links")
        if str(item.get("predicate", "")).casefold()
        in {"verifies", "verifiedby", "validates", "validatedby", "tests"}
        for endpoint in (item.get("source_id"), item.get("target_id"))
        if str(endpoint) in requirement_ids
    }
    architecture_na = {
        key: _not_applicable_requirement_ids(
            decisions,
            decision_type="architecture_dimension",
            key=key,
            valid_requirement_ids=requirement_ids,
        )
        for key in ("function", "logical_component", "physical_component", "interface", "verification")
    }
    all_source_ids = {
        str(item.get("id", ""))
        for item in state.get("document_regions", state.get("spans", ()))
        if isinstance(item, Mapping) and item.get("id")
    }
    analyzed_source_ids = {str(value) for value in state.get("analysis_source_registry", ())}
    missing_dimensions: set[str] = set()
    if any(not item.get("goals") for item in stakeholders):
        missing_dimensions.add("stakeholder_goals")
    if any(not item.get("interactions") for item in stakeholders):
        missing_dimensions.add("stakeholder_interactions")

    return {
        "missing_dimensions": sorted(missing_dimensions),
        "missing_stakeholder_categories": _missing_stakeholder_categories(
            stakeholders, pack, decisions, requirement_ids
        ),
        "missing_scenario_types": sorted(CORE_SCENARIO_TYPES - covered_types - na_types),
        "missing_scenario_dimensions": sorted(
            CORE_SCENARIO_DIMENSIONS - covered_dimensions - na_dimensions
        ),
        "missing_lifecycle_phases": sorted(expected_lifecycle - covered_lifecycle - na_lifecycle),
        "stakeholder_ids_without_concerns": sorted(stakeholder_ids - concern_ids),
        "stakeholder_ids_without_needs": sorted(stakeholder_ids - need_ids),
        "requirements_without_stakeholder_ids": sorted(
            requirement_ids - linked_stakeholder_requirement_ids
        ),
        "requirements_without_scenario_ids": sorted(
            requirement_ids - linked_scenario_requirement_ids
        ),
        "requirements_without_function_ids": sorted(
            requirement_ids - function_ids - architecture_na["function"]
        ),
        "requirements_without_logical_component_ids": sorted(
            requirement_ids - logical_ids - architecture_na["logical_component"]
        ),
        "requirements_without_physical_component_ids": sorted(
            requirement_ids - physical_ids - architecture_na["physical_component"]
        ),
        "requirements_without_interface_ids": sorted(
            requirement_ids - interface_ids - architecture_na["interface"]
        ),
        "requirements_without_verification_ids": sorted(
            requirement_ids - verification_ids - architecture_na["verification"]
        ),
        "unlinked_scenario_ids": sorted(
            str(item.get("id", "")) for item in scenarios if not item.get("requirement_ids")
        ),
        "analyzed_source_ids": sorted(analyzed_source_ids),
        "unprocessed_source_ids": sorted(all_source_ids - analyzed_source_ids),
    }


__all__ = [
    "CORE_SCENARIO_TYPES",
    "CORE_SCENARIO_DIMENSIONS",
    "CORE_STAKEHOLDER_CATEGORIES",
    "evaluate_project_coverage",
]
