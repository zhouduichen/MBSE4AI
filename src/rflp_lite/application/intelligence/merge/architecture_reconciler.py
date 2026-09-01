"""Architecture-specific candidate reconciliation."""

from __future__ import annotations

from rflp_lite.application.intelligence.identity import ensure_entity_metadata
from rflp_lite.application.intelligence.merge.common import (
    State,
    _all_ids,
    _architecture_bucket,
    _filter_relations,
    _label,
    _mapped_id,
    _new_item,
    _source_aliases,
)
from rflp_lite.domain.canonical import canonical_json


def merge_architecture_items(
    result: State, raw_items: list[State], input_hash: str, block_id: str
) -> None:
    discovery = dict(result.get("discovery") or {})
    architecture = dict(discovery.get("architecture") or {})
    valid_ids = _all_ids(result)
    generated_nodes: list[tuple[State, State, str]] = []
    aliases: dict[str, str] = _source_aliases(result)
    relation_items: list[State] = []
    for raw in raw_items:
        bucket = _architecture_bucket(raw)
        if bucket is None:
            relation_items.append(raw)
            continue
        name = _label(raw, "name", "title", "function", "component", "description")
        if not name:
            continue
        payload = {
            key: value
            for key, value in raw.items()
            if key not in {"id", "relations", "source_region_ids", "source_regions"}
        }
        payload["name"] = name
        node = _new_item(result, block_id, raw, payload, name)
        generated_nodes.append((raw, node, bucket))
        if str(raw.get("id", "")).strip():
            aliases.setdefault(str(raw["id"]).strip(), str(node["id"]))
        aliases.setdefault(str(node["id"]), str(node["id"]))
    valid_ids.update(str(node["id"]) for _, node, _ in generated_nodes)
    for bucket in ("functions", "logical_components", "physical_components", "interfaces"):
        entries = architecture.get(bucket, ())
        iterable = entries if isinstance(entries, (list, tuple)) else ()
        # Keep all prior candidates.  Reanalysis is additive; only a human
        # deletion may remove an architectural candidate from the workbench.
        architecture[bucket] = [
            ensure_entity_metadata(
                {
                    "functions": "function",
                    "logical_components": "logical_component",
                    "physical_components": "physical_component",
                    "interfaces": "interface",
                }[bucket],
                item,
            )
            for item in iterable
            if isinstance(item, dict)
        ]
    for raw, node, bucket in generated_nodes:
        entity_type = {
            "functions": "function",
            "logical_components": "logical_component",
            "physical_components": "physical_component",
            "interfaces": "interface",
        }[bucket]
        cleaned = ensure_entity_metadata(
            entity_type,
            _filter_relations(node, aliases, valid_ids),
            editor="llm",
        )
        architecture.setdefault(bucket, [])
        current = list(architecture[bucket]) if isinstance(architecture[bucket], list) else []
        target = next(
            (
                item
                for item in current
                if str(item.get("id", "")) == str(cleaned.get("id", ""))
                or (
                    str(item.get("name", "")).strip().casefold()
                    and str(item.get("name", "")).strip().casefold()
                    == str(cleaned.get("name", "")).strip().casefold()
                )
            ),
            None,
        )
        if target is None:
            current.append(cleaned)
            target = cleaned
        else:
            sources = dict(target.get("field_sources") or {})
            changed = False
            for field, value in cleaned.items():
                if field in {
                    "id",
                    "revision",
                    "last_editor",
                    "field_sources",
                    "match_keys",
                    "identity_hash",
                    "suggested_changes",
                    "review_hint",
                    "source_item_id",
                    "producer",
                    "analysis_block_id",
                    "analysis_input_hash",
                } or value in (None, "", [], {}):
                    continue
                if target.get(field) == value:
                    continue
                if sources.get(field) in {"user", "rule"}:
                    pending = list(target.get("suggested_changes") or [])
                    suggestion = {
                        "field": field,
                        "current": target.get(field),
                        "suggested": value,
                        "block_id": block_id,
                        "input_hash": input_hash,
                    }
                    if suggestion not in pending:
                        pending.append(suggestion)
                    target["suggested_changes"] = pending
                    continue
                target[field] = value
                sources[field] = "llm"
                changed = True
            target["field_sources"] = sources
            if changed:
                target["revision"] = int(target.get("revision", 1)) + 1
                target["last_editor"] = "llm"
        target_id = str(target.get("id", ""))
        if str(raw.get("id", "")).strip() and target_id:
            aliases[str(raw["id"]).strip()] = target_id
        architecture[bucket] = current
        for relation in (raw.get("relations", ()) if isinstance(raw.get("relations"), list) else ()):
            if isinstance(relation, dict):
                relation_items.append(relation)
    relations = [
        dict(item)
        for item in architecture.get("relations", ())
        if isinstance(item, dict)
    ]
    for relation in relation_items:
        source_id = _mapped_id(relation.get("source_id"), aliases, valid_ids)
        target_id = _mapped_id(relation.get("target_id"), aliases, valid_ids)
        if source_id and target_id:
            relations.append(
                {
                    "source_id": source_id,
                    "predicate": str(relation.get("predicate", "relatedTo")),
                    "target_id": target_id,
                    "producer": "llm",
                    "analysis_block_id": block_id,
                    "analysis_input_hash": input_hash,
                }
            )
    architecture["relations"] = sorted(
        {canonical_json(item): item for item in relations}.values(),
        key=lambda item: (
            str(item.get("source_id", "")),
            str(item.get("predicate", "")),
            str(item.get("target_id", "")),
        ),
    )
    for bucket in ("functions", "logical_components", "physical_components", "interfaces"):
        architecture[bucket] = sorted(
            [item for item in architecture.get(bucket, ()) if isinstance(item, dict)],
            key=lambda item: (str(item.get("name", "")), str(item.get("id", ""))),
        )
    architecture["block_id"] = block_id
    discovery["architecture"] = architecture
    result["discovery"] = discovery

