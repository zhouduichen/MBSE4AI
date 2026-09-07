from rflp_lite.repository.import_v1 import import_legacy_state
from rflp_lite.repository.sqlite import SQLiteModelRepository


def test_import_legacy_state_creates_imported_entities(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")

    diagnostics = import_legacy_state(
        repository,
        "p1",
        {"name": "旧项目", "stakeholders": [{"id": "s1", "name": "运营人员"}]},
    )

    graph = repository.load_graph("p1")
    assert graph.entities[0].id == "s1"
    assert graph.entities[0].meta.producer.value == "import"
    assert diagnostics
