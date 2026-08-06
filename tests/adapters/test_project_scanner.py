from pathlib import Path

import pytest

from rflp_lite.adapters.project_scanner import scan_project
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import AdapterFailure, ContractViolation


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "versioned-content-service"


def test_scan_example_project_element_composition():
    model, summary = scan_project(EXAMPLE)

    kinds = {}
    for element in model.elements:
        kinds[element.kind] = kinds.get(element.kind, 0) + 1
    assert kinds == {
        "module": 1,
        "class": 1,
        "function": 3,
        "api-operation": 3,
        "test-case": 1,
    }
    names = {element.name for element in model.elements}
    assert {"VersionedContentService", "save_version", "restore_version", "list_versions"} <= names
    assert {"listVersions", "saveVersion", "restoreVersion"} <= names
    assert "test_restore_version" in names

    assert model.source_root == "versioned-content-service"
    assert model.id.startswith("actualmodel-")
    assert model.hash
    assert summary["files_seen"] == 3
    assert summary["files_used"] == 3
    assert summary["files_skipped_size"] == 0
    assert summary["files_skipped_limit"] == 0
    assert summary["parse_errors"] == ()

    test_cases = [element for element in model.elements if element.kind == "test-case"]
    assert test_cases[0].status == "passed"
    assert all(element.id.startswith("actual-") for element in model.elements)
    assert [element.id for element in model.elements] == sorted(
        element.id for element in model.elements
    )


def test_scan_is_deterministic():
    first_model, first_summary = scan_project(EXAMPLE)
    second_model, second_summary = scan_project(EXAMPLE)
    assert canonical_json(first_model) == canonical_json(second_model)
    assert canonical_json(first_summary) == canonical_json(second_summary)


def test_scan_skips_hidden_vcs_and_symlinks(tmp_path: Path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hook.py").write_text("class GitInternal:\n    pass\n", encoding="utf-8")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "hidden.py").write_text("class Hidden:\n    pass\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.py").write_text("class Dep:\n    pass\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("class App:\n    pass\n", encoding="utf-8")
    (tmp_path / "link.py").symlink_to(EXAMPLE / "implementation.py")

    model, summary = scan_project(tmp_path)

    names = {element.name for element in model.elements}
    assert "App" in names
    assert names.isdisjoint({"GitInternal", "Hidden", "Dep", "VersionedContentService"})
    assert summary["files_seen"] == 1
    assert summary["files_used"] == 1


def test_scan_skips_oversized_files(tmp_path: Path):
    (tmp_path / "big.py").write_bytes(b"class Big:\n    pass\n" + b"# pad\n" * 300_000)
    (tmp_path / "small.py").write_text("class Small:\n    pass\n", encoding="utf-8")

    model, summary = scan_project(tmp_path)

    assert summary["files_skipped_size"] == 1
    assert summary["files_used"] == 1
    assert {element.name for element in model.elements} == {"small", "Small"}


def test_scan_stops_at_file_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("rflp_lite.adapters.project_scanner.MAX_FILES", 2)
    for index in range(5):
        (tmp_path / f"mod{index}.py").write_text(
            f"class Symbol{index}:\n    pass\n", encoding="utf-8"
        )

    model, summary = scan_project(tmp_path)

    assert summary["files_used"] == 2
    assert summary["files_skipped_limit"] == 3
    used_modules = {element.name for element in model.elements if element.kind == "module"}
    assert used_modules == {"mod0", "mod1"}


def test_scan_stops_at_depth_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("rflp_lite.adapters.project_scanner.MAX_DEPTH", 1)
    (tmp_path / "top.py").write_text("class Top:\n    pass\n", encoding="utf-8")
    nested = tmp_path / "package"
    nested.mkdir()
    (nested / "deep.py").write_text("class Deep:\n    pass\n", encoding="utf-8")

    model, summary = scan_project(tmp_path)

    assert {element.name for element in model.elements} == {"top", "Top"}
    assert summary["files_seen"] == 2
    assert summary["files_skipped_limit"] == 1


def test_scan_does_not_descend_beyond_max_depth(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("rflp_lite.adapters.project_scanner.MAX_DEPTH", 2)
    (tmp_path / "a.py").write_text("class A:\n    pass\n", encoding="utf-8")
    pkg1 = tmp_path / "pkg1"
    pkg1.mkdir()
    (pkg1 / "b.py").write_text("class B:\n    pass\n", encoding="utf-8")
    deep = pkg1 / "pkg2"
    deep.mkdir()
    (deep / "pkg3").mkdir()
    (deep / "pkg3" / "c.py").write_text("class C:\n    pass\n", encoding="utf-8")

    model, summary = scan_project(tmp_path)

    names = {element.name for element in model.elements}
    assert "A" in names and "B" in names
    assert "C" not in names and "c" not in names
    assert summary["files_seen"] == 2


def test_scan_empty_directory_raises(tmp_path: Path):
    with pytest.raises(AdapterFailure, match="没有可解析的"):
        scan_project(tmp_path)


def test_scan_without_supported_artifacts_raises(tmp_path: Path):
    (tmp_path / "readme.md").write_text("# 说明\n", encoding="utf-8")
    (tmp_path / "data.json").write_text('{"not_openapi": true}', encoding="utf-8")
    (tmp_path / "other.xml").write_text("<root><item/></root>", encoding="utf-8")
    with pytest.raises(AdapterFailure, match="没有可解析的"):
        scan_project(tmp_path)


def test_scan_missing_or_invalid_root_raises(tmp_path: Path):
    with pytest.raises(ContractViolation, match="项目目录不存在或不是目录"):
        scan_project(tmp_path / "does-not-exist")
    file_path = tmp_path / "app.py"
    file_path.write_text("class App:\n    pass\n", encoding="utf-8")
    with pytest.raises(ContractViolation, match="项目目录不存在或不是目录"):
        scan_project(file_path)


def test_scan_records_parse_errors_without_aborting(tmp_path: Path):
    (tmp_path / "broken.py").write_text("class Broken(:\n", encoding="utf-8")
    (tmp_path / "good.py").write_text("class Good:\n    pass\n", encoding="utf-8")
    (tmp_path / "bad.json").write_text("{broken", encoding="utf-8")
    (tmp_path / "bad.xml").write_text("<testsuite><testcase", encoding="utf-8")

    model, summary = scan_project(tmp_path)

    assert {element.name for element in model.elements} == {"good", "Good"}
    assert len(summary["parse_errors"]) == 3
    assert summary["parse_errors"] == tuple(sorted(summary["parse_errors"]))
    assert any(error.startswith("broken.py") for error in summary["parse_errors"])
    assert any(error.startswith("bad.json") for error in summary["parse_errors"])
    assert any(error.startswith("bad.xml") for error in summary["parse_errors"])
