from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


def validate_operational(graph: ModelGraph) -> tuple[str, ...]:
    required = {EntityKind.STAKEHOLDER, EntityKind.USE_CASE, EntityKind.OPERATIONAL_SCENARIO}
    present = {item.kind for item in graph.entities}
    return tuple(sorted(kind.value for kind in required - present))
