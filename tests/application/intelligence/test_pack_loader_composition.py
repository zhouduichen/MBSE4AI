import json
from pathlib import Path

import pytest

from rflp_lite.application import mbse_domain_packs as loader
from rflp_lite.application.mbse_domain_packs import load_composed_pack
from rflp_lite.domain.errors import ContractViolation


def _write_pack(directory: Path, pack_id: str, **changes: object) -> None:
    base = loader.load_domain_pack("common-v1")
    base.update({"id": pack_id, "display_name": pack_id, **changes})
    (directory / f"{pack_id}.json").write_text(
        json.dumps(base, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def composed_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_pack(tmp_path, "base-v1")
    _write_pack(
        tmp_path,
        "discipline-v1",
        extends=["base-v1"],
        stakeholder_lenses=[{"id": "mechanical", "label": "机械"}],
    )
    _write_pack(
        tmp_path,
        "overlay-v1",
        extends=["discipline-v1"],
        disciplines=["base-v1"],
        prompt_fragments={"special": "组合覆盖"},
    )
    monkeypatch.setattr(loader, "PACK_DIRECTORY", tmp_path)
    return tmp_path


def test_composed_pack_tracks_parent_sources_and_hashes(composed_directory: Path):
    result = load_composed_pack({"pack_ids": ["overlay-v1"]})

    assert result["pack_ids"] == ["base-v1", "discipline-v1", "overlay-v1"]
    assert set(result["pack_hashes"]) == set(result["pack_ids"])
    lens = {item["id"]: item for item in result["stakeholder_lenses"]}
    assert lens["mechanical"]["source_pack_id"] == "discipline-v1"
    assert result["prompt_fragments"]["special"] == "组合覆盖"


def test_composed_pack_rejects_inheritance_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_pack(tmp_path, "cycle-a", extends=["cycle-b"])
    _write_pack(tmp_path, "cycle-b", extends=["cycle-a"])
    monkeypatch.setattr(loader, "PACK_DIRECTORY", tmp_path)

    with pytest.raises(ContractViolation, match="cycle-a.*cycle-b.*cycle-a"):
        load_composed_pack({"pack_ids": ["cycle-a"]})


def test_composed_pack_rejects_unknown_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _write_pack(tmp_path, "child-v1", extends=["missing-v1"])
    monkeypatch.setattr(loader, "PACK_DIRECTORY", tmp_path)

    with pytest.raises(ContractViolation, match="not found"):
        load_composed_pack({"pack_ids": ["child-v1"]})
