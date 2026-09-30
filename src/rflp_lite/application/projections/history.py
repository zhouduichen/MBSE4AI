"""Revision, patch, run, step, audit, and readable diff projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from rflp_lite.application.projections.common import plain
from rflp_lite.domain.canonical import canonical_hash


@dataclass(frozen=True, slots=True)
class RevisionSummaryView:
    revision: int
    created_at: float | None
    actor: str
    patch_id: str | None
    run_id: str | None
    task_id: str | None
    reason: str
    added: tuple[Mapping[str, object], ...]
    updated: tuple[Mapping[str, object], ...]
    relations_added: tuple[Mapping[str, object], ...]
    relations_removed: tuple[Mapping[str, object], ...]

    def as_dict(self) -> Mapping[str, object]:
        return asdict(self)


def _snapshot(value: Mapping[str, object] | None) -> Mapping[str, object]:
    if value is None:
        return {"entities": [], "relations": []}
    raw = value.get("snapshot", value)
    return raw if isinstance(raw, Mapping) else {"entities": [], "relations": []}


def _entity_changes(before: Mapping[str, object], after: Mapping[str, object]) -> Mapping[str, object]:
    keys = ("name", "status", "producer", "confidence", "source_ids", "evidence_ids", "payload")
    changes = {key: {"before": before.get(key), "after": after.get(key)} for key in keys if before.get(key) != after.get(key)}
    return {"id": after.get("id", before.get("id")), "kind": after.get("kind", before.get("kind")), "name": after.get("name", before.get("name")), "changes": changes, "status_changed": before.get("status") != after.get("status"), "payload_changed": before.get("payload") != after.get("payload")}


def build_revision_diff(before: Mapping[str, object] | None, after: Mapping[str, object] | None, *, revision: int | None = None) -> Mapping[str, object]:
    before_snapshot, after_snapshot = _snapshot(before), _snapshot(after)
    before_entities = {str(item.get("id")): item for item in before_snapshot.get("entities", ()) if isinstance(item, Mapping)}
    after_entities = {str(item.get("id")): item for item in after_snapshot.get("entities", ()) if isinstance(item, Mapping)}
    added = tuple(after_entities[key] for key in sorted(set(after_entities) - set(before_entities)))
    deprecated = tuple(after_entities[key] for key in sorted(set(after_entities) & set(before_entities)) if after_entities[key].get("status") in {"deprecated", "rejected"} and before_entities[key].get("status") not in {"deprecated", "rejected"})
    updated = tuple(_entity_changes(before_entities[key], after_entities[key]) for key in sorted(set(after_entities) & set(before_entities)) if before_entities[key] != after_entities[key] and key not in {str(item.get("id")) for item in deprecated})
    before_relations = {str(item.get("id")): item for item in before_snapshot.get("relations", ()) if isinstance(item, Mapping)}
    after_relations = {str(item.get("id")): item for item in after_snapshot.get("relations", ()) if isinstance(item, Mapping)}
    relations_added = tuple(after_relations[key] for key in sorted(set(after_relations) - set(before_relations)))
    relations_removed = tuple(before_relations[key] for key in sorted(set(before_relations) - set(after_relations)))
    return {"revision": revision, "before_revision": before.get("sequence") if before else 0, "after_revision": after.get("sequence") if after else revision, "added_entities": list(added), "updated_entities": list(updated), "deprecated_entities": list(deprecated), "added_relations": list(relations_added), "removed_relations": list(relations_removed), "status_changes": [item for item in updated if item["status_changed"]], "payload_changes": [item for item in updated if item["payload_changed"]], "change_count": len(added) + len(updated) + len(deprecated) + len(relations_added) + len(relations_removed), "diff_hash": canonical_hash({"added": added, "updated": updated, "deprecated": deprecated, "relations_added": relations_added, "relations_removed": relations_removed})}


def build_history_view(repository, project_id: str) -> Mapping[str, object]:
    revisions = list(repository.list_revisions(project_id))
    patches = list(repository.list_patches(project_id))
    patch_by_revision = {int(item["revision"]): item for item in patches if item.get("revision") is not None}
    summaries = []
    for item in revisions:
        revision = int(item["sequence"])
        patch = patch_by_revision.get(revision, {})
        operations = patch.get("operations", [])
        added = tuple(operation.get("entity", {}) for operation in operations if operation.get("op") == "ADD")
        updated = tuple(operation for operation in operations if operation.get("op") == "UPDATE")
        relations_added = tuple(operation for operation in operations if operation.get("op") == "RELATE")
        previous = repository.load_revision(project_id, revision - 1)
        diff = build_revision_diff(previous, item, revision=revision)
        summaries.append(RevisionSummaryView(revision, item.get("created_at"), "user" if str(patch.get("task_id", "")).startswith("review.") else "system", patch.get("id"), item.get("run_id"), patch.get("task_id"), str(item.get("reason", "")), added, updated, relations_added, tuple(diff["removed_relations"])))
    runs = []
    for run in repository.list_runs(project_id):
        runs.append({"run_id": run.id, "project_id": run.project_id, "phase": run.phase, "status": run.status, "attempt": run.attempt, "methodology_version": run.methodology_version, "model_profile": run.model_profile, "provider_id": run.provider_id, "model_id": run.model_id, "execution_mode": run.execution_mode, "context_hash": run.context_hash, "task_spec_hash": run.task_spec_hash, "prompt_hash": run.prompt_hash, "input_hash": run.input_hash, "output_hash": run.output_hash, "started_at": run.started_at, "completed_at": run.completed_at, "steps": [asdict(step) for step in run.steps]})
    return {"project_id": project_id, "revisions": [item.as_dict() for item in summaries], "runs": runs, "patches": patches, "audit_events": list(repository.list_audit_events(project_id)), "metrics": {"revision_count": len(summaries), "run_count": len(runs), "patch_count": len(patches)}}
