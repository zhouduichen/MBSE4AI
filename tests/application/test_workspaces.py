from pathlib import Path

import pytest

from rflp_lite.application.workspaces import (
    create_managed_workspace,
    list_managed_workspaces,
    managed_workspace,
)
from rflp_lite.domain.errors import ContractViolation


def test_managed_workspace_create_and_list(tmp_path: Path) -> None:
    created = create_managed_workspace(tmp_path / "workspaces", "demo-01")
    assert created.name == "demo-01"
    assert created.path == (tmp_path / "workspaces" / "demo-01").resolve()
    assert created.profile_path.is_file()
    assert list_managed_workspaces(tmp_path / "workspaces") == (created,)


@pytest.mark.parametrize("name", ("../escape", "/tmp/escape", "a/b", "a\\b", "", "."))
def test_managed_workspace_rejects_unsafe_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ContractViolation):
        managed_workspace(tmp_path / "workspaces", name)


def test_create_does_not_overwrite_existing_profile(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    created = create_managed_workspace(root, "demo")
    original = created.profile_path.read_text(encoding="utf-8")
    with pytest.raises(ContractViolation, match="already exists"):
        create_managed_workspace(root, "demo")
    assert created.profile_path.read_text(encoding="utf-8") == original
