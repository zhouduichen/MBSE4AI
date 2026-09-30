from pathlib import Path

from fastapi.testclient import TestClient

from rflp_lite.domain.entities import EntityKind, EntityStatus, make_entity
from rflp_lite.domain.model import AddEntity, Patch, Relate
from rflp_lite.domain.relations import RelationPredicate
from rflp_lite.interface.web.app import create_app


def test_model_trace_returns_clickable_rflp_verification_path(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    repository = client.app.state.container.v2.repository("p1")
    requirement = make_entity(EntityKind.REQUIREMENT, "Battery shall last 8 hours", {"statement": "Battery shall last 8 hours", "obligation": "电池应持续 8 小时"}, status=EntityStatus.ACCEPTED)
    function = make_entity(EntityKind.FUNCTION, "Manage energy", status=EntityStatus.VALIDATED)
    logical = make_entity(EntityKind.LOGICAL_COMPONENT, "Energy controller", status=EntityStatus.VALIDATED)
    physical = make_entity(EntityKind.PHYSICAL_BLOCK, "Battery pack", status=EntityStatus.VALIDATED)
    scope = {
        "requirement_ids": [requirement.id],
        "function_ids": [function.id],
        "logical_component_ids": [logical.id],
        "physical_ids": [physical.id],
    }
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "Battery endurance test",
        scope,
        status=EntityStatus.VALIDATED,
    )
    validation = make_entity(
        EntityKind.VALIDATION_CASE,
        "Operator confirmation",
        scope,
        status=EntityStatus.VALIDATED,
    )
    graph = repository.load_graph("p1")
    operations = (
        AddEntity(requirement),
        AddEntity(function),
        AddEntity(logical),
        AddEntity(physical),
        AddEntity(verification),
        AddEntity(validation),
        Relate(requirement.id, RelationPredicate.SATISFIED_BY, function.id),
        Relate(function.id, RelationPredicate.ALLOCATED_TO, logical.id),
        Relate(logical.id, RelationPredicate.ALLOCATED_TO, physical.id),
        Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
        Relate(requirement.id, RelationPredicate.VALIDATED_BY, validation.id),
    )
    repository.append_patch("p1", Patch.create("p1", "test.trace", operations, "seed trace", graph.revision), graph.revision)

    response = client.get("/projects/p1/trace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 1
    assert payload["stages"] == [
        "Requirement",
        "Function",
        "Logical",
        "Physical",
        "Verification",
    ]
    path = payload["paths"][0]
    assert path["complete"] is True
    assert path["validation"]["id"] == validation.id
    assert [node["stage"] for node in path["nodes"]] == payload["stages"]
    assert path["nodes"][0]["href"].endswith(f"#entity-{requirement.id}")

    coverage = client.get("/projects/p1/coverage")
    assert coverage.status_code == 200
    assert coverage.json()["metrics"]["requirement_count"] == 1
    assert coverage.json()["rows"][0]["paths"] == [[requirement.id, function.id, logical.id, physical.id]]

    matrix = client.get("/projects/p1/traceability").json()
    row = matrix["rows"][0]
    focused = client.get(f"/projects/p1/rflp/trace/{requirement.id}").json()
    assert tuple(path["nodes"][index]["id"] for index in range(4)) == tuple([
        requirement.id,
        row["functions"][0],
        row["logical_components"][0],
        row["physical_blocks"][0],
    ])
    assert focused["selected_trace"][:4] == [
        requirement.id,
        row["functions"][0],
        row["logical_components"][0],
        row["physical_blocks"][0],
    ]

    page = client.get("/ui/projects/p1/model")
    assert page.status_code == 200
    assert "需求 → 功能 → 逻辑 → 物理 → 验证" in page.text
    assert "Battery endurance test" in page.text
    assert "Operator confirmation" in page.text


def test_model_trace_ignores_non_ready_targets_and_surfaces_scope_gaps(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / "workspaces"))
    assert client.post("/projects", json={"id": "p1"}).status_code == 200
    repository = client.app.state.container.v2.repository("p1")
    requirement = make_entity(
        EntityKind.REQUIREMENT,
        "Battery shall last 8 hours",
        {"statement": "Battery shall last 8 hours"},
        status=EntityStatus.VALIDATED,
    )
    candidate_function = make_entity(EntityKind.FUNCTION, "Candidate control")
    deprecated_function = make_entity(
        EntityKind.FUNCTION,
        "Deprecated control",
        status=EntityStatus.DEPRECATED,
    )
    verification = make_entity(
        EntityKind.VERIFICATION_CASE,
        "Stale endurance test",
        {
            "requirement_ids": [requirement.id],
            "function_ids": [],
            "logical_component_ids": [],
            "physical_ids": ["stale-physical"],
        },
        status=EntityStatus.VALIDATED,
    )
    graph = repository.load_graph("p1")
    operations = (
        AddEntity(requirement),
        AddEntity(candidate_function),
        AddEntity(deprecated_function),
        AddEntity(verification),
        Relate(requirement.id, RelationPredicate.SATISFIED_BY, candidate_function.id),
        Relate(requirement.id, RelationPredicate.SATISFIED_BY, deprecated_function.id),
        Relate(requirement.id, RelationPredicate.VERIFIED_BY, verification.id),
    )
    repository.append_patch(
        "p1",
        Patch.create("p1", "test.trace.broken", operations, "seed broken trace", graph.revision),
        graph.revision,
    )

    trace = client.get("/projects/p1/trace").json()
    path = trace["paths"][0]
    assert path["complete"] is False
    assert "Function" in path["missing"]
    assert path["nodes"][1] is None

    matrix = client.get("/projects/p1/traceability").json()
    row = matrix["rows"][0]
    assert row["status"] == "MISSING_FUNCTION"
    assert "function" in row["gaps"]
