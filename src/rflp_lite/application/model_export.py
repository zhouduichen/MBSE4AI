"""Stable text exports for the typed model graph."""

from __future__ import annotations

import json


def graph_sysml(graph) -> str:
    """Render a dependency-free, comment-preserving SysML interchange file.

    The project does not need a SysML compiler to make this export useful: the
    package wrapper is valid SysML syntax and each graph record is retained in
    deterministic JSON comments for round-tripping and inspection.
    """

    lines = ["package AI4MBSE_Model {", f"  // revision {graph.revision}"]
    for entity in graph.entities:
        lines.append(
            f"  // entity {json.dumps(entity.as_dict(), ensure_ascii=False, sort_keys=True)}"
        )
    for relation in graph.relations:
        payload = {
            "id": relation.id,
            "source_id": relation.source_id,
            "predicate": relation.predicate.value,
            "target_id": relation.target_id,
        }
        lines.append(
            f"  // relation {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"
