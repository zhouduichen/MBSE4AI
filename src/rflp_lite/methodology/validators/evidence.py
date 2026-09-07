from rflp_lite.domain.model import ModelGraph


def validate_evidence(graph: ModelGraph) -> tuple[str, ...]:
    return tuple(
        relation.id for relation in graph.relations
        if relation.evidence_ids and any(not evidence_id.strip() for evidence_id in relation.evidence_ids)
    )
