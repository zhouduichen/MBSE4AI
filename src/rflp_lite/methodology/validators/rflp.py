from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


def validate_rflp(graph: ModelGraph) -> tuple[str, ...]:
    required = {EntityKind.REQUIREMENT, EntityKind.FUNCTION, EntityKind.LOGICAL_COMPONENT, EntityKind.PHYSICAL_BLOCK}
    present = {item.kind for item in graph.entities}
    return tuple(sorted(kind.value for kind in required - present))
