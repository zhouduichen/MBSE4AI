from rflp_lite.domain.entities import EntityKind, make_entity
from rflp_lite.domain.model import ModelGraph
from rflp_lite.methodology.contracts import ContextBundle, Phase
from rflp_lite.methodology.tasks import tasks_for_phase
from rflp_lite.retrieval.planner import KnowledgeGap, build_gap_query


def test_gap_query_contains_entity_and_constraint_terms():
    task = tasks_for_phase(Phase.LOGICAL_PHYSICAL)[1]
    entity = make_entity(EntityKind.PHYSICAL_BLOCK, "PB-004 battery candidate", {"constraints": ["-20~50°C"], "rationale": "operating temperature"})
    context = ContextBundle("p1", task.id, 0, (entity,))

    query = build_gap_query(task, (entity,), KnowledgeGap("missing_temperature", "", "lacks operating temperature evidence"), context)

    assert "PB-004 battery candidate" in query
    assert "-20~50°C" in query
    assert "operating temperature" in query
