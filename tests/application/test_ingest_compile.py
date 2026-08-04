from pathlib import Path

from rflp_lite.application.compile import compile_claims
from rflp_lite.application.ingest import ingest_requirements


FIXTURE = Path("examples/versioned-content-service/requirements.md")


def test_markdown_ingestion_preserves_structure_and_claim_sources():
    artifact, spans = ingest_requirements(FIXTURE)
    claims = compile_claims(spans)
    assert artifact.kind == "markdown"
    assert len(spans) == len(claims) == 3
    assert all("Versioned Content Service Requirements" in span.locator for span in spans)
    assert {claim.predicate for claim in claims} == {"must", "shall"}
    assert {claim.span_id for claim in claims} == {span.id for span in spans}

