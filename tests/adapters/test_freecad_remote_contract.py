from __future__ import annotations

from rflp_lite.adapters.freecad_remote import _freecad_script, _validate_plan
from rflp_lite.domain.detail_design import CadExecutionPlan, CadOperation


def test_freecad_script_contains_allowlisted_rib_geometry_without_ssh():
    plan = CadExecutionPlan(
        "plan-1",
        "intent-1",
        (
            CadOperation("part", "create_part", (("part_id", "part-1"),)),
            CadOperation(
                "box",
                "create_box",
                (("part_id", "part-1"), ("length_mm", 100), ("width_mm", 50), ("height_mm", 10)),
                ("part",),
            ),
            CadOperation(
                "rib-1",
                "add_rib",
                (
                    ("part_id", "part-1"),
                    ("length_mm", 80),
                    ("width_mm", 4),
                    ("height_mm", 20),
                    ("x_mm", 10),
                    ("y_mm", 12),
                    ("z_mm", 10),
                ),
                ("box",),
            ),
        ),
    )

    _validate_plan(plan)
    script = _freecad_script(plan, "/tmp/ai4mbse-test")

    assert '"add_rib"' in script
    assert "Part.makeBox" in script
    assert "fuse" in script
