import sqlite3

import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.model import Patch, UpdateEntity
from rflp_lite.repository.sqlite import SQLiteModelRepository


def _columns(path, table):
    with sqlite3.connect(path) as connection:
        return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _count(path, table):
    with sqlite3.connect(path) as connection:
        return connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def test_legacy_core_tables_are_preserved_and_replaced(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE relations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        INSERT INTO relations VALUES ('old-rel', '{}');
        CREATE TABLE evidence (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        INSERT INTO evidence VALUES ('old-evidence', '{}');
        CREATE TABLE audit_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        INSERT INTO audit_events(kind, payload) VALUES ('old', '{}');
        """
    )
    connection.close()

    repository = SQLiteModelRepository(path)
    repository.ensure_project("p1")
    assert {"project_id", "source_id", "target_id"} <= _columns(path, "relations")
    assert {"project_id", "claim", "excerpt"} <= _columns(path, "evidence")
    assert {"project_id", "kind", "payload"} <= _columns(path, "audit_events")
    assert _count(path, "legacy_relations") == 1
    assert _count(path, "legacy_evidence") == 1
    assert _count(path, "legacy_audit_events") == 1
    repository.close()


def test_append_patch_creates_revision_and_loads_typed_graph(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1", "项目")
    entity = make_entity(EntityKind.SYSTEM, "系统")
    patch = Patch.create("p1", "system.define", (UpdateEntity("missing", {}),), "bad", 0)
    with pytest.raises(ContractViolation, match="entity not found"):
        repository.append_patch("p1", patch, 0)

    from rflp_lite.domain.model import AddEntity
    good = Patch.create("p1", "system.define", (AddEntity(entity),), "define", 0)
    revision = repository.append_patch("p1", good, 0)
    graph = repository.load_graph("p1")
    assert revision.sequence == 1
    assert graph.revision == 1
    assert graph.entities[0].kind is EntityKind.SYSTEM


def test_append_patch_rejects_stale_revision(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    from rflp_lite.domain.model import AddEntity
    first = Patch.create("p1", "define", (AddEntity(make_entity(EntityKind.SYSTEM, "系统")),), "first", 0)
    repository.append_patch("p1", first, 0)
    second = Patch.create("p1", "define", (AddEntity(make_entity(EntityKind.SYSTEM, "其他")),), "second", 0)
    with pytest.raises(ConcurrentModificationError):
        repository.append_patch("p1", second, 0)


def test_locked_entity_cannot_be_updated_in_repository(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    from rflp_lite.domain.model import AddEntity
    entity = make_entity(EntityKind.SYSTEM, "系统", status=EntityStatus.LOCKED)
    repository.append_patch("p1", Patch.create("p1", "define", (AddEntity(entity),), "first", 0), 0)
    patch = Patch.create("p1", "repair", (UpdateEntity(entity.id, {"payload": {"x": 1}}),), "repair", 1)
    with pytest.raises(ContractViolation, match="entity is locked"):
        repository.append_patch("p1", patch, 1)
