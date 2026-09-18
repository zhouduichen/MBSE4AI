from __future__ import annotations

from rflp_lite.adapters.cad_preview import PreviewCadAdapter
from rflp_lite.domain.detail_design import CadExecutionPlan, CadOperation


def _plan(*operations: CadOperation) -> CadExecutionPlan:
    return CadExecutionPlan("plan-1", "intent-1", operations)


def test_preview_rib_operation_changes_geometry_payload_and_hash():
    adapter = PreviewCadAdapter()
    base = _plan(
        CadOperation("part", "create_part", (("part_id", "part-1"),)),
        CadOperation(
            "box",
            "create_box",
            (("part_id", "part-1"), ("length_mm", 100), ("width_mm", 50), ("height_mm", 10)),
            ("part",),
        ),
    )
    ribbed = _plan(
        *base.operations,
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
    )

    base_result = adapter.preview_plan(base)
    ribbed_result = adapter.preview_plan(ribbed)

    assert ribbed_result.model_payload["parts"][0]["bbox_mm"] == [100.0, 50.0, 30.0]
    assert ribbed_result.model_payload["parts"][0]["features"][-1]["kind"] == "add_rib"
    assert "cube([80.0, 4.0, 20.0])" in ribbed_result.model_payload["open_scad_source"]
    assert len(ribbed_result.model_payload["obj"].splitlines()) > len(base_result.model_payload["obj"].splitlines())
    assert ribbed_result.model.artifact_hash != base_result.model.artifact_hash


def test_preview_keeps_fillet_as_explicit_structure_feature():
    adapter = PreviewCadAdapter()
    result = adapter.preview_plan(
        _plan(
            CadOperation("part", "create_part", (("part_id", "part-1"),)),
            CadOperation(
                "box",
                "create_box",
                (("part_id", "part-1"), ("length_mm", 100), ("width_mm", 50), ("height_mm", 10)),
                ("part",),
            ),
            CadOperation(
                "fillet",
                "add_fillet",
                (("part_id", "part-1"), ("radius_mm", 2.0)),
                ("box",),
            ),
        )
    )
    assert result.model_payload["parts"][0]["features"][-1]["kind"] == "add_fillet"
