from pathlib import Path

from rflp_lite.application.compile import compile_claims
from rflp_lite.application.ingest import ingest_requirements
from rflp_lite.application.requirements_workbench import analyze_artifact
from rflp_lite.bootstrap.container import build_container


FIXTURE = Path("examples/versioned-content-service/requirements.md")


def test_markdown_ingestion_preserves_structure_and_claim_sources():
    artifact, spans = ingest_requirements(FIXTURE)
    claims = compile_claims(spans)
    assert artifact.kind == "markdown"
    assert len(spans) == len(claims) == 3
    assert all("Versioned Content Service Requirements" in span.locator for span in spans)
    assert {claim.predicate for claim in claims} == {"must", "shall"}
    assert {claim.span_id for claim in claims} == {span.id for span in spans}


def test_artifact_analysis_accepts_explicit_dependencies():
    dependencies = build_container(Path.cwd()).dependencies

    state = analyze_artifact(
        "requirements.txt",
        "系统应支持备份。".encode(),
        dependencies=dependencies,
    )

    assert state["artifact"]["path"] == "requirements.txt"
    assert state["spans"]
    assert state["spans"][0]["text"] == "系统应支持备份。"
