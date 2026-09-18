"""Allowlisted FreeCAD execution through an explicitly configured SSH host.

The adapter sends generated, structured operation data to ``freecadcmd`` over
stdin.  It never evaluates user text as Python and never starts a local model
or a local CAD process.  The remote command and host are deployment settings;
the operation vocabulary is validated before any remote execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
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
_MARKER = "AI4MBSE_FREECAD_RESULT="
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class FreeCadRemoteConfig:
    ssh_host: str
    freecad_command: str
    artifact_root: Path
    remote_root: str = "/home/intern/huangjiahao/AI4MBSE-cad-runtime"
    timeout_seconds: float = 180.0

    @classmethod
    def from_env(cls, artifact_root: Path) -> "FreeCadRemoteConfig":
        host = os.getenv("AI4MBSE_CAD_SSH_HOST", "Jiayu-intern").strip()
        command = os.getenv(
            "AI4MBSE_FREECAD_COMMAND",
            "/home/intern/miniconda3/envs/ai4mbse-freecad/bin/freecadcmd",
        ).strip()
        remote_root = os.getenv(
            "AI4MBSE_CAD_REMOTE_ROOT",
            "/home/intern/huangjiahao/AI4MBSE-cad-runtime",
        ).strip()
        config = cls(host, command, artifact_root.resolve(), remote_root)
        config.validate()
        return config

    def validate(self) -> None:
        if not self.ssh_host or any(char.isspace() for char in self.ssh_host):
            raise ContractViolation("FreeCAD SSH host must be a non-empty host token")
        if not self.freecad_command.startswith("/") or any(
            char in self.freecad_command for char in "\r\n\x00"
        ):
            raise ContractViolation("FreeCAD command must be an absolute remote path")
        if not self.remote_root.startswith("/") or any(
            char in self.remote_root for char in "\r\n\x00"
        ):
            raise ContractViolation("FreeCAD remote root must be an absolute path")
        if self.timeout_seconds <= 0:
            raise ContractViolation("FreeCAD timeout must be positive")


def _safe_segment(value: str, label: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value):
        raise ContractViolation(f"{label} contains unsupported path characters")
    return value


def _positive(parameters: Mapping[str, Any], name: str) -> float:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise ContractViolation(f"CAD parameter {name} must be a positive number")
    return float(value)


def _validate_plan(plan: CadExecutionPlan) -> None:
    if not plan.operations:
        raise ContractViolation("CAD plan must contain at least one operation")
    seen: set[str] = set()
    for operation in plan.operations:
        if operation.id in seen:
            raise ContractViolation(f"duplicate CAD operation id: {operation.id}")
        if operation.operation not in _OPERATIONS:
            raise ContractViolation(f"CAD operation is not supported: {operation.operation}")
        if any(item not in seen for item in operation.depends_on):
            raise ContractViolation(f"CAD operation dependency is not earlier: {operation.id}")
        parameters = dict(operation.parameters)
        if operation.operation == "create_box":
            for name in ("length_mm", "width_mm", "height_mm"):
                _positive(parameters, name)
        if operation.operation == "create_cylinder":
            _positive(parameters, "diameter_mm")
            _positive(parameters, "height_mm")
        if operation.operation == "add_hole":
            _positive(parameters, "diameter_mm")
            _positive(parameters, "depth_mm")
        if operation.operation == "add_fillet":
            _positive(parameters, "radius_mm")
        if operation.operation == "set_material" and not str(parameters.get("material", "")).strip():
            raise ContractViolation("material is required")
        seen.add(operation.id)


def _plan_data(plan: CadExecutionPlan) -> list[dict[str, Any]]:
    return [operation.as_dict() for operation in plan.operations]


def _freecad_script(plan: CadExecutionPlan, output_dir: str) -> str:
    plan_literal = json.dumps(_plan_data(plan), ensure_ascii=False, separators=(",", ":"))
    output_literal = json.dumps(output_dir, ensure_ascii=False)
    return f'''import json, os, re
import FreeCAD as App
import Part

plan = json.loads({json.dumps(plan_literal, ensure_ascii=False)})
output_dir = json.loads({json.dumps(output_literal, ensure_ascii=False)})
os.makedirs(output_dir, exist_ok=True)
doc = App.newDocument("AI4MBSE")
parts = {{}}
shapes = {{}}
records = []
assemblies = []
diagnostics = []

def safe_name(value):
    token = re.sub(r"[^A-Za-z0-9_]", "_", str(value))
    return ("part_" + token)[:80]

def get_part(params, operation_id):
    part_id = str(params.get("part_id", operation_id))
    if part_id not in parts:
        obj = doc.addObject("Part::Feature", safe_name(part_id))
        obj.Label = str(params.get("name", part_id))
        parts[part_id] = obj
        shapes[part_id] = Part.Shape()
        records.append({{"id": part_id, "name": obj.Label, "material": "", "features": []}})
    return part_id, parts[part_id]

for operation in plan:
    name = operation["operation"]
    params = dict(operation.get("parameters", {{}}))
    if name == "create_part":
        get_part(params, operation["id"])
    elif name == "create_assembly":
        assembly_id = str(params.get("assembly_id", operation["id"]))
        assembly = doc.addObject("App::Part", safe_name(assembly_id))
        component_ids = list(params.get("component_ids", []))
        for component_id in component_ids:
            if str(component_id) in parts:
                assembly.addObject(parts[str(component_id)])
        assemblies.append({{"id": assembly_id, "component_ids": component_ids}})
    else:
        part_id, obj = get_part(params, operation["id"])
        if name == "create_box":
            shapes[part_id] = Part.makeBox(float(params["length_mm"]), float(params["width_mm"]), float(params["height_mm"]))
        elif name == "create_cylinder":
            shapes[part_id] = Part.makeCylinder(float(params["diameter_mm"]) / 2.0, float(params["height_mm"]))
        elif name == "add_hole":
            current = shapes[part_id]
            box = current.BoundBox
            x = float(params.get("x_mm", box.XMin + box.XLength / 2.0))
            y = float(params.get("y_mm", box.YMin + box.YLength / 2.0))
            z = float(params.get("z_mm", box.ZMin))
            cutter = Part.makeCylinder(float(params["diameter_mm"]) / 2.0, float(params["depth_mm"]), App.Vector(x, y, z))
            shapes[part_id] = current.cut(cutter)
        elif name == "add_fillet":
            try:
                shapes[part_id] = shapes[part_id].makeFillet(float(params["radius_mm"]), shapes[part_id].Edges)
            except Exception as exc:
                diagnostics.append("fillet " + operation["id"] + " was not applied: " + str(exc))
        elif name == "set_material":
            record = next(item for item in records if item["id"] == part_id)
            record["material"] = str(params["material"])
            if "Material" not in obj.PropertiesList:
                obj.addProperty("App::PropertyString", "Material", "AI4MBSE")
            obj.Material = record["material"]
        else:
            raise RuntimeError("unsupported operation: " + name)
        if name not in {{"set_material"}}:
            record = next(item for item in records if item["id"] == part_id)
            record["features"].append({{"id": operation["id"], "kind": name, "parameters": params}})
        obj.Shape = shapes[part_id]

doc.recompute()
fcstd_path = os.path.join(output_dir, "model.FCStd")
step_path = os.path.join(output_dir, "model.step")
objects = [obj for obj in parts.values() if not obj.Shape.isNull()]
if not objects:
    raise RuntimeError("FreeCAD plan did not create a solid")
doc.saveAs(fcstd_path)
Part.export(objects, step_path)
for record in records:
    obj = parts[record["id"]]
    shape = obj.Shape
    if shape.isNull():
        record.update({{"bbox_mm": [0.0, 0.0, 0.0], "volume_mm3": 0.0, "shape_valid": False}})
    else:
        record.update({{"bbox_mm": [float(shape.BoundBox.XLength), float(shape.BoundBox.YLength), float(shape.BoundBox.ZLength)], "volume_mm3": float(shape.Volume), "shape_valid": bool(shape.isValid())}})
reloaded = App.openDocument(fcstd_path)
reloaded.recompute()
reloaded_objects = [obj for obj in reloaded.Objects if hasattr(obj, "Shape") and not obj.Shape.isNull()]
reload_volume = sum(float(obj.Shape.Volume) for obj in reloaded_objects)
reload_valid = all(bool(obj.Shape.isValid()) for obj in reloaded_objects)
App.closeDocument(reloaded.Name)
payload = {{"parts": records, "assemblies": assemblies, "diagnostics": diagnostics, "remote_artifacts": {{"fcstd": fcstd_path, "step": step_path}}, "reload_verification": {{"fcstd_readable": True, "solid_count": len(reloaded_objects), "volume_mm3": reload_volume, "shape_valid": reload_valid}}}}
print("{_MARKER}" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
'''


def _artifact_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_artifact(config: FreeCadRemoteConfig, remote: str, local: Path) -> None:
    local.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["scp", "-q", "-o", "BatchMode=yes", f"{config.ssh_host}:{remote}", str(local)],
        capture_output=True,
        text=True,
        timeout=config.timeout_seconds,
        check=False,
    )
    if result.returncode != 0 or not local.is_file() or local.stat().st_size == 0:
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise ContractViolation(f"FreeCAD artifact download failed: {detail}")


def _result(
    plan: CadExecutionPlan,
    payload: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
    revision: int,
    status: str,
) -> CadOperationResult:
    files = {name: _artifact_hash(path) for name, path in artifact_paths.items()}
    model_payload = {
        "schema_version": "freecad-cad-model.v1",
        "cad_system": "FreeCAD",
        "source_kind": "real",
        "units": "mm",
        "parts": payload.get("parts", []),
        "assemblies": payload.get("assemblies", []),
        "diagnostics": payload.get("diagnostics", []),
        "reload_verification": payload.get("reload_verification", {}),
        "artifacts": {name: str(path) for name, path in artifact_paths.items()},
        "artifact_hashes": files,
        "remote_artifacts": payload.get("remote_artifacts", {}),
    }
    artifact_hash = canonical_hash({"payload": model_payload, "files": files})
    reference = CadModelReference(
        id=f"freecad-{artifact_hash[:16]}",
        cad_system="FreeCAD",
        adapter_version="freecad-remote-1.1.3",
        document_id=plan.id,
        revision=revision,
        units="mm",
        model_format="FreeCAD.FCStd+STEP",
        artifact_hash=artifact_hash,
        status=status,
        source_kind="real",
    )
    return CadOperationResult(reference, model_payload, tuple(str(item) for item in payload.get("diagnostics", [])))


class FreeCadRemoteAdapter:
    id = "cad.freecad.remote"
    version = "freecad-remote-1.1.3"

    def __init__(self, config: FreeCadRemoteConfig):
        self.config = config
        self.config.validate()

    def capabilities(self) -> CadCapabilities:
        return CadCapabilities(
            "FreeCAD",
            self.version,
            _OPERATIONS,
            ("mm",),
            "real",
            True,
            "open_source",
        )

    def preview_plan(self, plan: CadExecutionPlan, context: Mapping[str, object] | None = None) -> CadOperationResult:
        return self._run(plan, 0, "preview")

    def execute_plan(self, plan: CadExecutionPlan, context: Mapping[str, object] | None = None) -> CadOperationResult:
        if plan.approval_status != "approved":
            raise ContractViolation("CAD plan must be approved before execution")
        return self._run(plan, 1, "completed")

    def _run(self, plan: CadExecutionPlan, revision: int, status: str) -> CadOperationResult:
        _validate_plan(plan)
        plan_segment = _safe_segment(plan.id, "CAD plan id")
        remote_dir = f"{self.config.remote_root.rstrip('/')}/{plan_segment}/{status}"
        process = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", self.config.ssh_host, self.config.freecad_command],
            input=f"exec({_freecad_script(plan, remote_dir)!r})\n",
            capture_output=True,
            text=True,
            timeout=self.config.timeout_seconds,
            check=False,
        )
        if process.returncode != 0:
            detail = (process.stderr or process.stdout).strip()[-1000:]
            raise ContractViolation(f"FreeCAD remote execution failed: {detail}")
        payload = _parse_payload(process.stdout)
        local_dir = self.config.artifact_root / plan_segment / status
        artifact_paths = {
            "fcstd": local_dir / "model.FCStd",
            "step": local_dir / "model.step",
        }
        for name, path in artifact_paths.items():
            remote = str(payload.get("remote_artifacts", {}).get(name, ""))
            if not remote:
                raise ContractViolation(f"FreeCAD result did not provide {name} artifact")
            _copy_artifact(self.config, remote, path)
        return _result(plan, payload, artifact_paths, revision, status)


def _parse_payload(stdout: str) -> Mapping[str, Any]:
    line = next((item for item in reversed(stdout.splitlines()) if item.startswith(_MARKER)), "")
    if not line:
        raise ContractViolation("FreeCAD output did not contain a structured result")
    try:
        payload = json.loads(line[len(_MARKER):])
    except json.JSONDecodeError as exc:
        raise ContractViolation("FreeCAD structured result is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ContractViolation("FreeCAD structured result must be an object")
    return payload


__all__ = ["FreeCadRemoteAdapter", "FreeCadRemoteConfig"]
