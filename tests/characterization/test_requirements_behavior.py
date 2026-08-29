from rflp_lite.application.requirements_workbench import (
    accept_traceable,
    analyze_artifact,
    generate_model,
)


def test_requirements_vertical_slice_keeps_stable_semantics() -> None:
    state = analyze_artifact(
        "requirements.txt",
        "管理员必须恢复历史版本。\n审计人员必须查看恢复记录。".encode(),
    )
    stakeholder_ids = tuple(item["id"] for item in state["stakeholders"])
    accepted = generate_model(accept_traceable(state))

    assert stakeholder_ids
    assert {item["layer"] for item in accepted["rflp"]["elements"]} == {"R", "F", "L", "P"}
    assert accepted["coverage"] == {"R-F": 100, "F-L": 100, "L-P": 100}
