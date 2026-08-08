from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resource_path(relative: str) -> Path:
    """Resolve a resource from the source checkout or an installed wheel."""
    source_path = PROJECT_ROOT / relative
    if source_path.exists():
        return source_path
    return PACKAGE_ROOT / "resources" / relative


def default_workspace_root() -> Path:
    if (PROJECT_ROOT / "schemas").is_dir():
        return PROJECT_ROOT / "workspaces"
    return Path.cwd() / "workspaces"
