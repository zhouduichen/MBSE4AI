from rflp_lite.domain.model import ModelGraph


def validate_semantic(graph: ModelGraph) -> tuple[str, ...]:
    return tuple(sorted({item.id for item in graph.entities if not item.meta.name.strip()}))
