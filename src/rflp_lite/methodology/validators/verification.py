from rflp_lite.domain.entities import EntityKind, EntityStatus
from rflp_lite.domain.model import ModelGraph


def validate_verification(graph: ModelGraph) -> tuple[str, ...]:
    requirements = {item.id for item in graph.entities if item.kind is EntityKind.REQUIREMENT and item.meta.status is EntityStatus.ACCEPTED}
    verified = {item.id for item in graph.entities if item.kind is EntityKind.VERIFICATION_CASE}
    linked = {relation.source_id for relation in graph.relations if relation.target_id in verified}
    return tuple(sorted(requirements - linked))
