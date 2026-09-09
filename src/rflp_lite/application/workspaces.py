from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation
from rflp_lite.governance.profile import Profile
from rflp_lite.governance.validation import validate_json
from rflp_lite.application.resources import PROJECT_ROOT, resource_path


_WORKSPACE_NAME = re.compile(r"[^\W_][\w.-]{0,63}\Z", re.UNICODE)


@dataclass(frozen=True, slots=True)
class WorkspaceRef:
    name: str
    path: Path
    profile_path: Path
    initialized: bool


def initialize_workspace(path: Path) -> WorkspaceRef:
    workspace = path.resolve()
    profile_path = workspace / "profile.json"
    if profile_path.exists():
        raise ContractViolation(f"workspace already exists: {workspace.name}")
    profile = Profile()
    validate_json(profile.as_dict(), resource_path("schemas/profile.schema.json"))
    workspace.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(canonical_json(profile.as_dict()) + "\n", encoding="utf-8")
    return WorkspaceRef(workspace.name, workspace, profile_path, True)


def managed_workspace(root: Path, name: str) -> Path:
    if not _WORKSPACE_NAME.fullmatch(name):
        raise ContractViolation(
            "项目名须为 1-64 个字符，允许中文、字母、数字、点、下划线和短横线，且不得包含空格或路径分隔符"
        )
    resolved_root = root.resolve()
    candidate = (resolved_root / name).resolve()
    if candidate.parent != resolved_root:
        raise ContractViolation("workspace path escapes the managed root")
    return candidate


def create_managed_workspace(root: Path, name: str) -> WorkspaceRef:
    return initialize_workspace(managed_workspace(root, name))


def list_managed_workspaces(root: Path) -> tuple[WorkspaceRef, ...]:
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        return ()
    values = (
        WorkspaceRef(path.name, path.resolve(), path.resolve() / "profile.json", True)
        for path in resolved_root.iterdir()
        if path.is_dir() and (path / "profile.json").is_file()
    )
    return tuple(sorted(values, key=lambda item: item.name))
