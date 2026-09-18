import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.interface.web.app import create_app


def _single_page_pdf(lines: tuple[str, ...]) -> bytes:
    stream = b"BT\n/F1 11 Tf\n72 720 Td\n" + b"\n".join(
        f"({escaped}) Tj\n0 -18 Td".encode("ascii")
        for line in lines
        for escaped in (line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"),)
    ) + b"\nET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode("ascii"))
        document.extend(value)
        document.extend(b"\nendobj\n")
    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(document)


def _docx_document(lines: tuple[str, ...]) -> bytes:
    paragraphs = "".join(
        f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body></w:document>"
    )
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return content.getvalue()


def test_document_to_requirements_behavior_and_traceability(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "mission"}).status_code == 200
    source = Path(__file__).parent.parent / "fixtures" / "requirements_use_case_acceptance.txt"

    uploaded = client.post(
        "/projects/mission/documents",
        files={"file": (source.name, source.read_bytes(), "text/plain")},
    )
    assert uploaded.status_code == 200
    document_id = uploaded.json()["document"]["document_id"]

    draft_response = client.post(
        "/projects/mission/requirements-use-case/draft",
        json={"document_ids": [document_id]},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["draft"]
    assert len(draft["requirements"]) >= 3
    assert draft["use_cases"]
    assert draft["scenarios"]
    assert draft["system_context"]["attributes"]["platform_type"] == "generic_system"
    assert any(item["kind"] == "stakeholder" for item in draft["entities"])
    assert all(
        item["source_refs"] or item["confidence"] < 1
        for item in draft["requirements"]
    )

    applied = client.post(
        "/projects/mission/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    assert applied.json()["apply"]["created_entity_count"] >= 6
    model_after_apply = client.get("/projects/mission/model").json()
    system = next(item for item in model_after_apply["entities"] if item["kind"] == "system")
    assert system["payload"]["attributes"]["platform_type"] == "generic_system"
    assert any(item["kind"] == "stakeholder" for item in model_after_apply["entities"])
    assert any(
        item["payload"].get("inferred_constraints")
        for item in model_after_apply["entities"]
        if item["kind"] == "requirement"
    )

    model = model_after_apply
    candidates = [item for item in model["entities"] if item["kind"] == "requirement"]
    assert len(candidates) >= 3
    accepted = client.post(
        f"/projects/mission/entities/{candidates[0]['id']}/accept",
        json={"expected_revision": model["revision"]},
    )
    assert accepted.status_code == 200
    edited = client.post(
        f"/projects/mission/entities/{candidates[1]['id']}/edit",
        json={
            "expected_revision": accepted.json()["revision"]["sequence"],
            "statement": "系统应记录每次任务的时间、位置和告警状态",
        },
    )
    assert edited.status_code == 200

    behavior = client.get("/projects/mission/behavior")
    assert behavior.status_code == 200
    assert behavior.json()["behavior"]["use_cases"]

    traceability = client.get("/projects/mission/traceability")
    assert traceability.status_code == 200
    assert traceability.json()["traceability"]["rows"]


def test_pdf_document_reaches_structured_requirements_and_modelgraph(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "pdf-mission"}).status_code == 200
    content = _single_page_pdf(
        (
            "The system latency shall be no more than 2 seconds.",
            "The operator shall receive an alarm.",
            "The system shall keep an audit trail.",
        )
    )

    uploaded = client.post(
        "/projects/pdf-mission/documents",
        files={"file": ("brief.pdf", content, "application/pdf")},
    )
    assert uploaded.status_code == 200
    document = uploaded.json()["document"]
    assert document["name"] == "brief.pdf"
    assert document["region_count"] == 3
    document_id = document["document_id"]

    draft_response = client.post(
        "/projects/pdf-mission/requirements-use-case/draft",
        json={"document_ids": [document_id]},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["draft"]
    assert len(draft["requirements"]) == 3
    assert any(
        constraint["field"] == "latency_ms"
        and constraint["operator"] == "max"
        and constraint["value"] == 2000.0
        for requirement in draft["requirements"]
        for constraint in requirement["constraints"]
    )
    assert any(item["name"] == "操作员" for item in draft["entities"])
    assert all(item["source_refs"] for item in draft["requirements"])
    assert len({item["source_refs"][0] for item in draft["requirements"]}) == 3

    applied = client.post(
        "/projects/pdf-mission/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    model = client.get("/projects/pdf-mission/model").json()
    requirements = [item for item in model["entities"] if item["kind"] == "requirement"]
    assert len(requirements) == 3
    assert any(
        item["payload"].get("constraints", {}).get("max_latency_ms") == 2000.0
        for item in requirements
    )
    assert any(item["kind"] == "use_case" for item in model["entities"])
    assert any(item["kind"] == "activity" for item in model["entities"])


def test_docx_document_reaches_structured_requirements_and_modelgraph(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "docx-mission"}).status_code == 200
    content = _docx_document(
        (
            "The system shall provide a status report.",
            "The system latency shall be no more than 3 seconds.",
            "The operator shall receive an alarm.",
        )
    )

    uploaded = client.post(
        "/projects/docx-mission/documents",
        files={"file": ("brief.docx", content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert uploaded.status_code == 200
    document = uploaded.json()["document"]
    assert document["name"] == "brief.docx"
    assert document["region_count"] == 3

    draft_response = client.post(
        "/projects/docx-mission/requirements-use-case/draft",
        json={"document_ids": [document["document_id"]]},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["draft"]
    assert len(draft["requirements"]) == 3
    assert all(item["source_refs"] for item in draft["requirements"])
    assert len({item["source_refs"][0] for item in draft["requirements"]}) == 3
    assert any(
        constraint["field"] == "latency_ms"
        and constraint["operator"] == "max"
        and constraint["value"] == 3000.0
        for requirement in draft["requirements"]
        for constraint in requirement["constraints"]
    )

    applied = client.post(
        "/projects/docx-mission/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    model = client.get("/projects/docx-mission/model").json()
    assert len([item for item in model["entities"] if item["kind"] == "requirement"]) == 3
    assert any(item["kind"] == "use_case" for item in model["entities"])


def test_text_intake_persists_bounded_concern_attributes(tmp_path: Path):
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "profile"}).status_code == 200

    response = client.post(
        "/projects/profile/requirements-use-case/draft",
        json={
            "text": "校园无人配送机器人由操作员使用，维护人员负责维护，系统应故障安全并支持持续运行"
        },
    )
    assert response.status_code == 200
    draft = response.json()["draft"]
    assert draft["system_context"]["attributes"]["platform_type"] == "robot"
    assert {item["name"] for item in draft["entities"]} >= {
        "操作员",
        "维护人员",
        "安全性",
        "可靠性",
        "可维护性",
    }
    assert all(item["confidence"] < 0.5 for item in draft["entities"])

    applied = client.post(
        "/projects/profile/requirements-use-case/apply",
        json={"draft_id": draft["draft_id"]},
    )
    assert applied.status_code == 200
    model = client.get("/projects/profile/model").json()
    system = next(item for item in model["entities"] if item["kind"] == "system")
    assert system["payload"]["attributes"]["platform_type"] == "robot"
    assert any(item["kind"] == "concern" for item in model["entities"])
