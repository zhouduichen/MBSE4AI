from rflp_lite.methodology.contracts import Phase
from rflp_lite.methodology.stages import assurance, functional, logical_physical, operational
from rflp_lite.methodology.tasks import tasks_for_phase


def test_four_phase_catalog_has_expected_order_and_no_architecture_block():
    assert [task.id for task in operational.tasks()] == [
        "system_definition", "stakeholder_analysis", "stakeholder_requirements",
        "lifecycle_analysis", "scenario_exploration", "use_case_analysis",
        "operational_scenario", "activity_analysis", "system_requirement_derivation",
    ]
    assert [task.id for task in functional.tasks()] == [
        "function_identification", "functional_decomposition", "functional_interaction",
        "functional_scenario", "functional_requirement",
    ]
    assert [task.id for task in logical_physical.tasks()] == [
        "logical_analysis", "physical_candidates", "allocation_tradeoff", "technical_requirement",
    ]
    assert [task.id for task in assurance.tasks()] == [
        "interface_sequence_state", "fmea_stpa_hazard", "verification_validation",
        "reverse_feasibility", "global_cross_analysis",
    ]
    assert all(task.id != "architecture" for task in tasks_for_phase(Phase.OPERATIONAL))
