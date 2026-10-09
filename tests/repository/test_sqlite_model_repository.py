import sqlite3

import pytest

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.errors import ConcurrentModificationError, ContractViolation
from rflp_lite.domain.model import AddEntity, Patch, Relate, UpdateEntity
from rflp_lite.domain.relations import RelationPredicate
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

    good = Patch.create("p1", "system.define", (AddEntity(entity),), "define", 0)
    revision = repository.append_patch("p1", good, 0)
    graph = repository.load_graph("p1")
    assert revision.sequence == 1
    assert graph.revision == 1
    assert graph.entities[0].kind is EntityKind.SYSTEM


def test_append_patch_materializes_referenced_evidence_in_same_revision(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.save_evidence(
        "p1",
        {
            "id": "evidence-requirement",
            "source_type": "document_region",
            "source_id": "spec-1",
            "locator": "page-4",
            "claim": "续航要求",
            "excerpt": "系统续航应达到 8 小时",
            "relevance": 0.98,
        },
    )
    repository.save_evidence(
        "p1",
        {
            "id": "evidence-relation",
            "source_type": "test",
            "source_id": "test-1",
            "locator": "result-1",
            "claim": "功能满足需求",
            "excerpt": "测试结果满足需求目标",
            "relevance": 1.0,
        },
    )
    function = make_entity(EntityKind.FUNCTION, "管理续航")
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "续航要求",
        evidence_ids=("evidence-requirement",),
    )
    patch = Patch.create(
        "p1",
        "requirement.define",
        (
            AddEntity(function),
            AddEntity(requirement),
            Relate(
                requirement.id,
                RelationPredicate.SATISFIED_BY,
                function.id,
                ("evidence-relation",),
            ),
        ),
        "define requirement with evidence",
        0,
    )

    revision = repository.append_patch("p1", patch, 0)

    graph = repository.load_graph("p1")
    evidence = {
        item.id: item
        for item in graph.entities
        if item.kind is EntityKind.EVIDENCE
    }
    assert revision.sequence == graph.revision == 1
    assert set(evidence) == {"evidence-requirement", "evidence-relation"}
    assert evidence["evidence-requirement"].payload["excerpt"] == "系统续航应达到 8 小时"
    assert evidence["evidence-requirement"].meta.created_revision == 1
    assert evidence["evidence-relation"].meta.updated_revision == 1
    assert len([item for item in graph.entities if item.kind is EntityKind.EVIDENCE]) == 2
    audit = repository.list_audit_events("p1")[-1]
    assert audit["payload"]["materialized_evidence_ids"] == [
        "evidence-relation",
        "evidence-requirement",
    ]


def test_unreferenced_evidence_stays_external_until_a_model_patch_references_it(tmp_path):
    repository = SQLiteModelRepository(tmp_path / "model.db")
    repository.ensure_project("p1")
    repository.save_evidence(
        "p1",
        {
            "id": "evidence-unattached",
            "source_type": "search",
            "claim": "未绑定证据",
            "excerpt": "检索结果",
        },
    )

    assert repository.load_graph("p1").entities == ()
    assert repository.load_graph("p1").revision == 0


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
