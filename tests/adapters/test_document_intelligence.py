import pytest

from rflp_lite.adapters.document_intelligence import LocalDocumentParser
from rflp_lite.domain.errors import AdapterFailure


def test_text_document_is_parsed_into_page_aware_regions():
    parsed = LocalDocumentParser().parse("纲要.txt", "平台必须支持需求捕获\n平台支持模型导出".encode())
    assert parsed.artifact.kind == "txt"
    assert parsed.pages[0].number == 1
    assert [region.page for region in parsed.regions] == [1, 1]
    assert parsed.regions[0].locator == "paragraph-1"


def test_document_parser_rejects_unsupported_and_oversized_inputs():
    parser = LocalDocumentParser()
    with pytest.raises(AdapterFailure, match="unsupported document"):
        parser.parse("requirements.xlsx", b"data")
    with pytest.raises(AdapterFailure, match="50 MiB"):
        parser.parse("requirements.txt", b"x" * (50 * 1024 * 1024 + 1))

