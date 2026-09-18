from __future__ import annotations

from rflp_lite.adapters.drawing_preview import PreviewDrawingAdapter


def test_preview_drawing_emits_shared_annotation_svg_and_stable_hash():
    model = {
        "parts": [
            {
                "id": "bracket",
                "bbox_mm": [100, 50, 10],
                "features": [
                    {
                        "id": "hole-1",
                        "kind": "add_hole",
                        "parameters": {"diameter_mm": 8},
                    }
                ],
            }
        ]
    }
    adapter = PreviewDrawingAdapter()

    first = adapter.generate_annotations(model)
    second = adapter.generate_annotations(model)

    assert {"top", "isometric"} <= set(first.annotations[0].views)
    assert {"drawing_svg", "drawing_hash", "drawing_backend", "source_kind"} <= set(first.artifacts)
    assert first.artifacts["drawing_svg"].startswith("<svg")
    assert "bracket · top" in first.artifacts["drawing_svg"]
    assert "bracket · side" in first.artifacts["drawing_svg"]
    assert "100 mm" in first.artifacts["drawing_svg"]
    assert "平面度 0.20 | A" in first.artifacts["drawing_svg"]
    assert first.artifacts["source_kind"] == "development"
    assert first.artifacts["drawing_hash"] == second.artifacts["drawing_hash"]


def test_preview_drawing_keeps_invalid_geometry_as_diagnostic():
    result = PreviewDrawingAdapter().generate_annotations(
        {"parts": [{"id": "broken", "bbox_mm": ["bad", 20, 5], "features": []}]}
    )

    assert any("broken" in item for item in result.diagnostics)
    assert result.artifacts["drawing_svg"].startswith("<svg")


def test_preview_drawing_annotates_profile_features():
    result = PreviewDrawingAdapter().generate_annotations({
        "parts": [{
            "id": "housing",
            "bbox_mm": [120, 80, 60],
            "features": [{
                "id": "shell",
                "kind": "create_shell",
                "parameters": {"wall_thickness_mm": 2},
            }, {
                "id": "gear",
                "kind": "create_gear",
                "parameters": {"module": 2, "teeth": 20, "bore_diameter_mm": 8},
            }],
        }],
    })

    kinds = {item.annotation_kind for item in result.annotations}
    assert {"wall_thickness", "gear_bore_diameter", "gear_profile"} <= kinds
    assert all(item.views == ("top", "isometric") for item in result.annotations)
