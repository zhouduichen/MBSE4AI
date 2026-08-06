import io
import zipfile

from rflp_lite.adapters.readers import read_artifact

_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(body: str) -> bytes:
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_NS}"><w:body>{body}</w:body></w:document>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_docx_paragraphs_are_captured():
    content = _docx(
        "<w:p><w:r><w:t>审计人员必须查看恢复记录。</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>管理员必须恢复历史版本。</w:t></w:r></w:p>"
    )
    _, spans = read_artifact("req.docx", content)
    texts = [span.text for span in spans]
    assert "审计人员必须查看恢复记录。" in texts
    assert "管理员必须恢复历史版本。" in texts


def test_docx_table_row_is_captured_as_single_span():
    content = _docx(
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>REQ-1</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>The service must save each content version.</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "</w:tbl>"
    )
    artifact, spans = read_artifact("req.docx", content)
    texts = [span.text for span in spans]
    assert any(
        "REQ-1" in text and "must save each content version" in text for text in texts
    )
    assert artifact.id.startswith("artifact-")


def test_docx_table_text_is_not_duplicated_as_plain_paragraph():
    content = _docx(
        "<w:tbl>"
        "<w:tr>"
        "<w:tc><w:p><w:r><w:t>only-in-table</w:t></w:r></w:p></w:tc>"
        "</w:tr>"
        "</w:tbl>"
    )
    _, spans = read_artifact("req.docx", content)
    texts = [span.text for span in spans]
    assert texts.count("only-in-table") == 1