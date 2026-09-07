from rflp_lite.domain.entities import EntityKind
from rflp_lite.domain.model import ModelGraph


def validate_functional(graph: ModelGraph) -> tuple[str, ...]:
    return () if any(item.kind is EntityKind.FUNCTION for item in graph.entities) else ("missing_function",)
