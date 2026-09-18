import io
import zipfile

import pytest

from rflp_lite.adapters.documents.ocr import RapidOcrAdapter
from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.domain.errors import AdapterFailure


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
