from __future__ import annotations

import importlib.metadata
import platform
import sys

from rflp_lite.governance.profile import Profile


_COMPONENTS = (
    "jsonschema",
    "prance",
    "junitparser",
    "ortools",
    "hypothesis",
    "import-linter",
)


def dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for component in _COMPONENTS:
        try:
            versions[component] = importlib.metadata.version(component)
        except importlib.metadata.PackageNotFoundError:
            versions[component] = "not-installed"
    return versions


def build_manifest(
    profile: Profile,
    fixture_hashes: dict[str, str],
    stage_hashes: dict[str, str],
    baseline_hash: str,
    result_hash: str,
    status: str = "passed",
) -> dict[str, object]:
    return {
        "profile": profile.as_dict(),
        "python": platform.python_version(),
        "platform": f"{sys.platform}-{platform.machine()}",
        "dependencies": dependency_versions(),
        "fixture_hashes": dict(sorted(fixture_hashes.items())),
        "stage_hashes": dict(sorted(stage_hashes.items())),
        "baseline_hash": baseline_hash,
        "result_hash": result_hash,
        "status": status,
    }

