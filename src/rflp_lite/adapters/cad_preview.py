"""Deterministic vendor-neutral CAD preview adapter.

This adapter creates a parameterized solid preview and OpenSCAD/OBJ payloads;
it is explicitly development evidence until a registered real CAD adapter is
configured.  It never executes arbitrary scripts or natural-language code.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.detail_design import CadExecutionPlan, CadModelReference
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.ports.cad import CadCapabilities, CadOperationResult


_OPERATIONS = (
    "create_part",
    "create_box",
    "create_cylinder",
    "create_shell",
    "create_gear",
    "add_rib",
    "add_shaft_step",
    "add_hole",
    "add_fillet",
    "set_material",
    "create_assembly",
)


def _numbers(raw: object, names: tuple[str, ...]) -> tuple[float, ...]:
    if not isinstance(raw, Mapping):
        raise ContractViolation("CAD operation parameters must be an object")
    values = []
    for name in names:
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
            raise ContractViolation(f"CAD parameter {name} must be a positive number")
        values.append(float(value))
    return tuple(values)


def _positive(raw: Mapping[str, Any], name: str) -> float:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ContractViolation(f"CAD parameter {name} must be a positive number")
    return float(value)


def _part(parts: list[dict[str, Any]], operation, parameters: Mapping[str, Any]) -> dict[str, Any]:
    part_id = str(parameters.get("part_id", operation.id)).strip() or operation.id
    name = str(parameters.get("name", part_id))
    item = {"id": part_id, "name": name, "features": [], "material": "", "bbox_mm": [0.0, 0.0, 0.0], "solids": []}
    parts.append(item)
    return item


def _active_part(parts: list[dict[str, Any]], operation, parameters: Mapping[str, Any]) -> dict[str, Any]:
    part_id = str(parameters.get("part_id", "")).strip()
    existing = next((item for item in parts if item["id"] == part_id), None)
    return existing or _part(parts, operation, parameters)


def _apply_operation(parts, assemblies, operation) -> None:
    parameters = dict(operation.parameters)
    if operation.operation == "create_part":
        _part(parts, operation, parameters)
        return
    if operation.operation == "create_assembly":
        assemblies.append({"id": str(parameters.get("assembly_id", operation.id)), "component_ids": list(parameters.get("component_ids", ()))})
        return
    target = _active_part(parts, operation, parameters)
    if operation.operation in {"create_box", "create_cylinder"}:
        names = ("length_mm", "width_mm", "height_mm") if operation.operation == "create_box" else ("diameter_mm", "height_mm")
        dimensions = _numbers(parameters, names)
        target["bbox_mm"] = list(dimensions if len(dimensions) == 3 else (dimensions[0], dimensions[0], dimensions[1]))
        if operation.operation == "create_box":
            target["solids"] = [{"kind": "box", "size": list(dimensions), "origin": [0.0, 0.0, 0.0]}]
        target["features"].append({"id": operation.id, "kind": operation.operation, "parameters": parameters})
        return
    if operation.operation == "create_shell":
        length, width, height = _numbers(parameters, ("length_mm", "width_mm", "height_mm"))
        wall = _positive(parameters, "wall_thickness_mm")
        if wall * 2 >= min(length, width, height):
            raise ContractViolation("shell wall thickness must leave a positive inner cavity")
        target["bbox_mm"] = [length, width, height]
        target["solids"] = [{
            "kind": "shell",
            "outer": [length, width, height],
            "wall_thickness_mm": wall,
            "origin": [0.0, 0.0, 0.0],
        }]
        target["features"].append({"id": operation.id, "kind": operation.operation, "parameters": parameters})
        return
    if operation.operation == "create_gear":
        module = _positive(parameters, "module")
        teeth = _positive(parameters, "teeth")
        face_width = _positive(parameters, "face_width_mm")
        outside = _positive(parameters, "outside_diameter_mm")
        if teeth < 6 or abs(teeth - round(teeth)) > 1e-6:
            raise ContractViolation("gear teeth must be an integer of at least 6")
        target["bbox_mm"] = [outside, outside, face_width]
        target["solids"] = [{
            "kind": "cylinder",
            "diameter": outside,
            "height": face_width,
            "origin": [0.0, 0.0, 0.0],
        }]
        target["features"].append({
            "id": operation.id,
            "kind": operation.operation,
            "parameters": {**parameters, "module": module, "teeth": int(teeth)},
        })
        return
    if operation.operation == "add_rib":
        length, width, height, x, y, z = _numbers(
            parameters,
            ("length_mm", "width_mm", "height_mm", "x_mm", "y_mm", "z_mm"),
        )
        target["solids"].append({"kind": "box", "size": [length, width, height], "origin": [x, y, z]})
        bbox = target["bbox_mm"]
        target["bbox_mm"] = [max(float(bbox[0]), x + length), max(float(bbox[1]), y + width), max(float(bbox[2]), z + height)]
        target["features"].append({"id": operation.id, "kind": operation.operation, "parameters": parameters})
        return
    if operation.operation == "add_shaft_step":
        diameter = _positive(parameters, "diameter_mm")
        length = _positive(parameters, "length_mm")
        offset = _positive(parameters, "offset_mm")
        base_diameter = _positive(parameters, "base_diameter_mm")
        if diameter >= base_diameter:
            raise ContractViolation("shaft step diameter must be smaller than base diameter")
        target["solids"].append({
            "kind": "cylinder",
            "diameter": diameter,
            "height": length,
            "origin": [0.0, 0.0, offset],
        })
        bbox = target["bbox_mm"]
        target["bbox_mm"] = [
            max(float(bbox[0]), base_diameter),
            max(float(bbox[1]), base_diameter),
            max(float(bbox[2]), offset + length),
        ]
        target["features"].append({"id": operation.id, "kind": operation.operation, "parameters": parameters})
        return
    if operation.operation in {"add_hole", "add_fillet"}:
        names = ("diameter_mm", "depth_mm") if operation.operation == "add_hole" else ("radius_mm",)
        _numbers(parameters, names)
        target["features"].append({"id": operation.id, "kind": operation.operation, "parameters": parameters})
        return
    if operation.operation == "set_material":
        material = str(parameters.get("material", "")).strip()
        if not material:
            raise ContractViolation("material is required")
        target["material"] = material
        return
    raise ContractViolation(f"unsupported CAD operation: {operation.operation}")


def _obj_for_cuboid(size: tuple[float, float, float], origin: tuple[float, float, float], index_offset: int) -> tuple[str, int]:
    x, y, z = size
    ox, oy, oz = origin
    if min(x, y, z) <= 0:
        return "", index_offset
    vertices = ((ox, oy, oz), (ox + x, oy, oz), (ox + x, oy + y, oz), (ox, oy + y, oz), (ox, oy, oz + z), (ox + x, oy, oz + z), (ox + x, oy + y, oz + z), (ox, oy + y, oz + z))
    faces = ((1, 2, 3, 4), (5, 8, 7, 6), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 8, 4), (5, 1, 4, 8))
    offset = index_offset
    return "\n".join([*(f"v {a:g} {b:g} {c:g}" for a, b, c in vertices), *("f " + " ".join(str(index + offset) for index in face) for face in faces)]), index_offset + 8


def _obj_for_cylinder(diameter: float, height: float, origin: tuple[float, float, float], index_offset: int) -> tuple[str, int]:
    if diameter <= 0 or height <= 0:
        return "", index_offset
    import math

    ox, oy, oz = origin
    radius = diameter / 2.0
    sides = 16
    vertices = [
        (ox + radius * math.cos(2 * math.pi * index / sides), oy + radius * math.sin(2 * math.pi * index / sides), oz + z)
        for z in (0.0, height)
        for index in range(sides)
    ]
    faces = []
    for index in range(sides):
        nxt = (index + 1) % sides
        faces.extend(((index, nxt, sides + nxt, sides + index),))
    faces.append(tuple(range(sides - 1, -1, -1)))
    faces.append(tuple(range(sides, sides * 2)))
    offset = index_offset
    return "\n".join([*(f"v {a:g} {b:g} {c:g}" for a, b, c in vertices), *("f " + " ".join(str(index + offset + 1) for index in face) for face in faces)]), index_offset + len(vertices)


def _obj_for_part(part: Mapping[str, object]) -> str:
    solids = part.get("solids", ())
    if not isinstance(solids, (list, tuple)) or not solids:
        x, y, z = (float(value) for value in part.get("bbox_mm", (0.0, 0.0, 0.0)))
        solids = ({"kind": "box", "size": [x, y, z], "origin": [0.0, 0.0, 0.0]},)
    fragments: list[str] = []
    offset = 0
    for solid in solids:
        if not isinstance(solid, Mapping):
            continue
        kind = solid.get("kind")
        origin = tuple(float(value) for value in solid.get("origin", (0.0, 0.0, 0.0)))
        if kind == "box":
            size = tuple(float(value) for value in solid.get("size", (0.0, 0.0, 0.0)))
            fragment, offset = _obj_for_cuboid(size, origin, offset)
        elif kind == "cylinder":
            fragment, offset = _obj_for_cylinder(float(solid.get("diameter", 0.0)), float(solid.get("height", 0.0)), origin, offset)
        elif kind == "shell":
            size = tuple(float(value) for value in solid.get("outer", (0.0, 0.0, 0.0)))
            fragment, offset = _obj_for_cuboid(size, origin, offset)
        else:
            continue
        if fragment:
            fragments.append(fragment)
    return "\n".join(fragments)


def _open_scad_for_part(part: Mapping[str, object]) -> str:
    solids = part.get("solids", ())
    if not isinstance(solids, (list, tuple)) or not solids:
        x, y, z = (float(value) for value in part.get("bbox_mm", (0.0, 0.0, 0.0)))
        solids = ({"kind": "box", "size": [x, y, z], "origin": [0.0, 0.0, 0.0]},)
    lines = [f"// {part['id']}"]
    for solid in solids:
        if not isinstance(solid, Mapping):
            continue
        origin = [float(value) for value in solid.get("origin", (0.0, 0.0, 0.0))]
        kind = solid.get("kind")
        if kind == "box":
            size = [float(value) for value in solid.get("size", (0.0, 0.0, 0.0))]
            lines.append(f"translate([{origin[0]}, {origin[1]}, {origin[2]}]) cube([{size[0]}, {size[1]}, {size[2]}]);")
        elif kind == "cylinder":
            diameter = float(solid.get("diameter", 0.0))
            height = float(solid.get("height", 0.0))
            if diameter > 0 and height > 0:
                lines.append(f"translate([{origin[0]}, {origin[1]}, {origin[2]}]) cylinder(d={diameter}, h={height}, $fn=48);")
        elif kind == "shell":
            outer = [float(value) for value in solid.get("outer", (0.0, 0.0, 0.0))]
            wall = float(solid.get("wall_thickness_mm", 0.0))
            inner = [value - 2 * wall for value in outer]
            if all(value > 0 for value in inner):
                lines.append(
                    "difference() { "
                    f"translate([{origin[0]}, {origin[1]}, {origin[2]}]) cube([{outer[0]}, {outer[1]}, {outer[2]}]); "
                    f"translate([{origin[0] + wall}, {origin[1] + wall}, {origin[2] + wall}]) cube([{inner[0]}, {inner[1]}, {inner[2]}]); "
                    "}"
                )
    return "\n".join(lines)


def _legacy_obj_for_box(part: Mapping[str, object]) -> str:
    """Retain the old private helper name for integrations importing it."""
    x, y, z = (float(value) for value in part.get("bbox_mm", (0.0, 0.0, 0.0)))
    if min(x, y, z) <= 0:
        return ""
    return _obj_for_cuboid((x, y, z), (0.0, 0.0, 0.0), 0)[0]


def _model_payload(plan: CadExecutionPlan) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    assemblies: list[dict[str, Any]] = []
    for operation in plan.operations:
        _apply_operation(parts, assemblies, operation)
    obj = "\n".join(_obj_for_part(part) for part in parts if _obj_for_part(part))
    return {
        "schema_version": "parametric-cad-preview.v1",
        "units": "mm",
        "parts": parts,
        "assemblies": assemblies,
        "obj": obj,
        "open_scad_source": "\n".join(_open_scad_for_part(part) for part in parts if _open_scad_for_part(part)),
    }


def _result(plan: CadExecutionPlan, payload: Mapping[str, object], revision: int, status: str) -> CadOperationResult:
    artifact_hash = canonical_hash(payload)
    reference = CadModelReference(
        id=f"cad-preview-{artifact_hash[:16]}",
        cad_system="vendor-neutral-preview",
        adapter_version="preview-v1",
        document_id=plan.id,
        revision=revision,
        units="mm",
        model_format="parametric-cad-preview.v1",
        artifact_hash=artifact_hash,
        status=status,
        source_kind="development",
    )
    return CadOperationResult(reference, dict(payload), ())


class PreviewCadAdapter:
    id = "cad.vendor-neutral.preview"
    version = "preview-v1"

    def capabilities(self) -> CadCapabilities:
        return CadCapabilities(
            "vendor-neutral-preview", self.version, _OPERATIONS, ("mm",), "development", True, "not_applicable"
        )

    def preview_plan(self, plan: CadExecutionPlan, context: Mapping[str, object] | None = None) -> CadOperationResult:
        _validate_plan(plan, self.capabilities())
        return _result(plan, _model_payload(plan), 0, "preview")

    def execute_plan(self, plan: CadExecutionPlan, context: Mapping[str, object] | None = None) -> CadOperationResult:
        if plan.approval_status != "approved":
            raise ContractViolation("CAD plan must be approved before execution")
        _validate_plan(plan, self.capabilities())
        return _result(plan, _model_payload(plan), 1, "completed")


def _validate_plan(plan: CadExecutionPlan, capabilities: CadCapabilities) -> None:
    if not plan.operations:
        raise ContractViolation("CAD plan must contain at least one operation")
    allowed = set(capabilities.supported_operations)
    ids: set[str] = set()
    for operation in plan.operations:
        if operation.id in ids:
            raise ContractViolation(f"duplicate CAD operation id: {operation.id}")
        if operation.operation not in allowed:
            raise ContractViolation(f"CAD operation is not supported: {operation.operation}")
        if any(dependency not in ids for dependency in operation.depends_on):
            raise ContractViolation(f"CAD operation dependency is not earlier: {operation.id}")
        ids.add(operation.id)


__all__ = ["PreviewCadAdapter"]
