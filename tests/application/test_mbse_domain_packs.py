import json
import subprocess
import sys
from pathlib import Path

import pytest

from rflp_lite.application import mbse_domain_packs as loader
from rflp_lite.application.mbse_domain_packs import (
    load_domain_pack,
    mbse_domain_pack_hash,
    validate_candidate_payload,
)
from rflp_lite.domain.errors import ContractViolation


def _urban_medical_pack() -> dict[str, object]:
    return {
        "id": "urban-medical-aam-v1",
        "version": 1,
        "display_name": "城市医疗空中交通",
        "description": "用于城市医疗飞行任务的 MBSE 发现领域包。",
        "element_schemas": {
            "stakeholder": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "category", "goals", "interactions"],
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "category": {"type": "string", "minLength": 1},
                    "goals": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "interactions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            }
        },
        "stakeholder_lenses": [
            {"id": "medical", "label": "医疗"},
            {"id": "operations", "label": "运营"},
            {"id": "regulatory", "label": "监管"},
            {"id": "public_environment", "label": "公共环境"},
        ],
        "lifecycle_phases": [
            {"id": "dispatch", "label": "任务调度"},
            {"id": "service", "label": "运行服务"},
        ],
        "scenario_dimensions": [
            {
                "id": "weather",
                "label": "天气",
                "values": ["clear", "rain", "typhoon"],
            },
            {
                "id": "visibility",
                "label": "能见度",
                "values": ["day", "night", "low"],
            },
            {
                "id": "mission_phase",
                "label": "任务阶段",
                "values": ["dispatch", "en_route", "approach", "landing"],
            },
            {
                "id": "system_state",
                "label": "系统状态",
                "values": ["nominal", "degraded", "emergency"],
            },
            {
                "id": "medical_urgency",
                "label": "医疗紧急度",
                "values": ["routine", "urgent", "critical"],
            },
        ],
        "coverage_rules": [
            {
                "id": "medical-coverage",
                "source": "stakeholder_lenses",
                "priority": "high",
            },
            {
                "id": "scenario-coverage",
                "source": "scenario_dimensions",
                "priority": "high",
            },
        ],
        "prompt_fragments": {
            "stakeholders": "识别医疗、运营、监管和公共环境相关利益相关方。"
        },
        "diagram_groups": {
            "context": {"label": "系统上下文", "order": 0},
            "scenario": {"label": "极端场景", "order": 1},
        },
    }


def _write_pack(directory: Path, pack_id: str, payload: dict[str, object]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{pack_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def pack_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_pack(tmp_path, "urban-medical-aam-v1", _urban_medical_pack())
    _write_pack(
        tmp_path,
        "mbse-common-v1",
        {
            **_urban_medical_pack(),
            "id": "mbse-common-v1",
            "display_name": "MBSE 通用包",
        },
    )
    (tmp_path / "not-a-pack.txt").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(loader, "PACK_DIRECTORY", tmp_path)
    return tmp_path


def test_load_and_enumerate_domain_packs(pack_directory: Path):
    assert loader.list_domain_packs() == ["mbse-common-v1", "urban-medical-aam-v1"]

    pack = load_domain_pack("urban-medical-aam-v1")

    assert pack["id"] == "urban-medical-aam-v1"
    assert pack["version"] == 1
    assert mbse_domain_pack_hash(pack) == mbse_domain_pack_hash(
        load_domain_pack("urban-medical-aam-v1")
    )


def test_pack_contains_key_stakeholders_and_extreme_scenario_dimensions(
    pack_directory: Path,
):
    pack = load_domain_pack("urban-medical-aam-v1")

    stakeholder_ids = {item["id"] for item in pack["stakeholder_lenses"]}
    dimensions = {item["id"]: item["values"] for item in pack["scenario_dimensions"]}

    assert stakeholder_ids >= {
        "medical",
        "operations",
        "regulatory",
        "public_environment",
    }
    assert dimensions["weather"][-1] == "typhoon"
    assert dimensions["visibility"][-1] == "low"
    assert dimensions["system_state"][-1] == "emergency"
    assert dimensions["medical_urgency"][-1] == "critical"


def test_stakeholder_payload_is_validated(pack_directory: Path):
    pack = load_domain_pack("urban-medical-aam-v1")
    accepted = validate_candidate_payload(
        pack,
        "stakeholder",
        {
            "name": "急救医生",
            "category": "medical",
            "goals": ["稳定患者状态"],
            "interactions": ["提交医疗任务"],
        },
    )

    assert accepted["name"] == "急救医生"
    with pytest.raises(ContractViolation, match="stakeholder"):
        validate_candidate_payload(pack, "stakeholder", {"name": "急救医生"})


def test_loader_rejects_path_escape_and_core_overrides(
    pack_directory: Path, tmp_path: Path
):
    with pytest.raises(ContractViolation, match="invalid MBSE domain pack ID"):
        load_domain_pack("../urban-medical-aam-v1")

    bad = _urban_medical_pack()
    bad["core_overrides"] = ["status"]
    _write_pack(pack_directory, "bad", bad)
    with pytest.raises(ContractViolation, match="core_overrides"):
        load_domain_pack("bad", validate=False)

    outside = tmp_path.parent / "outside.json"
    outside.write_text(json.dumps(_urban_medical_pack()), encoding="utf-8")
    (pack_directory / "escape.json").symlink_to(outside)
    with pytest.raises(ContractViolation, match="not found"):
        load_domain_pack("escape", validate=False)


def test_source_and_packaged_schema_are_identical():
    source = Path("schemas/mbse-domain-pack.schema.json")
    packaged = Path("src/rflp_lite/resources/schemas/mbse-domain-pack.schema.json")

    assert source.read_bytes() == packaged.read_bytes()


def test_existing_resource_directory_can_enumerate_and_load_legacy_pack():
    assert "fixed-wing-v1" in loader.list_domain_packs()
    pack = load_domain_pack("fixed-wing-v1")
    assert pack["id"] == "fixed-wing"


def test_import_does_not_require_optional_jsonschema():
    script = """
import builtins
import sys

class BlockJsonSchema:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'jsonschema' or fullname.startswith('jsonschema.'):
            raise ModuleNotFoundError('jsonschema is optional')
        return None

sys.meta_path.insert(0, BlockJsonSchema())
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name == 'jsonschema' or name.startswith('jsonschema.'):
        raise ModuleNotFoundError('jsonschema is optional')
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import

import rflp_lite.application.mbse_domain_packs
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
