from pathlib import Path

from rflp_lite.adapters.evidence_readers import read_junit, read_openapi, read_python_ast


ROOT = Path("examples/versioned-content-service")


def test_openapi_reader_returns_internal_evidence():
    evidence = read_openapi(ROOT / "openapi.json")
    assert len(evidence) == 3
    assert {item.details[0][1] for item in evidence} == {"GET", "POST"}
    assert all(item.kind == "openapi-operation" for item in evidence)


def test_junit_reader_preserves_passing_case():
    evidence = read_junit(ROOT / "junit.xml")
    assert len(evidence) == 1
    assert evidence[0].status == "passed"
    assert "test_restore_version" in evidence[0].source


def test_python_ast_reader_extracts_symbols():
    evidence = read_python_ast(ROOT / "implementation.py")
    assert any(item.target_id == "implementation-VersionedContentService" for item in evidence)
    assert any(item.target_id == "implementation-restore_version" for item in evidence)

