from pathlib import Path


def test_product_docs_define_single_model_truth():
    text = Path("PRODUCT.md").read_text(encoding="utf-8")
    assert "ModelGraph" in text
    assert "ModelGraph 是模型唯一真源" in text
    assert "四阶段方法论" in text
