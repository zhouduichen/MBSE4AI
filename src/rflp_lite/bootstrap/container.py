"""Small composition root for the AI4MBSE Harness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rflp_lite.bootstrap.v2 import V2Services, build_v2_services
from rflp_lite.application.llm_profiles import default_config_dir


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    workspace_root: Path
    fixture_root: Path | None
    v2: V2Services


def build_container(
    workspace_root: Path, fixture_root: Path | None = None
) -> ApplicationContainer:
    root = workspace_root.resolve()
    return ApplicationContainer(root, fixture_root, build_v2_services(root, config_dir=default_config_dir()))
