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
