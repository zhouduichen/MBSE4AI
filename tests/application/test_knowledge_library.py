import pytest

from rflp_lite.application.knowledge_library import import_requirement_history


def test_history_requires_id_and_statement():
    with pytest.raises(ValueError):
        import_requirement_history([{"id": "h-1"}], "history", "1")
