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


def _part(parts: list[dict[str, Any]], operation, parameters: Mapping[str, Any]) -> dict[str, Any]:
    part_id = str(parameters.get("part_id", operation.id)).strip() or operation.id
    name = str(parameters.get("name", part_id))
    item = {"id": part_id, "name": name, "features": [], "material": "", "bbox_mm": [0.0, 0.0, 0.0]}
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


def _obj_for_box(part: Mapping[str, object]) -> str:
    x, y, z = (float(value) for value in part.get("bbox_mm", (0.0, 0.0, 0.0)))
    if min(x, y, z) <= 0:
        return ""
    vertices = ((0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z))
    faces = ((1, 2, 3, 4), (5, 8, 7, 6), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 8, 4), (5, 1, 4, 8))
    return "\n".join([*(f"v {a:g} {b:g} {c:g}" for a, b, c in vertices), *("f " + " ".join(str(index) for index in face) for face in faces)])


def _model_payload(plan: CadExecutionPlan) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    assemblies: list[dict[str, Any]] = []
    for operation in plan.operations:
        _apply_operation(parts, assemblies, operation)
    obj = "\n".join(_obj_for_box(part) for part in parts if _obj_for_box(part))
    return {
        "schema_version": "parametric-cad-preview.v1",
        "units": "mm",
        "parts": parts,
        "assemblies": assemblies,
        "obj": obj,
        "open_scad_source": "\n".join(
            f"// {part['id']}\ncube([{part['bbox_mm'][0]}, {part['bbox_mm'][1]}, {part['bbox_mm'][2]}]);"
            for part in parts
            if all(float(value) > 0 for value in part.get("bbox_mm", (0, 0, 0)))
        ),
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
