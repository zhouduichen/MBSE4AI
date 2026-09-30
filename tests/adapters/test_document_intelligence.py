import io
import zipfile

import pytest

from rflp_lite.adapters.documents.ocr import RapidOcrAdapter
from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.domain.errors import AdapterFailure


def _pdf_with_text(text: str) -> bytes:
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET\n".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, value in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    output.extend(
        b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    )
    output.extend(
        f"trailer\n<< /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_text_document_is_parsed_into_page_aware_regions():
    parsed = LocalDocumentParser().parse("纲要.txt", "平台必须支持需求捕获\n平台支持模型导出".encode())
    assert parsed.artifact.kind == "txt"
    assert parsed.pages[0].number == 1
    assert [region.page for region in parsed.regions] == [1, 1]
    assert parsed.regions[0].locator == "paragraph-1"


def test_docx_document_is_parsed_into_structured_regions():
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>任务要求</w:t></w:r></w:p>
    <w:p><w:r><w:t>系统应在 2 秒内上报告警。</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        archive.writestr("word/document.xml", document_xml)

    parsed = LocalDocumentParser().parse("纲要.docx", content.getvalue())

    assert parsed.artifact.kind == "docx"
    assert [region.text for region in parsed.regions] == ["任务要求", "系统应在 2 秒内上报告警。"]
    assert parsed.regions[0].heading_path == ("任务要求",)


def test_pdf_hybrid_ocr_normalizes_render_pixels_and_deduplicates_text():
    class Ocr:
        def recognize(self, image, *, page):
            del image, page
            return (("System shall respond within 2 seconds.", (139, 119, 570, 154), 0.9),)

    parsed = LocalDocumentParser(ocr=Ocr()).parse(
        "outline.pdf", _pdf_with_text("System shall respond within 2 seconds.")
    )

    assert len(parsed.regions) == 1
    assert parsed.regions[0].kind == "text"
    assert parsed.regions[0].bbox[0] == pytest.approx(72.0)
    assert any(item.code == "pdf_page_hybrid_ocr" for item in parsed.diagnostics)


def test_document_parser_rejects_unsupported_and_oversized_inputs():
    parser = LocalDocumentParser()
    with pytest.raises(AdapterFailure, match="unsupported artifact"):
        parser.parse("requirements.xlsx", b"data")
    with pytest.raises(AdapterFailure, match="50 MiB"):
        parser.parse("requirements.txt", b"x" * (50 * 1024 * 1024 + 1))


def test_rapid_ocr_adapter_accepts_array_like_polygon_coordinates():
    class ArrayLike:
        def __init__(self, value):
            self.value = value

        def tolist(self):
            return self.value

    class Engine:
        def __call__(self, image):
            return ([
                (ArrayLike([
                    ArrayLike([1, 2]),
                    ArrayLike([11, 2]),
                    ArrayLike([11, 12]),
                    ArrayLike([1, 12]),
                ]), "text")
            ], None)

    assert RapidOcrAdapter(engine=Engine()).extract(object()) == (
        ("text", (1.0, 2.0, 11.0, 12.0)),
    )
