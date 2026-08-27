# Incremental Requirements Reanalysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically reconcile new requirements into complete stakeholder, Concern/Need, scenario, and RFLP/MBSE coverage while preserving editable human values, reserving deletion for explicit human actions, and supporting idempotent full-project reanalysis.

**Architecture:** Keep the current Workbench JSON, SQLite repository, six strict LLM blocks, and local JobService. Add deterministic identity, snapshot, coverage, and reconciliation services between LLM output and Workbench persistence; bind every job to a content revision that changes only for requirement/human writes, while retaining the repository revision for audit. Route all automated changes through the reconciler. Add asynchronous full reanalysis plus recoverable human deletion without introducing a new database or runtime service.

**Tech Stack:** Python 3.12, FastAPI, Jinja2/HTMX, SQLite, dataclasses, JSON Schema/jsonschema, pytest, existing OpenAI-compatible/Ollama adapter.

## Global Constraints

- Every new requirement automatically triggers stakeholder, Concern/Need, scenario, requirement, and architecture analysis.
- All content remains editable; do not add a hard-lock field or immutable user-facing state.
- A later LLM result must not silently overwrite a field whose latest editor is the user.
- A later LLM result must not silently overwrite an explicit source/rule field; disagreement becomes a suggestion just like a human-field disagreement.
- LLM, rule, and background-job paths must not delete entities or relations.
- Only an explicit human delete command may remove current content, and it must create a recoverable deletion record.
- A manually deleted identity must not be recreated automatically; it may only produce a review hint until a human restores it.
- “重新分析全部需求” must run all six analysis blocks against the latest effective requirements.
- Repeated analysis of one revision must be idempotent and must not duplicate entities or relations.
- No input source may be silently omitted because the project exceeds the old 24-region or 32-requirement caps.
- Preserve workspace isolation, strict response schemas, provenance, and existing partial-failure behavior.
- Reuse Workbench JSON, SQLiteRepository, JobService, and existing model adapters; add no vector database, queue service, or workflow dependency.

## File Structure

New focused modules:

- `src/rflp_lite/application/intelligence/identity.py` — normalized labels, stable match keys, aliases, and metadata migration.
- `src/rflp_lite/application/intelligence/reconciliation.py` — the only automated merge boundary; applies field-source precedence, suggestions, suppression, and summaries.
- `src/rflp_lite/application/intelligence/project_snapshot.py` — compact immutable analysis snapshots and complete source batching.
- `src/rflp_lite/application/intelligence/coverage_audit.py` — deterministic stakeholder/scenario/trace coverage gaps.
- `src/rflp_lite/application/use_cases/reanalyze_requirements.py` — incremental, coverage-audit, and full-reanalysis orchestration.
- `src/rflp_lite/application/entity_deletion.py` — delete preview, transactional deletion plan, deletion registry, and restore policy.

Existing modules to change:

- `src/rflp_lite/application/requirements_workbench.py` — initialize metadata and record user edits.
- `src/rflp_lite/application/intelligence/block_schemas.py` — allow only the five approved operations and reject delete-like actions.
- `src/rflp_lite/application/intelligence/analysis_blocks.py` — build requests from snapshots and delegate merges to reconciliation.
- `src/rflp_lite/application/intelligence/enrichment_jobs.py` — analysis modes, source batches, revision guards, summaries, and superseded jobs.
- `src/rflp_lite/application/jobs.py` — durable `superseded` state and active-job idempotency.
- `src/rflp_lite/application/use_cases/requirements_analysis.py` — submit automatic incremental analysis with delta source IDs.
- `src/rflp_lite/application/scenarios.py` — record user field sources and preserve edited scenarios.
- `src/rflp_lite/application/web_facade.py` — narrow facade methods for reanalysis, entity editing, deletion preview/delete/restore.
- `src/rflp_lite/interface/web/routes.py` and `api_v1.py` — Web and JSON endpoints.
- `src/rflp_lite/interface/web/templates/requirements-input.html`, `requirements-overview.html`, `requirements-stakeholders.html`, and `requirements-scenarios.html` — progress, full reanalysis, editing, delete preview, suggestions, and restore UI.
- `src/rflp_lite/interface/web/presenters.py` — analysis and deletion view models.

The implementation is one dependent vertical feature, split below into independently reviewable increments. Do not implement later UI tasks before the identity and reconciliation contracts they consume.

---

### Task 1: Stable Identity and Backward-Compatible Metadata

**Files:**
- Create: `src/rflp_lite/application/intelligence/identity.py`
- Modify: `src/rflp_lite/application/requirements_workbench.py` in `analyze_artifact`, `empty_workbench`, `merge_artifact`, and `restore_legacy_requirements`
- Test: `tests/application/intelligence/test_identity.py`
- Test: `tests/application/test_requirements_workbench.py`

**Interfaces:**
- Consumes: `canonical_hash` and `canonical_json` from `rflp_lite.domain.canonical`.
- Produces: `normalize_label(value: object) -> str`, `label_similarity(left: object, right: object) -> float`, `entity_match_keys(entity_type: str, item: Mapping[str, object]) -> tuple[str, ...]`, `ensure_entity_metadata(entity_type: str, item: Mapping[str, object], *, editor: str | None = None) -> dict[str, object]`, `ensure_workbench_metadata(state: dict[str, object]) -> dict[str, object]`, and `advance_content_revision(state: dict[str, object]) -> dict[str, object]`.

- [ ] **Step 1: Write failing stable-identity and migration tests**

```python
from rflp_lite.application.intelligence.identity import (
    ensure_entity_metadata,
    ensure_workbench_metadata,
    entity_match_keys,
    label_similarity,
)


def test_stakeholder_match_key_does_not_depend_on_input_hash() -> None:
    first = ensure_entity_metadata(
        "stakeholder",
        {"id": "st-1", "name": " 运维人员 ", "category": "operator"},
        editor="llm",
    )
    second = ensure_entity_metadata(
        "stakeholder",
        {"id": "st-2", "name": "运维人员", "category": "operator"},
        editor="llm",
    )
    assert entity_match_keys("stakeholder", first) == entity_match_keys("stakeholder", second)
    assert first["match_keys"] == ["stakeholder:operator:运维人员"]
    assert label_similarity("系统运维人员", "运维人员") >= 0.95


def test_legacy_workbench_gets_lightweight_metadata_without_changing_ids() -> None:
    state = {
        "revision": 4,
        "stakeholders": [{"id": "st-1", "name": "管理员", "category": "operator"}],
        "concerns": [],
        "needs": [],
        "claims": [],
        "structured_requirements": [],
        "scenarios": [],
    }
    migrated = ensure_workbench_metadata(state)
    assert migrated["stakeholders"][0]["id"] == "st-1"
    assert migrated["stakeholders"][0]["revision"] == 1
    assert migrated["stakeholders"][0]["field_sources"]["name"] == "rule"
    assert migrated["content_revision"] == 4
    assert migrated["deletion_registry"] == []
```

- [ ] **Step 2: Run the new tests and verify the missing module failure**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_identity.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: rflp_lite.application.intelligence.identity`.

- [ ] **Step 3: Implement normalized match keys and metadata migration**

Create `identity.py` with these complete public functions and private group mapping:

```python
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping

from rflp_lite.domain.canonical import canonical_hash, canonical_json


_GROUP_TYPES = {
    "stakeholders": "stakeholder",
    "concerns": "concern",
    "needs": "need",
    "claims": "requirement",
    "structured_requirements": "requirement",
    "scenarios": "scenario",
}


def normalize_label(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s\-_—–，。；：、,.!！?？:;]+", "", text)


def label_similarity(left: object, right: object) -> float:
    first, second = normalize_label(left), normalize_label(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    shorter, longer = sorted((first, second), key=len)
    if len(shorter) >= 4 and shorter in longer:
        return 0.96
    left_pairs = {first[index:index + 2] for index in range(max(1, len(first) - 1))}
    right_pairs = {second[index:index + 2] for index in range(max(1, len(second) - 1))}
    return (2.0 * len(left_pairs & right_pairs)) / (len(left_pairs) + len(right_pairs))


def entity_match_keys(entity_type: str, item: Mapping[str, object]) -> tuple[str, ...]:
    aliases = item.get("aliases", ())
    alias_values = aliases if isinstance(aliases, (list, tuple)) else ()
    if entity_type == "stakeholder":
        category = normalize_label(item.get("category", "other")) or "other"
        labels = [item.get("name", ""), *alias_values]
        return tuple(sorted({f"stakeholder:{category}:{normalize_label(label)}" for label in labels if normalize_label(label)}))
    if entity_type == "concern":
        return (f"concern:{item.get('stakeholder_id', '')}:{normalize_label(item.get('name', ''))}",)
    if entity_type == "need":
        return (f"need:{item.get('stakeholder_id', '')}:{normalize_label(item.get('statement', ''))}",)
    if entity_type == "scenario":
        actors = ",".join(sorted(normalize_label(value) for value in item.get("actors", ()) if normalize_label(value)))
        objective = normalize_label(item.get("title", item.get("description", "")))
        return (f"scenario:{normalize_label(item.get('scenario_type', 'normal'))}:{actors}:{objective}",)
    statement = normalize_label(item.get("statement", item.get("object", item.get("name", ""))))
    return (f"{entity_type}:{statement}",) if statement else ()


def ensure_entity_metadata(
    entity_type: str,
    item: Mapping[str, object],
    *,
    editor: str | None = None,
) -> dict[str, object]:
    result = json.loads(canonical_json(dict(item)))
    source = str(editor or result.get("last_editor") or result.get("producer") or "rule")
    result.setdefault("revision", 1)
    result.setdefault("last_editor", source)
    result.setdefault("aliases", [])
    result.setdefault("source_requirement_ids", list(result.get("requirement_ids", ())))
    result.setdefault("suggested_changes", [])
    result.setdefault("review_hint", "")
    result.setdefault("match_keys", list(entity_match_keys(entity_type, result)))
    fields = dict(result.get("field_sources") or {})
    for key in result:
        if key not in {"field_sources", "suggested_changes", "match_keys", "aliases"}:
            fields.setdefault(key, source)
    result["field_sources"] = fields
    if not result.get("identity_hash"):
        result["identity_hash"] = canonical_hash((entity_type, result["match_keys"]))
    if not result.get("id"):
        result["id"] = f"{entity_type}-{str(result['identity_hash'])[:12]}"
    return result


def ensure_workbench_metadata(state: dict[str, object]) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    result.setdefault("content_revision", int(result.get("revision", 0)))
    result.setdefault("deletion_registry", [])
    result.setdefault("analysis_summary", {})
    for group, entity_type in _GROUP_TYPES.items():
        result[group] = [
            ensure_entity_metadata(entity_type, item)
            for item in result.get(group, ())
            if isinstance(item, dict)
        ]
    return result


def advance_content_revision(state: dict[str, object]) -> dict[str, object]:
    result = ensure_workbench_metadata(state)
    result["content_revision"] = int(result.get("content_revision", 0)) + 1
    return result
```

Call `ensure_workbench_metadata` before returning newly analyzed, empty, merged, or legacy-restored workbenches. Do not change existing IDs. `content_revision` is not the SQLite revision: requirement submission, human edit, human delete, and restore call `advance_content_revision` once before persistence; LLM/rule reconciliation and Job progress saves preserve it unchanged. This distinction prevents a multi-block Job from superseding itself after its first save.

- [ ] **Step 4: Run identity and workbench regression tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_identity.py tests/application/test_requirements_workbench.py -q`

Expected: PASS with no changed assertions for existing IDs, claim counts, or merge behavior.

- [ ] **Step 5: Commit the identity increment**

```bash
git add src/rflp_lite/application/intelligence/identity.py src/rflp_lite/application/requirements_workbench.py tests/application/intelligence/test_identity.py tests/application/test_requirements_workbench.py
git commit -m "feat: add stable analysis entity identity"
```

---

### Task 2: Deterministic Reconciliation and Human Field Precedence

**Files:**
- Create: `src/rflp_lite/application/intelligence/reconciliation.py`
- Test: `tests/application/intelligence/test_reconciliation.py`

**Interfaces:**
- Consumes: identity functions from Task 1 and canonical Workbench groups.
- Produces: `ReconcileSummary`, `accumulate_summary(state, summary)`, `reconcile_entities(state: dict[str, object], group: str, incoming: tuple[dict[str, object], ...], *, block_id: str, input_hash: str) -> tuple[dict[str, object], ReconcileSummary]`, and `reconcile_relations(state: dict[str, object], incoming: tuple[dict[str, object], ...], *, block_id: str, input_hash: str) -> tuple[dict[str, object], ReconcileSummary]`.

- [ ] **Step 1: Write failing tests for idempotency, human precedence, suggestions, and deletion suppression**

```python
from rflp_lite.application.intelligence.reconciliation import reconcile_entities


def _state() -> dict[str, object]:
    return {
        "stakeholders": [{
            "id": "st-1",
            "name": "现场管理员",
            "category": "operator",
            "goals": ["稳定运行"],
            "aliases": ["管理员"],
            "match_keys": ["stakeholder:operator:管理员"],
            "field_sources": {"name": "user", "goals": "llm"},
            "revision": 2,
            "suggested_changes": [],
        }],
        "deletion_registry": [],
    }


def test_reconcile_preserves_user_value_and_updates_machine_field() -> None:
    state, summary = reconcile_entities(
        _state(),
        "stakeholders",
        ({"name": "管理员", "category": "operator", "goals": ["安全运行"]},),
        block_id="stakeholders",
        input_hash="hash-2",
    )
    item = state["stakeholders"][0]
    assert item["name"] == "现场管理员"
    assert item["goals"] == ["安全运行"]
    assert item["suggested_changes"][0]["field"] == "name"
    assert summary.updated == 1


def test_reconcile_is_idempotent_and_respects_human_deletion() -> None:
    state = _state()
    incoming = ({"name": "管理员", "category": "operator", "goals": []},)
    once, _ = reconcile_entities(state, "stakeholders", incoming, block_id="stakeholders", input_hash="h")
    twice, _ = reconcile_entities(once, "stakeholders", incoming, block_id="stakeholders", input_hash="h")
    assert len(twice["stakeholders"]) == 1
    twice["stakeholders"] = []
    twice["deletion_registry"] = [{"entity_type": "stakeholder", "match_keys": ["stakeholder:operator:管理员"]}]
    suppressed, summary = reconcile_entities(twice, "stakeholders", incoming, block_id="stakeholders", input_hash="h2")
    assert suppressed["stakeholders"] == []
    assert suppressed["analysis_review_hints"][0]["operation"] == "upsert_entity"
    assert summary.suppressed == 1


def test_propose_change_never_overwrites_even_a_machine_field() -> None:
    state, _ = reconcile_entities(
        _state(),
        "stakeholders",
        ({
            "operation": "propose_change",
            "target_id": "st-1",
            "name": "现场管理员",
            "category": "operator",
            "goals": ["建议目标"],
        },),
        block_id="stakeholders",
        input_hash="hash-3",
    )
    assert state["stakeholders"][0]["goals"] == ["稳定运行"]
    assert state["stakeholders"][0]["suggested_changes"][-1]["suggested"] == ["建议目标"]


def test_llm_conflict_with_explicit_rule_field_becomes_suggestion() -> None:
    state = _state()
    state["stakeholders"][0]["field_sources"]["name"] = "rule"
    reconciled, _ = reconcile_entities(
        state,
        "stakeholders",
        ({
            "operation": "enrich_fields",
            "target_id": "st-1",
            "name": "模型改名",
            "category": "operator",
        },),
        block_id="stakeholders",
        input_hash="hash-4",
    )
    assert reconciled["stakeholders"][0]["name"] == "现场管理员"
    assert reconciled["stakeholders"][0]["suggested_changes"][-1]["suggested"] == "模型改名"


def test_unique_high_similarity_role_reuses_stable_id() -> None:
    state = {
        "stakeholders": [{
            "id": "st-operator",
            "name": "运维人员",
            "category": "operator",
            "field_sources": {"name": "rule"},
        }],
        "deletion_registry": [],
    }
    reconciled, _ = reconcile_entities(
        state,
        "stakeholders",
        ({"name": "系统运维人员", "category": "operator"},),
        block_id="stakeholders",
        input_hash="hash-5",
    )
    assert [item["id"] for item in reconciled["stakeholders"]] == ["st-operator"]


def test_deleted_role_is_suppressed_through_conservative_similarity() -> None:
    state = {
        "stakeholders": [],
        "deletion_registry": [{
            "entity_type": "stakeholder",
            "match_keys": ["stakeholder:operator:运维人员"],
            "snapshot": {"name": "运维人员", "category": "operator"},
        }],
    }
    reconciled, summary = reconcile_entities(
        state,
        "stakeholders",
        ({"name": "系统运维人员", "category": "operator"},),
        block_id="stakeholders",
        input_hash="hash-6",
    )
    assert reconciled["stakeholders"] == []
    assert summary.suppressed == 1
```

- [ ] **Step 2: Run reconciliation tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_reconciliation.py -q`

Expected: FAIL during collection because `reconciliation.py` does not exist.

- [ ] **Step 3: Implement the reconciliation boundary**

Implement an immutable summary and one automated merge path:

```python
from __future__ import annotations

import json
from dataclasses import dataclass

from rflp_lite.application.intelligence.identity import (
    ensure_entity_metadata,
    entity_match_keys,
    label_similarity,
)
from rflp_lite.domain.canonical import canonical_json
from rflp_lite.domain.errors import ContractViolation


_GROUP_TYPES = {
    "stakeholders": "stakeholder",
    "concerns": "concern",
    "needs": "need",
    "claims": "requirement",
    "structured_requirements": "requirement",
    "scenarios": "scenario",
    "architecture_functions": "function",
    "architecture_logical_components": "logical_component",
    "architecture_physical_components": "physical_component",
    "architecture_interfaces": "interface",
}
_CONTROL_FIELDS = frozenset({
    "id", "target_id", "operation", "revision", "last_editor", "field_sources",
    "match_keys", "identity_hash", "suggested_changes", "review_hint",
    "analysis_block_id", "analysis_input_hash", "source_item_id", "producer",
})


@dataclass(frozen=True, slots=True)
class ReconcileSummary:
    added: int = 0
    updated: int = 0
    related: int = 0
    suggested: int = 0
    suppressed: int = 0

    def merge(self, other: "ReconcileSummary") -> "ReconcileSummary":
        return ReconcileSummary(*(getattr(self, field) + getattr(other, field) for field in self.__dataclass_fields__))

    def as_dict(self) -> dict[str, int]:
        return {field: int(getattr(self, field)) for field in self.__dataclass_fields__}


def accumulate_summary(
    state: dict[str, object], current: ReconcileSummary
) -> dict[str, int]:
    previous = state.get("analysis_summary")
    values = previous if isinstance(previous, dict) else {}
    return {
        field: int(values.get(field, 0)) + int(getattr(current, field))
        for field in current.__dataclass_fields__
    }


def _deleted_keys(state: dict[str, object], entity_type: str) -> set[str]:
    return {
        str(key)
        for entry in state.get("deletion_registry", ())
        if isinstance(entry, dict) and entry.get("entity_type") == entity_type
        for key in entry.get("match_keys", ())
    }


def _suppressed_match_keys(
    state: dict[str, object],
    entity_type: str,
    candidate: dict[str, object],
) -> set[str]:
    candidate_keys = set(entity_match_keys(entity_type, candidate))
    exact = candidate_keys & _deleted_keys(state, entity_type)
    if exact:
        return exact
    for entry in state.get("deletion_registry", ()):
        if not isinstance(entry, dict) or entry.get("entity_type") != entity_type:
            continue
        snapshot = entry.get("snapshot")
        if not isinstance(snapshot, dict) or not _same_identity_scope(
            entity_type, snapshot, candidate
        ):
            continue
        if label_similarity(
            _primary_label(entity_type, snapshot),
            _primary_label(entity_type, candidate),
        ) >= 0.92:
            return set(str(value) for value in entry.get("match_keys", ()))
    return set()


def _match(items: list[dict[str, object]], keys: set[str]) -> dict[str, object] | None:
    return next((item for item in items if keys.intersection(str(key) for key in item.get("match_keys", ()))), None)


def _primary_label(entity_type: str, item: dict[str, object]) -> object:
    if entity_type == "need":
        return item.get("statement", "")
    if entity_type == "scenario":
        return item.get("title", item.get("description", ""))
    return item.get("name", item.get("object", item.get("statement", "")))


def _same_identity_scope(
    entity_type: str,
    left: dict[str, object],
    right: dict[str, object],
) -> bool:
    if entity_type == "stakeholder":
        return left.get("category") == right.get("category")
    if entity_type in {"concern", "need"}:
        return left.get("stakeholder_id") == right.get("stakeholder_id")
    if entity_type == "scenario":
        return left.get("scenario_type", "normal") == right.get("scenario_type", "normal")
    return entity_type in {"function", "logical_component", "physical_component", "interface"}


def _near_matches(
    entity_type: str,
    items: list[dict[str, object]],
    candidate: dict[str, object],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    scored = sorted(
        (
            (label_similarity(_primary_label(entity_type, item), _primary_label(entity_type, candidate)), item)
            for item in items
            if _same_identity_scope(entity_type, item, candidate)
        ),
        key=lambda pair: (-pair[0], str(pair[1].get("id", ""))),
    )
    possible = [item for score, item in scored if score >= 0.72]
    if not scored or scored[0][0] < 0.92:
        return None, possible
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.08:
        return None, possible
    return scored[0][1], possible


def reconcile_entities(
    state: dict[str, object],
    group: str,
    incoming: tuple[dict[str, object], ...],
    *,
    block_id: str,
    input_hash: str,
) -> tuple[dict[str, object], ReconcileSummary]:
    if group not in _GROUP_TYPES:
        raise ContractViolation(f"不支持自动对账的实体组: {group}")
    result = json.loads(canonical_json(state))
    entity_type = _GROUP_TYPES[group]
    items = [ensure_entity_metadata(entity_type, item) for item in result.get(group, ())]
    summary = ReconcileSummary()
    for raw in incoming:
        operation = str(raw.get("operation", "upsert_entity"))
        candidate = ensure_entity_metadata(
            entity_type,
            {key: value for key, value in raw.items() if key != "operation"},
            editor="llm",
        )
        keys = set(entity_match_keys(entity_type, candidate))
        suppressed_keys = _suppressed_match_keys(result, entity_type, candidate)
        if suppressed_keys:
            hints = list(result.get("analysis_review_hints", ()))
            hint = {
                "entity_type": entity_type,
                "match_keys": sorted(suppressed_keys),
                "operation": operation,
                "block_id": block_id,
                "input_hash": input_hash,
                "message": "模型再次识别到人工删除的对象；保持删除，等待人工恢复。",
            }
            if hint not in hints:
                hints.append(hint)
            result["analysis_review_hints"] = hints
            summary = summary.merge(ReconcileSummary(suppressed=1))
            continue
        target_id = str(raw.get("target_id", ""))
        current = next(
            (item for item in items if target_id and item.get("id") == target_id),
            None,
        ) or _match(items, keys)
        possible_duplicates: list[dict[str, object]] = []
        if current is None:
            current, possible_duplicates = _near_matches(
                entity_type, items, candidate
            )
        if current is None:
            if operation != "upsert_entity":
                hints = list(result.get("analysis_review_hints", ()))
                hint = {
                    "entity_type": entity_type,
                    "target_id": target_id,
                    "operation": operation,
                    "block_id": block_id,
                    "input_hash": input_hash,
                    "message": str(candidate.get("review_hint", "未找到建议对应的当前对象")),
                }
                if hint not in hints:
                    hints.append(hint)
                result["analysis_review_hints"] = hints
                summary = summary.merge(ReconcileSummary(suggested=1))
                continue
            source_item_id = str(candidate.get("id", ""))
            candidate["source_item_id"] = source_item_id
            candidate["id"] = f"{entity_type}-{str(candidate['identity_hash'])[:12]}"
            candidate["producer"] = "llm"
            candidate["analysis_block_id"] = block_id
            candidate["analysis_input_hash"] = input_hash
            if possible_duplicates:
                candidate["possible_duplicate_ids"] = sorted(
                    str(item.get("id", "")) for item in possible_duplicates
                )
                candidate["review_hint"] = "名称相近但无法唯一确认，请人工核对是否重复。"
            items.append(candidate)
            summary = summary.merge(ReconcileSummary(added=1))
            continue
        changed = False
        suggestions = list(current.get("suggested_changes", ()))
        sources = dict(current.get("field_sources") or {})
        if operation == "flag_for_review":
            hint = str(candidate.get("review_hint", "模型标记此对象需要人工复核")).strip()
            if hint and current.get("review_hint") != hint:
                current["review_hint"] = hint
                current["revision"] = int(current.get("revision", 1)) + 1
                summary = summary.merge(ReconcileSummary(updated=1))
            continue
        for field, value in candidate.items():
            if field in _CONTROL_FIELDS or value in (None, "", [], {}):
                continue
            if operation == "propose_change" or (
                sources.get(field) in {"user", "rule"}
                and current.get(field) != value
            ):
                suggestion = {"field": field, "current": current.get(field), "suggested": value, "block_id": block_id, "input_hash": input_hash}
                if suggestion not in suggestions:
                    suggestions.append(suggestion)
                    summary = summary.merge(ReconcileSummary(suggested=1))
                continue
            if current.get(field) != value:
                current[field] = value
                sources[field] = "llm"
                changed = True
        current["field_sources"] = sources
        current["suggested_changes"] = suggestions
        current["match_keys"] = sorted(set(current.get("match_keys", ())) | keys)
        if changed:
            current["revision"] = int(current.get("revision", 1)) + 1
            current["last_editor"] = "llm"
            summary = summary.merge(ReconcileSummary(updated=1))
    result[group] = sorted(items, key=lambda item: str(item.get("id", "")))
    return result, summary
```

Reject an unknown operation before the loop. `enrich_fields`, `propose_change`, and `flag_for_review` require either `target_id` or a match key that resolves to an existing object; only `upsert_entity` may create. Implement `reconcile_relations` with the same idempotent pattern using `(source_id, predicate, target_id)` as its stable key. It accepts only `add_relation` or `flag_for_review`, rejects missing endpoints, and never removes an existing relation.

- [ ] **Step 4: Run reconciliation tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_reconciliation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the reconciliation service**

```bash
git add src/rflp_lite/application/intelligence/reconciliation.py tests/application/intelligence/test_reconciliation.py
git commit -m "feat: reconcile automated analysis safely"
```

---

### Task 3: Strict Non-Delete LLM Operations and Six-Block Integration

**Files:**
- Modify: `src/rflp_lite/application/intelligence/block_schemas.py`
- Modify: `src/rflp_lite/application/intelligence/validated_result.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Test: `tests/application/intelligence/test_block_schemas.py`
- Test: `tests/contracts/test_analysis_block_contract.py`
- Test: `tests/application/intelligence/test_enrichment_jobs.py`

**Interfaces:**
- Consumes: `reconcile_entities` and `reconcile_relations` from Task 2.
- Produces: block items with required `operation` in `{"upsert_entity", "add_relation", "enrich_fields", "propose_change", "flag_for_review"}` and `current_entities_for(block_id: str, state: dict[str, object]) -> dict[str, object]`.

- [ ] **Step 1: Add failing schema tests that accept approved operations and reject delete**

```python
def test_stakeholder_schema_requires_an_approved_operation() -> None:
    payload = {
        "items": [{**_base_item("stakeholders"), "operation": "upsert_entity"}],
        "diagnostics": [],
    }
    assert parse_block_dto("stakeholders", payload).items


def test_analysis_schema_rejects_delete_operation() -> None:
    payload = {
        "items": [{**_base_item("stakeholders"), "operation": "delete"}],
        "diagnostics": [],
    }
    with pytest.raises(ContractViolation, match="Strict Schema"):
        parse_block_dto("stakeholders", payload)
```

- [ ] **Step 2: Run schema tests and verify they fail**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_block_schemas.py tests/contracts/test_analysis_block_contract.py -q`

Expected: FAIL because current item schemas do not require `operation` and still accept it inconsistently.

- [ ] **Step 3: Add operation properties with entity/relation-specific enums**

Add these shared schemas. Include `_ENTITY_OPERATION` in `_SYSTEM_SCOPE`, `_STAKEHOLDER`, `_CONCERN`, `_NEED`, `_REQUIREMENT`, `_SCENARIO`, and `_ARCHITECTURE_ENTITY`; include `_RELATION_OPERATION` only in relation schemas. Make `operation` required everywhere, and add optional `target_id` plus `review_hint` to entity schemas used by proposal/review operations:

```python
_ENTITY_OPERATION = {
    "type": "string",
    "enum": [
        "upsert_entity",
        "enrich_fields",
        "propose_change",
        "flag_for_review",
    ],
}
_RELATION_OPERATION = {
    "type": "string",
    "enum": ["add_relation", "flag_for_review"],
}
```

Update the existing test helper `_base_item` so its common fields include `operation="upsert_entity"`. Add contract tests proving a stakeholder cannot use `add_relation`, a relation cannot use `upsert_entity`, and no schema accepts `delete`. Update `_legacy_fixture_response` so pre-v2 fixture items receive `operation="upsert_entity"`, while relation items receive `operation="add_relation"`.

In `validated_result.py`, add the semantic check that `enrich_fields`, `propose_change`, and `flag_for_review` carry a non-empty `target_id` or enough identity fields for the entity type; a relation `flag_for_review` must carry the existing relation ID. Reject invalid operation/target combinations before reconciliation.

Update every block system prompt to state that it may add, enrich, propose, relate, or flag only; it must never emit delete/remove/purge semantics. Schema validation remains the enforcement boundary even if a provider ignores this instruction.

- [ ] **Step 4: Write failing integration tests for canonical cross-block context**

```python
from rflp_lite.application.intelligence.analysis_blocks import current_entities_for


def test_concerns_request_receives_reconciled_stakeholder_ids() -> None:
    state = {
        "stakeholders": [{"id": "st-1", "name": "运维人员", "category": "operator"}],
        "concerns": [], "needs": [], "claims": [], "structured_requirements": [], "scenarios": [],
    }
    context = current_entities_for("concerns_needs", state)
    assert context["stakeholders"] == [{"id": "st-1", "name": "运维人员", "category": "operator"}]


def test_scenario_request_receives_requirements_and_stakeholders() -> None:
    state = {
        "stakeholders": [{"id": "st-1", "name": "运维人员", "category": "operator"}],
        "claims": [{"id": "req-1", "object": "系统应记录故障", "status": "accepted"}],
        "structured_requirements": [], "concerns": [], "needs": [], "scenarios": [],
    }
    context = current_entities_for("scenarios", state)
    assert context["stakeholders"][0]["id"] == "st-1"
    assert context["requirements"][0]["id"] == "req-1"
```

- [ ] **Step 5: Route block merges through reconciliation**

Implement `current_entities_for` as a canonical index and add it to `build_block_request(state, block, composed_pack).user_payload["current_entities"]`:

```python
def current_entities_for(block_id: str, state: dict[str, object]) -> dict[str, object]:
    def compact(group: str, fields: tuple[str, ...]) -> list[dict[str, object]]:
        return [
            {field: item.get(field) for field in fields if field in item}
            for item in state.get(group, ())
            if isinstance(item, dict) and item.get("status") != "rejected"
        ]

    context: dict[str, object] = {}
    if block_id in {"concerns_needs", "requirements", "scenarios", "architecture"}:
        context["stakeholders"] = compact(
            "stakeholders", ("id", "name", "category", "goals", "interactions")
        )
    if block_id in {"requirements", "scenarios", "architecture"}:
        context["concerns"] = compact("concerns", ("id", "name", "stakeholder_id"))
        context["needs"] = compact(
            "needs", ("id", "statement", "stakeholder_id", "concern_id")
        )
    if block_id in {"scenarios", "architecture"}:
        context["requirements"] = compact(
            "claims", ("id", "subject", "predicate", "object", "status")
        )
    if block_id == "architecture":
        context["scenarios"] = compact(
            "scenarios", ("id", "title", "scenario_type", "actors", "requirement_ids")
        )
    return context
```

Replace direct list appends in `merge_block_result` with this dispatcher. Map model-provided references through `source_item_id` aliases before reconciliation:

```python
_BLOCK_GROUPS = {
    "stakeholders": ("stakeholders",),
    "concerns_needs": ("concerns", "needs"),
    "requirements": ("structured_requirements", "claims"),
    "scenarios": ("scenarios",),
}


def _reconcile_block_entities(
    state: dict[str, object],
    validated: ValidatedBlockResult,
) -> tuple[dict[str, object], ReconcileSummary]:
    result = state
    summary = ReconcileSummary()
    grouped: dict[str, list[dict[str, object]]] = {
        group: [] for group in _BLOCK_GROUPS.get(validated.block_id, ())
    }
    for item in validated.dto.items:
        raw = dict(item)
        raw.setdefault("provider_id", str(validated.provenance.get("provider_id", "")))
        raw.setdefault("model_id", str(validated.provenance.get("model_id", "")))
        raw.setdefault("analysis_reason", str(raw.get("rationale", "")))
        if validated.block_id == "concerns_needs":
            group = "concerns" if raw.get("kind") == "concern" else "needs"
        elif validated.block_id == "requirements":
            group = "structured_requirements"
        else:
            groups = _BLOCK_GROUPS.get(validated.block_id, ())
            if not groups:
                continue
            group = groups[0]
        grouped.setdefault(group, []).append(raw)
    for group, values in grouped.items():
        result, current = reconcile_entities(
            result,
            group,
            tuple(values),
            block_id=validated.block_id,
            input_hash=validated.input_hash,
        )
        summary = summary.merge(current)
    return result, summary
```

When reconciling `requirements`, derive the compatible Claim view from each reconciled structured requirement after it has a formal ID. Handle `system_scope` through field-source precedence too: union list fields such as boundaries/interfaces across batches, preserve human scalar fields, and turn conflicting scalar model values into suggestions instead of allowing the last batch to win. Handle `architecture` through `reconcile_relations` plus the existing architecture buckets.

Replace `_merge_architecture`'s “remove only this input hash, then append” behavior with a temporary flat-state reconciliation so a new input hash cannot duplicate old architecture entities:

```python
_ARCHITECTURE_GROUPS = {
    "functions": "architecture_functions",
    "logical_components": "architecture_logical_components",
    "physical_components": "architecture_physical_components",
    "interfaces": "architecture_interfaces",
}
_ARCHITECTURE_ENTITY_TYPES = {
    "architecture_functions": "function",
    "architecture_logical_components": "logical_component",
    "architecture_physical_components": "physical_component",
    "architecture_interfaces": "interface",
}


def _merge_reconciled_architecture(
    state: dict[str, object], validated: ValidatedBlockResult
) -> dict[str, object]:
    result = json.loads(canonical_json(state))
    discovery = dict(result.get("discovery") or {})
    architecture = dict(discovery.get("architecture") or {})
    temporary: dict[str, object] = {
        group: list(architecture.get(bucket, ()))
        for bucket, group in _ARCHITECTURE_GROUPS.items()
    }
    temporary["deletion_registry"] = list(result.get("deletion_registry", ()))
    incoming_by_group = {group: [] for group in _ARCHITECTURE_GROUPS.values()}
    relation_items: list[dict[str, object]] = []
    for item in validated.dto.items:
        raw = dict(item)
        raw.setdefault("provider_id", str(validated.provenance.get("provider_id", "")))
        raw.setdefault("model_id", str(validated.provenance.get("model_id", "")))
        raw.setdefault("analysis_reason", str(raw.get("rationale", "")))
        bucket = _architecture_bucket(raw)
        if bucket is None:
            relation_items.append(raw)
        else:
            relation_items.extend(
                dict(relation)
                for relation in raw.get("relations", ())
                if isinstance(relation, dict)
            )
            raw.pop("relations", None)
            incoming_by_group[_ARCHITECTURE_GROUPS[bucket]].append(raw)
    summary = ReconcileSummary()
    aliases: dict[str, str] = {}
    for group, incoming in incoming_by_group.items():
        temporary, current = reconcile_entities(
            temporary,
            group,
            tuple(incoming),
            block_id=validated.block_id,
            input_hash=validated.input_hash,
        )
        summary = summary.merge(current)
        for raw in incoming:
            raw_id = str(raw.get("id", ""))
            raw_keys = set(entity_match_keys(_ARCHITECTURE_ENTITY_TYPES[group], raw))
            matched = next(
                (
                    item for item in temporary[group]
                    if raw_keys.intersection(item.get("match_keys", ()))
                ),
                None,
            )
            if raw_id and matched is not None:
                aliases[raw_id] = str(matched["id"])
    valid_ids = _all_ids(result) | {
        str(item["id"])
        for group in _ARCHITECTURE_GROUPS.values()
        for item in temporary[group]
    }
    mapped_relations = tuple(
        {
            **raw,
            "source_id": aliases.get(str(raw.get("source_id", "")), str(raw.get("source_id", ""))),
            "target_id": aliases.get(str(raw.get("target_id", "")), str(raw.get("target_id", ""))),
        }
        for raw in relation_items
    )
    relation_state = {
        **temporary,
        "trace_links": list(architecture.get("relations", ())),
        "valid_entity_ids": sorted(valid_ids),
        "deletion_registry": list(result.get("deletion_registry", ())),
    }
    relation_state, relation_summary = reconcile_relations(
        relation_state,
        mapped_relations,
        block_id=validated.block_id,
        input_hash=validated.input_hash,
    )
    summary = summary.merge(relation_summary)
    for bucket, group in _ARCHITECTURE_GROUPS.items():
        architecture[bucket] = temporary[group]
    architecture["relations"] = relation_state["trace_links"]
    discovery["architecture"] = architecture
    result["discovery"] = discovery
    result["analysis_summary"] = accumulate_summary(result, summary)
    return _record_block_result(result, validated)
```

Make `reconcile_relations` include `state["valid_entity_ids"]` in endpoint validation in addition to IDs discovered from ordinary groups. This preserves cross-block formal references while letting the temporary architecture collection use the same relation reconciler.

The public merge stays compatible:

```python
def merge_block_result(
    state: dict[str, object],
    result_or_block_id: ValidatedBlockResult | str,
    response: GenerationResponse | None = None,
) -> dict[str, object]:
    validated = _validated_compatibility_result(state, result_or_block_id, response)
    if validated.block_id == "system_scope":
        return _merge_system_scope(state, validated)
    if validated.block_id == "architecture":
        return _merge_reconciled_architecture(state, validated)
    result, summary = _reconcile_block_entities(state, validated)
    result["analysis_summary"] = accumulate_summary(result, summary)
    return _record_block_result(result, validated)
```

Add `ReconcileSummary.as_dict()` and extract the current compatibility conversion, system-scope merge, architecture merge, and block-result provenance recording into the named private helpers shown above. Each helper must return a complete Workbench dictionary and must not mutate its input.

Store the accumulated `ReconcileSummary` under:

```python
result["analysis_summary"] = {
    "added": summary.added,
    "updated": summary.updated,
    "related": summary.related,
    "suggested": summary.suggested,
    "suppressed": summary.suppressed,
}
```

- [ ] **Step 6: Run block, contract, and enrichment tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_block_schemas.py tests/application/intelligence/test_validated_result.py tests/contracts/test_analysis_block_contract.py tests/application/intelligence/test_enrichment_jobs.py -q`

Expected: PASS; delete operations are rejected, cross-block references use current formal IDs, and existing partial-failure tests still pass.

- [ ] **Step 7: Commit strict operations and reconciled blocks**

```bash
git add src/rflp_lite/application/intelligence/block_schemas.py src/rflp_lite/application/intelligence/validated_result.py src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/intelligence/enrichment_jobs.py tests/application/intelligence/test_block_schemas.py tests/contracts/test_analysis_block_contract.py tests/application/intelligence/test_enrichment_jobs.py
git commit -m "feat: reconcile strict analysis block operations"
```

---

### Task 4: Complete Project Snapshots, Coverage Audit, and Source Batching

**Files:**
- Create: `src/rflp_lite/application/intelligence/project_snapshot.py`
- Create: `src/rflp_lite/application/intelligence/coverage_audit.py`
- Modify: `src/rflp_lite/application/intelligence/block_schemas.py`
- Modify: `src/rflp_lite/application/intelligence/validated_result.py`
- Modify: `src/rflp_lite/application/intelligence/analysis_blocks.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Test: `tests/application/intelligence/test_project_snapshot.py`
- Test: `tests/application/intelligence/test_coverage_audit.py`
- Test: `tests/application/intelligence/test_enrichment_jobs.py`

**Interfaces:**
- Produces: `build_project_snapshot(state: dict[str, object], *, mode: str, delta_region_ids: tuple[str, ...] = ()) -> dict[str, object]`, `source_batches(snapshot: dict[str, object], *, batch_size: int = 20) -> tuple[tuple[dict[str, object], ...], ...]`, and `evaluate_project_coverage(state: dict[str, object], pack: dict[str, object]) -> dict[str, object]`.
- Consumes: normalized metadata and reconciled formal IDs from Tasks 1–3.

- [ ] **Step 1: Write failing tests proving that more than 24 regions are retained**

```python
from rflp_lite.application.intelligence.project_snapshot import build_project_snapshot, source_batches


def test_snapshot_batches_every_source_without_truncation() -> None:
    regions = [{"id": f"region-{index}", "text": f"需求 {index}"} for index in range(55)]
    state = {
        "revision": 8,
        "project_scope": {"workspace": "demo", "input_hash": "hash"},
        "document_regions": regions,
        "stakeholders": [], "concerns": [], "needs": [], "claims": [],
        "structured_requirements": [], "scenarios": [], "deletion_registry": [],
    }
    snapshot = build_project_snapshot(state, mode="full_reanalysis")
    batches = source_batches(snapshot, batch_size=20)
    assert [len(batch) for batch in batches] == [20, 20, 15]
    assert {item["id"] for batch in batches for item in batch} == {item["id"] for item in regions}
```

- [ ] **Step 2: Write failing coverage tests**

```python
from rflp_lite.application.intelligence.coverage_audit import evaluate_project_coverage


def test_coverage_reports_missing_stakeholder_details_and_scenario_types() -> None:
    state = {
        "stakeholders": [{"id": "st-1", "name": "用户", "category": "end_user", "goals": [], "interactions": []}],
        "concerns": [], "needs": [],
        "claims": [{"id": "req-1", "status": "accepted", "object": "系统应支持操作"}],
        "structured_requirements": [],
        "scenarios": [{"id": "sc-1", "scenario_type": "normal", "requirement_ids": ["req-1"]}],
    }
    report = evaluate_project_coverage(state, {})
    assert "stakeholder_goals" in report["missing_dimensions"]
    assert set(report["missing_scenario_types"]) == {"boundary", "failure", "recovery", "misuse"}
    assert "cybersecurity" in report["missing_scenario_dimensions"]
    assert report["stakeholder_ids_without_concerns"] == ["st-1"]
    assert report["stakeholder_ids_without_needs"] == ["st-1"]
    assert report["requirements_without_function_ids"] == ["req-1"]
    assert report["requirements_without_verification_ids"] == ["req-1"]
```

- [ ] **Step 3: Run snapshot and coverage tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_project_snapshot.py tests/application/intelligence/test_coverage_audit.py -q`

Expected: FAIL because the modules are missing.

- [ ] **Step 4: Implement complete snapshots and batching**

Use a JSON-safe snapshot that includes all effective entities and only compact fields:

```python
def build_project_snapshot(
    state: dict[str, object],
    *,
    mode: str,
    delta_region_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    if mode not in {"incremental", "coverage_audit", "full_reanalysis"}:
        raise ContractViolation(f"未知需求分析模式: {mode}")
    scope = state.get("project_scope") if isinstance(state.get("project_scope"), dict) else {}
    regions = [
        {
            "id": str(item.get("id", "")),
            "text": str(item.get("text", "")),
            "locator": str(item.get("locator", "")),
        }
        for item in state.get("document_regions", state.get("spans", ()))
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ]
    delta = set(delta_region_ids)
    selected_regions = (
        [item for item in regions if item["id"] in delta]
        if mode == "incremental" and delta
        else regions
    )
    discovery = state.get("discovery") if isinstance(state.get("discovery"), dict) else {}
    architecture = (
        discovery.get("architecture")
        if isinstance(discovery.get("architecture"), dict)
        else {}
    )
    return {
        "mode": mode,
        "workspace": str(scope.get("workspace", "")),
        "revision": int(state.get("revision", 0)),
        "content_revision": int(state.get("content_revision", state.get("revision", 0))),
        "input_hash": str(scope.get("input_hash", "")),
        "delta_region_ids": list(delta_region_ids),
        "input_regions": selected_regions,
        "all_source_ids": sorted(item["id"] for item in regions),
        "stakeholders": list(state.get("stakeholders", ())),
        "concerns": list(state.get("concerns", ())),
        "needs": list(state.get("needs", ())),
        "requirements": list(state.get("structured_requirements", ())) + list(state.get("claims", ())),
        "scenarios": list(state.get("scenarios", ())),
        "trace_links": list(state.get("trace_links", ())),
        "architecture": dict(architecture),
        "deletion_registry": list(state.get("deletion_registry", ())),
    }
```

`source_batches` must return every source in stable ID order and return one empty tuple when no sources exist, so the system-scope block can still run for a manual workbench:

```python
def source_batches(
    snapshot: dict[str, object], *, batch_size: int = 20
) -> tuple[tuple[dict[str, object], ...], ...]:
    if batch_size < 1:
        raise ContractViolation("source batch size must be positive")
    sources = tuple(sorted(
        (dict(item) for item in snapshot.get("input_regions", ()) if isinstance(item, dict)),
        key=lambda item: str(item.get("id", "")),
    ))
    if not sources:
        return ((),)
    return tuple(
        sources[offset:offset + batch_size]
        for offset in range(0, len(sources), batch_size)
    )
```

- [ ] **Step 5: Implement deterministic coverage**

Return a JSON-safe report with at least:

```python
{
    "missing_dimensions": [],
    "missing_stakeholder_categories": [],
    "missing_scenario_types": [],
    "missing_scenario_dimensions": [],
    "missing_lifecycle_phases": [],
    "stakeholder_ids_without_concerns": [],
    "stakeholder_ids_without_needs": [],
    "requirements_without_stakeholder_ids": [],
    "requirements_without_scenario_ids": [],
    "requirements_without_function_ids": [],
    "requirements_without_logical_component_ids": [],
    "requirements_without_physical_component_ids": [],
    "requirements_without_interface_ids": [],
    "requirements_without_verification_ids": [],
    "unlinked_scenario_ids": [],
    "analyzed_source_ids": [],
    "unprocessed_source_ids": [],
}
```

Implement the core calculation with stable sorted output:

```python
CORE_SCENARIO_TYPES = frozenset({"normal", "boundary", "failure", "recovery", "misuse"})
CORE_SCENARIO_DIMENSIONS = frozenset({
    "external_system_failure",
    "human_interaction_error",
    "performance_capacity_boundary",
    "safety",
    "cybersecurity",
    "regulatory",
})
CORE_STAKEHOLDER_CATEGORIES = frozenset({
    "customer", "end_user", "operator", "engineering", "supplier",
    "regulator", "external_system", "environment",
})


def _valid_not_applicable(
    decisions: list[dict[str, object]],
    *,
    decision_type: str,
    valid_requirement_ids: set[str],
) -> set[str]:
    return {
        str(item.get("key", ""))
        for item in decisions
        if item.get("decision_type") == decision_type
        and item.get("status") == "not_applicable"
        and str(item.get("rationale", "")).strip()
        and bool(item.get("source_requirement_ids"))
        and set(str(value) for value in item.get("source_requirement_ids", ())) <= valid_requirement_ids
    }


def _not_applicable_requirement_ids(
    decisions: list[dict[str, object]],
    *,
    decision_type: str,
    key: str,
    valid_requirement_ids: set[str],
) -> set[str]:
    return {
        str(requirement_id)
        for item in decisions
        if item.get("decision_type") == decision_type
        and item.get("key") == key
        and item.get("status") == "not_applicable"
        and str(item.get("rationale", "")).strip()
        for requirement_id in item.get("source_requirement_ids", ())
        if str(requirement_id) in valid_requirement_ids
    }


def _missing_stakeholder_categories(
    stakeholders: list[dict[str, object]],
    pack: dict[str, object],
    decisions: list[dict[str, object]],
    requirement_ids: set[str],
) -> list[str]:
    configured = {
        str(value)
        for value in pack.get("stakeholder_categories", ())
        if str(value).strip()
    }
    expected = CORE_STAKEHOLDER_CATEGORIES | configured
    present = {str(item.get("category", "other")) for item in stakeholders}
    not_applicable = _valid_not_applicable(
        decisions,
        decision_type="stakeholder_category",
        valid_requirement_ids=requirement_ids,
    )
    return sorted(expected - present - not_applicable)


def evaluate_project_coverage(
    state: dict[str, object], pack: dict[str, object]
) -> dict[str, object]:
    stakeholders = [item for item in state.get("stakeholders", ()) if isinstance(item, dict)]
    scenarios = [item for item in state.get("scenarios", ()) if isinstance(item, dict) and item.get("status") != "rejected"]
    requirements = [item for item in state.get("claims", ()) if isinstance(item, dict) and item.get("status") != "rejected"]
    requirement_ids = {str(item.get("id", "")) for item in requirements}
    covered_types = {str(item.get("scenario_type", "normal")) for item in scenarios}
    covered_dimensions = {
        str(value)
        for item in scenarios
        for value in item.get("coverage_dimensions", ())
    }
    expected_lifecycle_phases = {
        str(value) for value in pack.get("lifecycle_phases", ()) if str(value).strip()
    }
    covered_lifecycle_phases = {
        str(item.get("lifecycle_phase", ""))
        for item in scenarios if str(item.get("lifecycle_phase", ""))
    }
    decisions = [item for item in state.get("coverage_decisions", ()) if isinstance(item, dict)]
    considered_not_applicable = _valid_not_applicable(
        decisions,
        decision_type="scenario_type",
        valid_requirement_ids=requirement_ids,
    )
    dimensions_not_applicable = _valid_not_applicable(
        decisions,
        decision_type="scenario_dimension",
        valid_requirement_ids=requirement_ids,
    )
    lifecycle_not_applicable = _valid_not_applicable(
        decisions,
        decision_type="lifecycle_phase",
        valid_requirement_ids=requirement_ids,
    )
    missing_dimensions: set[str] = set()
    if any(not item.get("goals") for item in stakeholders):
        missing_dimensions.add("stakeholder_goals")
    if any(not item.get("interactions") for item in stakeholders):
        missing_dimensions.add("stakeholder_interactions")
    linked_requirement_ids = {
        str(requirement_id)
        for scenario in scenarios
        for requirement_id in scenario.get("requirement_ids", ())
    }
    stakeholder_ids = {str(item.get("id", "")) for item in stakeholders}
    concern_stakeholder_ids = {
        str(item.get("stakeholder_id", ""))
        for item in state.get("concerns", ()) if isinstance(item, dict)
    }
    need_stakeholder_ids = {
        str(item.get("stakeholder_id", ""))
        for item in state.get("needs", ()) if isinstance(item, dict)
    }
    need_to_stakeholder = {
        str(item.get("id", "")): str(item.get("stakeholder_id", ""))
        for item in state.get("needs", ()) if isinstance(item, dict)
    }
    stakeholder_linked_requirement_ids = {
        str(item.get("id", ""))
        for item in requirements
        if item.get("stakeholder_id") in stakeholder_ids
        or need_to_stakeholder.get(str(item.get("need_id", ""))) in stakeholder_ids
    }
    discovery = state.get("discovery") if isinstance(state.get("discovery"), dict) else {}
    architecture = discovery.get("architecture") if isinstance(discovery.get("architecture"), dict) else {}
    function_requirement_ids = {
        str(requirement_id)
        for item in architecture.get("functions", ())
        if isinstance(item, dict)
        for requirement_id in item.get("requirement_ids", item.get("source_requirement_ids", ()))
    }
    interface_requirement_ids = {
        str(requirement_id)
        for item in architecture.get("interfaces", ())
        if isinstance(item, dict)
        for requirement_id in item.get("requirement_ids", item.get("source_requirement_ids", ()))
    }
    logical_requirement_ids = {
        str(requirement_id)
        for item in architecture.get("logical_components", ())
        if isinstance(item, dict)
        for requirement_id in item.get("requirement_ids", item.get("source_requirement_ids", ()))
    }
    physical_requirement_ids = {
        str(requirement_id)
        for item in architecture.get("physical_components", ())
        if isinstance(item, dict)
        for requirement_id in item.get("requirement_ids", item.get("source_requirement_ids", ()))
    }
    verification_requirement_ids = {
        str(endpoint)
        for item in state.get("trace_links", ())
        if isinstance(item, dict)
        and str(item.get("predicate", "")).casefold() in {
            "verifies", "verifiedby", "validates", "validatedby", "tests",
        }
        for endpoint in (item.get("source_id"), item.get("target_id"))
        if str(endpoint) in requirement_ids
    }
    architecture_not_applicable = {
        key: _not_applicable_requirement_ids(
            decisions,
            decision_type="architecture_dimension",
            key=key,
            valid_requirement_ids=requirement_ids,
        )
        for key in ("function", "logical_component", "physical_component", "interface", "verification")
    }
    all_source_ids = {
        str(item.get("id", ""))
        for item in state.get("document_regions", state.get("spans", ()))
        if isinstance(item, dict) and item.get("id")
    }
    analyzed_source_ids = {
        str(value) for value in state.get("analysis_source_registry", ())
    }
    return {
        "missing_dimensions": sorted(missing_dimensions),
        "missing_stakeholder_categories": _missing_stakeholder_categories(
            stakeholders, pack, decisions, requirement_ids
        ),
        "missing_scenario_types": sorted(CORE_SCENARIO_TYPES - covered_types - considered_not_applicable),
        "missing_scenario_dimensions": sorted(
            CORE_SCENARIO_DIMENSIONS - covered_dimensions - dimensions_not_applicable
        ),
        "missing_lifecycle_phases": sorted(
            expected_lifecycle_phases
            - covered_lifecycle_phases
            - lifecycle_not_applicable
        ),
        "stakeholder_ids_without_concerns": sorted(stakeholder_ids - concern_stakeholder_ids),
        "stakeholder_ids_without_needs": sorted(stakeholder_ids - need_stakeholder_ids),
        "requirements_without_stakeholder_ids": sorted(requirement_ids - stakeholder_linked_requirement_ids),
        "requirements_without_scenario_ids": sorted(requirement_ids - linked_requirement_ids),
        "requirements_without_function_ids": sorted(requirement_ids - function_requirement_ids - architecture_not_applicable["function"]),
        "requirements_without_logical_component_ids": sorted(requirement_ids - logical_requirement_ids - architecture_not_applicable["logical_component"]),
        "requirements_without_physical_component_ids": sorted(requirement_ids - physical_requirement_ids - architecture_not_applicable["physical_component"]),
        "requirements_without_interface_ids": sorted(requirement_ids - interface_requirement_ids - architecture_not_applicable["interface"]),
        "requirements_without_verification_ids": sorted(requirement_ids - verification_requirement_ids - architecture_not_applicable["verification"]),
        "unlinked_scenario_ids": sorted(str(item.get("id", "")) for item in scenarios if not item.get("requirement_ids")),
        "analyzed_source_ids": sorted(analyzed_source_ids),
        "unprocessed_source_ids": sorted(all_source_ids - analyzed_source_ids),
    }
```

Extend the strict scenario and architecture response envelopes with `coverage_decisions`. Each item requires `decision_type` in `{"scenario_type", "scenario_dimension", "lifecycle_phase", "stakeholder_category", "architecture_dimension"}`, a `key`, `status="not_applicable"`, non-empty `rationale`, and non-empty `source_requirement_ids`. Constrain `key` to the five scenario types, the six core/configured scenario dimensions, configured lifecycle phases, configured/core stakeholder categories, or `function/logical_component/physical_component/interface/verification` according to its type. Parse these decisions in `validated_result.py`, reject invalid type/key pairs, assign `id="coverage-decision-" + canonical_hash((decision_type, key, sorted(source_requirement_ids)))[:12]`, and reconcile them idempotently under `state["coverage_decisions"]` using the same tuple as the stable key. A decision counts only when every referenced Requirement ID exists in the current Workbench. This lets the audit prove that a lens was considered without fabricating an irrelevant stakeholder, scenario, or architecture allocation.

- [ ] **Step 6: Feed batches and coverage gaps into analysis requests**

Remove the `[:24]` and `[:32]` truncation paths from `analysis_blocks.py`. Extend `build_block_request` so every request payload contains `analysis_mode`, workspace, repository snapshot revision, content revision, input hash, delta region IDs, current formal entities, current architecture index, coverage gaps, deletion registry, the current source batch, batch index/count, and pack guidance. Let `EnrichmentJobRunner` iterate stable source batches, reconcile each batch immediately, and run a final coverage pass:

```python
request_payload.update({
    "analysis_mode": snapshot["mode"],
    "workspace": snapshot["workspace"],
    "snapshot_revision": snapshot["revision"],
    "snapshot_content_revision": snapshot["content_revision"],
    "input_hash": snapshot["input_hash"],
    "delta_region_ids": snapshot["delta_region_ids"],
    "current_entities": current_entities_for(block.id, state),
    "current_architecture": current_architecture_for(state),
    "coverage_gaps": state.get("analysis_coverage", {}),
    "deletion_registry": snapshot["deletion_registry"],
    "input_regions": list(batch),
    "batch_index": batch_index,
    "batch_count": len(batches),
})
```

`current_architecture_for(state)` returns compact IDs, kinds, names, Requirement IDs, and relations from the latest reconciled `discovery.architecture`; it must not reuse the immutable snapshot's older architecture after a preceding batch has added formal elements.

```python
snapshot = build_project_snapshot(
    state,
    mode=analysis_mode,
    delta_region_ids=delta_region_ids,
)
state["analysis_summary"] = {}
batches = source_batches(snapshot, batch_size=20)
attempted_source_ids: set[str] = set()
source_block_states: dict[str, dict[str, str]] = {
    str(item["id"]): {}
    for item in snapshot["input_regions"]
}
for batch_index, batch in enumerate(batches, start=1):
    for block_id, block in block_map.items():
        request_state = {**state, "analysis_input_regions": list(batch)}
        state, block_status = self._run_and_reconcile_block(
            job_id, state, request_state, block, pack
        )
        for item in batch:
            source_block_states[str(item["id"])][block_id] = block_status
    attempted_source_ids.update(str(item["id"]) for item in batch)
    completed_source_ids = {
        source_id
        for source_id, statuses in source_block_states.items()
        if statuses
        and set(statuses) == set(block_map)
        and set(statuses.values()) == {"succeeded"}
    }
    self.jobs.update(job_id, {
        "source_total": len(snapshot["input_regions"]),
        "source_attempted": len(attempted_source_ids),
        "source_analyzed": len(completed_source_ids),
        "batch_count": len(batches),
        "batch_index": batch_index,
    })
state["analysis_progress"] = {
    "attempted_source_ids": sorted(attempted_source_ids),
    "analyzed_source_ids": sorted(completed_source_ids),
    "source_block_states": source_block_states,
    "source_total": len(snapshot["input_regions"]),
}
state["analysis_source_registry"] = sorted(
    set(str(value) for value in state.get("analysis_source_registry", ()))
    | completed_source_ids
)
state["analysis_coverage"] = evaluate_project_coverage(state, pack)
```

Extract the current block call/validate/reconcile code into `_run_and_reconcile_block`, returning `(latest_state, status)`; it must retain lease heartbeats, strict validation, per-block duration, and partial-failure diagnostics. Aggregate a block as `succeeded` only when it succeeded for every batch, otherwise `degraded`/`failed` with batch diagnostics. Both `incremental` and `full_reanalysis` execute all six blocks in dependency order; incremental limits raw source input to delta regions while still passing the complete reconciled project index. This ensures a new boundary/interface requirement can also update system scope.

Map deterministic gaps to one final consolidation pass:

```python
def blocks_for_coverage(report: dict[str, object]) -> tuple[str, ...]:
    selected: set[str] = set()
    if report.get("missing_dimensions") or report.get("missing_stakeholder_categories"):
        selected.add("stakeholders")
    if report.get("stakeholder_ids_without_concerns") or report.get("stakeholder_ids_without_needs"):
        selected.add("concerns_needs")
    if report.get("requirements_without_stakeholder_ids"):
        selected.add("requirements")
    if (
        report.get("missing_scenario_types")
        or report.get("missing_scenario_dimensions")
        or report.get("missing_lifecycle_phases")
        or report.get("requirements_without_scenario_ids")
        or report.get("unlinked_scenario_ids")
    ):
        selected.add("scenarios")
    if (
        report.get("requirements_without_function_ids")
        or report.get("requirements_without_logical_component_ids")
        or report.get("requirements_without_physical_component_ids")
        or report.get("requirements_without_interface_ids")
        or report.get("requirements_without_verification_ids")
    ):
        selected.add("architecture")
    return tuple(
        block_id
        for block_id in (
            "stakeholders", "concerns_needs", "requirements", "scenarios", "architecture"
        )
        if block_id in selected
    )
```

Set Job phase to `coverage_audit`, put the complete report in `request_state["coverage_gaps"]`, and call each selected block once using reconciled current entities plus the compact architecture index. Recompute `analysis_coverage` after this pass. Do not loop indefinitely: unresolved gaps stay visible for human review or a later reanalysis.

Keep `analysis_coverage` separate from the existing derived-model `coverage` field. The former records audit gaps; the latter remains RFLP trace coverage and may be rebuilt by `generate_model`.

- [ ] **Step 7: Run batching, coverage, and enrichment regression tests**

Run: `.venv/bin/python -m pytest tests/application/intelligence/test_project_snapshot.py tests/application/intelligence/test_coverage_audit.py tests/application/intelligence/test_enrichment_jobs.py tests/interface/web/test_auto_requirements.py -q`

Expected: PASS; a 55-source fixture reports 55 analyzed sources and existing six-block behavior remains valid.

- [ ] **Step 8: Commit complete snapshot and coverage support**

```bash
git add src/rflp_lite/application/intelligence/project_snapshot.py src/rflp_lite/application/intelligence/coverage_audit.py src/rflp_lite/application/intelligence/block_schemas.py src/rflp_lite/application/intelligence/validated_result.py src/rflp_lite/application/intelligence/analysis_blocks.py src/rflp_lite/application/intelligence/enrichment_jobs.py tests/application/intelligence/test_project_snapshot.py tests/application/intelligence/test_coverage_audit.py tests/application/intelligence/test_enrichment_jobs.py tests/interface/web/test_auto_requirements.py
git commit -m "feat: audit complete requirements coverage"
```

---

### Task 5: Revision-Safe Analysis Modes and Idempotent Jobs

**Files:**
- Create: `src/rflp_lite/application/use_cases/reanalyze_requirements.py`
- Modify: `src/rflp_lite/application/jobs.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/application/use_cases/requirements_analysis.py`
- Modify: `src/rflp_lite/application/use_cases/dependencies.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Test: `tests/application/test_jobs_recovery.py`
- Test: `tests/application/test_requirements_analysis_service.py`
- Test: `tests/application/use_cases/test_reanalyze_requirements.py`

**Interfaces:**
- Produces: `ReanalyzeRequirementsCommand(workspace: WorkspaceRef, mode: str, delta_region_ids: tuple[str, ...] = ())`, `ReanalyzeRequirementsUseCase.execute(command, model) -> dict[str, object]`, and new named `mode`, `snapshot_revision`, `snapshot_content_revision`, `analysis_config_hash`, and `delta_region_ids` arguments on `EnrichmentJobRunner.submit`.
- Adds durable Job state `superseded`.

- [ ] **Step 1: Write failing JobService idempotency and superseded tests**

```python
def test_submit_async_reuses_active_idempotent_job(tmp_path) -> None:
    jobs = JobService(tmp_path)
    gate = threading.Event()
    first = jobs.submit_async("requirements.enrichment", {"idempotency_key": "demo:2:full"}, lambda: (gate.wait(1), {"status": "succeeded"})[1])
    second = jobs.submit_async("requirements.enrichment", {"idempotency_key": "demo:2:full"}, lambda: {"status": "succeeded"})
    assert second["id"] == first["id"]
    gate.set()


def test_superseded_is_a_terminal_job_state(tmp_path) -> None:
    jobs = JobService(tmp_path)
    record = jobs.submit("requirements.enrichment", {}, lambda: {"status": "superseded"})
    assert record["status"] == "superseded"
```

- [ ] **Step 2: Write failing stale-revision use-case test**

```python
def test_full_reanalysis_marks_old_snapshot_superseded(fake_dependencies, workspace) -> None:
    use_case = ReanalyzeRequirementsUseCase(fake_dependencies)
    job = use_case.execute(
        ReanalyzeRequirementsCommand(workspace=workspace, mode="full_reanalysis"),
        model=FixtureModel(),
    )
    fake_dependencies.save_human_edit()
    result = fake_dependencies.run_job(job["id"])
    assert result["status"] == "superseded"
    assert fake_dependencies.latest_state()["content_revision"] > job["payload"]["snapshot_content_revision"]
```

- [ ] **Step 3: Run Job and use-case tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/test_jobs_recovery.py tests/application/use_cases/test_reanalyze_requirements.py -q`

Expected: FAIL because active jobs are not reused, `superseded` is not terminal, and the use case is missing.

- [ ] **Step 4: Add `superseded` and active idempotency to JobService**

Add `superseded` to `JOB_STATES`, terminal result normalization, wait loops, and UI terminal-state lists. Reuse an idempotency key only while its Job is `queued` or `running`, preventing double-click concurrency. Any terminal record may create a new attempt, so “重新分析全部需求” really reruns the model even when the Workbench revision is unchanged; deterministic reconciliation still makes the resulting state idempotent.

Use one shared lookup in both synchronous and asynchronous submit paths:

```python
JOB_STATES = frozenset(
    {"queued", "running", "succeeded", "completed", "degraded", "failed", "interrupted", "superseded"}
)
_REUSABLE_JOB_STATES = frozenset({"queued", "running"})
_TERMINAL_JOB_STATES = frozenset({"succeeded", "completed", "degraded", "failed", "interrupted", "superseded"})


def _reusable_job(
    self,
    jobs: list[dict[str, object]],
    idempotency_key: str,
) -> dict[str, object] | None:
    if not idempotency_key:
        return None
    return next(
        (
            item for item in reversed(jobs)
            if item.get("idempotency_key") == idempotency_key
            and item.get("status") in _REUSABLE_JOB_STATES
        ),
        None,
    )
```

In both `submit` and `submit_async`, hold `self._lock` while loading the ledger, calling `_reusable_job(jobs, idempotency_key)`, allocating/appending a new record, and saving it. Return a canonical clone when a reusable record exists. This closes the double-click race instead of doing a lookup and append in separate critical sections. Normalize runner result status against `_TERMINAL_JOB_STATES`.

- [ ] **Step 5: Implement the reanalysis use case**

```python
from dataclasses import dataclass

from rflp_lite.application.workspaces import WorkspaceRef
from rflp_lite.domain.canonical import canonical_hash
from rflp_lite.domain.errors import ContractViolation


@dataclass(frozen=True, slots=True)
class ReanalyzeRequirementsCommand:
    workspace: WorkspaceRef
    mode: str
    delta_region_ids: tuple[str, ...] = ()


class ReanalyzeRequirementsUseCase:
    def __init__(self, dependencies) -> None:
        self.dependencies = dependencies

    def execute(self, command: ReanalyzeRequirementsCommand, model) -> dict[str, object]:
        if command.mode not in {"incremental", "coverage_audit", "full_reanalysis"}:
            raise ContractViolation("未知需求分析模式")
        state = self.dependencies.load_state(command.workspace)
        if not isinstance(state, dict):
            raise ContractViolation("requirements workbench is empty")
        revision = int(state.get("revision", 0))
        content_revision = int(state.get("content_revision", revision))
        scope = state.get("project_scope") if isinstance(state.get("project_scope"), dict) else {}
        input_hash = str(scope.get("input_hash", ""))
        config_hash = canonical_hash({
            "analysis_config": state.get("analysis_config", {}),
            "provider_id": str(getattr(model, "provider_id", "")),
            "model_id": str(getattr(model, "model_id", "")),
        })
        return self.dependencies.runner_factory(command.workspace.path).submit(
            model,
            input_hash=input_hash,
            mode=command.mode,
            snapshot_revision=revision,
            snapshot_content_revision=content_revision,
            analysis_config_hash=config_hash,
            delta_region_ids=command.delta_region_ids,
            idempotency_key=f"{command.workspace.name}:{content_revision}:{command.mode}:{config_hash}",
        )
```

Define a typed dependencies dataclass in `application/use_cases/dependencies.py` with `load_state` and `runner_factory`; wire it in `bootstrap/container.py` and `WebFacade` without importing concrete adapters into the use-case module.

Extend `EnrichmentJobRunner.submit` to persist all named analysis arguments under `job["payload"]` and thread them unchanged into `_execute`; tests must assert mode, both revisions, config hash, delta IDs, input hash, and workspace are visible in the durable Job record.

- [ ] **Step 6: Atomically guard and merge every block**

Do not perform “reload/check” and “save” as separate operations. After an LLM response is strictly validated, open one repository transaction, reload current Workbench, validate its content revision/input hash, reconcile the validated result into that reloaded state, and save. Do this for every block/batch merge, not only once at worker startup:

```python
def _snapshot_is_current(
    self,
    current: dict[str, object],
    snapshot_content_revision: int,
    snapshot_input_hash: str,
) -> bool:
    scope = current.get("project_scope") if isinstance(current.get("project_scope"), dict) else {}
    return (
        int(current.get("content_revision", current.get("revision", 0)))
        == snapshot_content_revision
        and str(scope.get("input_hash", "")) == snapshot_input_hash
    )


def _commit_validated_block(
    self,
    validated: ValidatedBlockResult,
    *,
    snapshot_content_revision: int,
    snapshot_input_hash: str,
) -> dict[str, object] | None:
    repository = self.dependencies.repository_factory(
        self.workspace_path / ".rflp" / "model.db"
    )
    try:
        with repository.transaction():
            current = repository.load_workbench()
            if not isinstance(current, dict):
                raise ContractViolation("requirements workbench is empty")
            if not self._snapshot_is_current(
                current, snapshot_content_revision, snapshot_input_hash
            ):
                return None
            merged = merge_block_result(current, validated)
            repository.save_workbench(
                merged, f"requirements.enriched.{validated.block_id}"
            )
            repository.record_audit("requirements.analysis_block_merged", {
                "block_id": validated.block_id,
                "input_hash": validated.input_hash,
                "output_hash": validated.output_hash,
                "content_revision": snapshot_content_revision,
            })
        return merged
    finally:
        repository.close()


def _supersede(self, job_id: str, block_id: str) -> dict[str, object]:
    diagnostic = {
        "code": "analysis_snapshot_superseded",
        "severity": "warning",
        "block_id": block_id,
        "message": "需求或人工内容已更新，旧分析结果未合并。",
    }
    self.jobs.update(job_id, {"status": "superseded", "active_block": "", "error": diagnostic, "retryable": False})
    return {"status": "superseded", "blocks": dict((self.jobs.get(job_id) or {}).get("blocks", {})), "diagnostics": [diagnostic]}
```

If `_commit_validated_block` returns `None`, return `_supersede(job_id, block_id)` without calling `_save_state`. Build the next block request from the returned merged state so it receives formal IDs. Apply the same transactional guard to the final coverage write and derived-model write. This also prevents two different analysis modes on the same content revision from losing each other's reconciled additions.

Update `retry` and `retry_block` to load the latest Workbench and submit with its current content revision/input hash. If those differ from the failed Job payload, mark that old Job superseded and create the retry against the latest snapshot; never replay a failed block into its stale snapshot.

- [ ] **Step 7: Submit automatic incremental mode with delta IDs**

In `RequirementsAnalysisService.analyze`, compute delta region IDs by comparing pre-merge and post-merge IDs and submit `incremental` through the new use case:

```python
from rflp_lite.application.intelligence.identity import advance_content_revision


before_region_ids = {
    str(item.get("id", ""))
    for item in (current or {}).get("document_regions", ())
    if isinstance(item, dict)
}
before_semantic_hash = canonical_hash({
    "regions": (current or {}).get("document_regions", ()),
    "claims": (current or {}).get("claims", ()),
    "structured_requirements": (current or {}).get("structured_requirements", ()),
})
after_region_ids = {
    str(item.get("id", ""))
    for item in state.get("document_regions", ())
    if isinstance(item, dict)
}
delta_region_ids = tuple(sorted(after_region_ids - before_region_ids))
after_semantic_hash = canonical_hash({
    "regions": state.get("document_regions", ()),
    "claims": state.get("claims", ()),
    "structured_requirements": state.get("structured_requirements", ()),
})
if current is not None and before_semantic_hash == after_semantic_hash:
    return current
state = advance_content_revision(state)
self._save_initial(workspace, state, event)
job = self.dependencies.reanalyze.execute(
    ReanalyzeRequirementsCommand(
        workspace=workspace,
        mode="incremental",
        delta_region_ids=delta_region_ids,
    ),
    model,
)
```

Move the existing `_save_initial` call to the location shown so there is exactly one initial save and the runner reads the incremented content revision. Before submitting an automatic incremental Job, call `advance_content_revision(state)` exactly once after the requirement merge. After incremental reconciliation, run deterministic coverage and process missing blocks in the same durable Job under phase `coverage_audit`. Update `auto_analysis.mode`, `auto_analysis.phase`, `auto_analysis.snapshot_revision`, and `auto_analysis.snapshot_content_revision` whenever the Job state is persisted.

- [ ] **Step 8: Run Job, requirements-analysis, and use-case tests**

Run: `.venv/bin/python -m pytest tests/application/test_jobs_recovery.py tests/application/test_requirements_analysis_service.py tests/application/use_cases/test_reanalyze_requirements.py tests/e2e/test_cross_workspace_and_partial_failure.py -q`

Expected: PASS; stale jobs are superseded, same-revision requests are idempotent, and new requirements still automatically schedule analysis.

- [ ] **Step 9: Commit revision-safe orchestration**

```bash
git add src/rflp_lite/application/use_cases/reanalyze_requirements.py src/rflp_lite/application/use_cases/dependencies.py src/rflp_lite/application/jobs.py src/rflp_lite/application/intelligence/enrichment_jobs.py src/rflp_lite/application/use_cases/requirements_analysis.py src/rflp_lite/bootstrap/container.py tests/application/test_jobs_recovery.py tests/application/test_requirements_analysis_service.py tests/application/use_cases/test_reanalyze_requirements.py tests/e2e/test_cross_workspace_and_partial_failure.py
git commit -m "feat: make requirements analysis revision safe"
```

---

### Task 6: Full Reanalysis Web/API Entry Points and Progress

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-overview.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-input.html`
- Test: `tests/interface/web/test_requirements_enrichment.py`
- Test: `tests/interface/web/test_pages.py`
- Test: `tests/interface/web/test_api_v1.py`

**Interfaces:**
- Consumes: `ReanalyzeRequirementsUseCase` from Task 5.
- Produces: `WebFacade.reanalyze_all_requirements(workspace_name: str) -> dict[str, object]`, Web POST `/w/{workspace_name}/requirements/reanalyze`, and API POST `/api/v1/workspaces/{workspace_name}/requirements/reanalyze`.

- [ ] **Step 1: Write failing Web and API tests**

```python
def test_reanalyze_button_submits_full_project_job(client, monkeypatch) -> None:
    client.post("/w/demo/requirements/analyze", data={"text": "系统应记录故障"})
    wait_for_analysis(client)
    response = client.post("/w/demo/requirements/reanalyze", follow_redirects=False)
    assert response.status_code == 303
    state = client.get("/api/v1/workspaces/demo/requirements").json()["requirements"]
    assert state["auto_analysis"]["mode"] == "full_reanalysis"


def test_reanalyze_api_returns_job(client) -> None:
    client.post("/w/demo/requirements/analyze", data={"text": "系统应记录故障"})
    wait_for_analysis(client)
    response = client.post("/api/v1/workspaces/demo/requirements/reanalyze")
    assert response.status_code == 200
    assert response.json()["job"]["kind"] == "requirements.enrichment"
    assert response.json()["job"]["payload"]["mode"] == "full_reanalysis"
```

- [ ] **Step 2: Run focused Web tests and verify 404 failures**

Run: `.venv/bin/python -m pytest tests/interface/web/test_requirements_enrichment.py tests/interface/web/test_api_v1.py -q`

Expected: FAIL with missing route responses.

- [ ] **Step 3: Add facade and routes**

Implement the facade method as a thin adapter:

```python
def reanalyze_all_requirements(self, workspace_name: str) -> dict[str, object]:
    workspace = self.workspace(workspace_name)
    return self._reanalyze_requirements.execute(
        ReanalyzeRequirementsCommand(workspace=workspace, mode="full_reanalysis"),
        self._project_analysis_model(),
    )
```

The Web route redirects to `/w/{workspace_name}/requirements/input`; the API returns `{"status": "ok", "job": job}`. Both use existing error mapping.

```python
@router.post("/w/{workspace_name}/requirements/reanalyze")
def reanalyze_requirements(request: Request, workspace_name: str) -> Response:
    try:
        _facade(request).reanalyze_all_requirements(workspace_name)
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(
        _requirements_module_location(workspace_name, "input"),
        status_code=303,
    )


@api_v1.post("/workspaces/{workspace_name}/requirements/reanalyze", response_model=None)
def reanalyze_requirements_api(
    request: Request, workspace_name: str
) -> JSONResponse | dict[str, object]:
    try:
        job = _facade(request).reanalyze_all_requirements(workspace_name)
        return {"status": "ok", "job": job}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc)
```

- [ ] **Step 4: Render full-reanalysis control and progress**

Add a visible form with exact copy `重新分析全部需求`. Render `analysis_summary` counts and source progress from the Job/Workbench presenter. Extend polling terminal states to include `superseded`; when superseded, reload so the latest Job is shown.

```html
<form method="post" action="/w/{{ workspace.name }}/requirements/reanalyze">
  <button class="button" type="submit">重新分析全部需求</button>
</form>
{% if state.analysis_summary %}
<span>新增 {{ state.analysis_summary.added or 0 }}</span>
<span>补充 {{ state.analysis_summary.updated or 0 }}</span>
<span>新增关系 {{ state.analysis_summary.related or 0 }}</span>
<span>模型建议 {{ state.analysis_summary.suggested or 0 }}</span>
<span>保持人工删除 {{ state.analysis_summary.suppressed or 0 }}</span>
{% endif %}
```

The presenter must expose `mode_label`, `phase_label`, `source_total`, `source_attempted`, `source_analyzed`, `batch_count`, and the existing block status collection without reading JobService from the template. Label `source_analyzed` as fully completed, not merely attempted.

- [ ] **Step 5: Run Web and page tests**

Run: `.venv/bin/python -m pytest tests/interface/web/test_requirements_enrichment.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py -q`

Expected: PASS; the button is visible, the API returns a Job, polling recognizes superseded, and existing retry-block controls still work.

- [ ] **Step 6: Commit full reanalysis entry points**

```bash
git add src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/presenters.py src/rflp_lite/interface/web/templates/requirements-overview.html src/rflp_lite/interface/web/templates/requirements-input.html tests/interface/web/test_requirements_enrichment.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py
git commit -m "feat: add full requirements reanalysis"
```

---

### Task 7: Always-Editable Stakeholders and Scenarios with User Provenance

**Files:**
- Modify: `src/rflp_lite/application/requirements_workbench.py`
- Modify: `src/rflp_lite/application/scenarios.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-stakeholders.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-review.html`
- Test: `tests/application/test_requirements_workbench.py`
- Test: `tests/application/test_scenarios.py`
- Test: `tests/interface/web/test_pages.py`

**Interfaces:**
- Produces: `edit_stakeholder(state, stakeholder_id, *, name, category, description, goals, interactions, requirement_ids, scenario_ids) -> dict[str, object]`; editable Concern/Need forms on the stakeholder page; updated `add_scenario`/`revise_scenario` fields for `scenario_type`, `coverage_dimensions`, `lifecycle_phase`, `trigger`, `recovery_steps`, and `stakeholder_ids`; and `edit_coverage_decision(...)`, all with user provenance.

- [ ] **Step 1: Write failing edit-provenance tests**

```python
def test_editing_stakeholder_marks_only_changed_fields_as_user() -> None:
    state = analyze_artifact("requirements.txt", "管理员必须恢复系统。".encode())
    item = state["stakeholders"][0]
    edited = edit_stakeholder(
        state,
        item["id"],
        name="现场管理员",
        category="operator",
        description="负责现场运行",
        goals="安全恢复",
        interactions="提交恢复请求",
    )
    current = edited["stakeholders"][0]
    assert current["field_sources"]["name"] == "user"
    assert current["field_sources"]["goals"] == "user"
    assert current["last_editor"] == "user"


def test_editing_llm_scenario_makes_changed_fields_user_authored() -> None:
    state = generate_scenario_drafts(_state())
    scenario = state["scenarios"][0]
    edited = revise_scenario(state, scenario["id"], title="人工标题", scenario_type="recovery", coverage_dimensions=["safety"], lifecycle_phase="operation", description=scenario["description"], trigger="检测到故障", actors=scenario["actors"], stakeholder_ids=[state["stakeholders"][0]["id"]], preconditions=scenario["preconditions"], steps=scenario["steps"], recovery_steps=["恢复服务"], expected_outcomes=scenario["expected_outcomes"], faults=scenario["faults"], requirement_ids=scenario["requirement_ids"])
    assert edited["scenarios"][0]["field_sources"]["title"] == "user"
    assert edited["scenarios"][0]["field_sources"]["scenario_type"] == "user"
    assert edited["scenarios"][0]["recovery_steps"] == ["恢复服务"]
    assert edited["scenarios"][0]["producer"] == scenario["producer"]


def test_editing_coverage_decision_is_a_human_content_change() -> None:
    state = coverage_decision_state()
    edited = edit_coverage_decision(
        state,
        "coverage-decision-1",
        status="rejected",
        rationale="人工判断该场景仍需要分析",
        source_requirement_ids=["req-1"],
    )
    decision = edited["coverage_decisions"][0]
    assert decision["status"] == "rejected"
    assert decision["field_sources"]["status"] == "user"
    assert edited["content_revision"] == state["content_revision"] + 1
```

- [ ] **Step 2: Run edit tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/test_requirements_workbench.py tests/application/test_scenarios.py -q`

Expected: FAIL because stakeholder detail editing and per-field user provenance are missing.

- [ ] **Step 3: Implement stakeholder editing**

Validate the stakeholder ID, normalized category, and non-empty name. Convert multiline goals/interactions to lists. Increment revision, set `last_editor="user"`, update `field_sources` only for submitted fields, append the old name to aliases when renamed, refresh match keys, and invalidate RFLP/MBSE/baseline using the existing derived-model invalidation helper. Extend `_invalidate_derived_model` to set `analysis_coverage={}` as well, because any human entity edit makes the previous completeness audit stale.

```python
def edit_stakeholder(
    state: dict[str, object],
    stakeholder_id: str,
    *,
    name: str,
    category: str,
    description: str = "",
    goals: str | list[str] | tuple[str, ...] = (),
    interactions: str | list[str] | tuple[str, ...] = (),
    requirement_ids: str | list[str] | tuple[str, ...] = (),
    scenario_ids: str | list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    result = ensure_workbench_metadata(state)
    item = next(
        (value for value in result.get("stakeholders", ()) if value.get("id") == stakeholder_id),
        None,
    )
    if item is None:
        raise ContractViolation("利益相关方不存在")
    clean_name = str(name).strip()
    if not clean_name:
        raise ContractViolation("利益相关方名称不能为空")
    old_name = str(item.get("name", "")).strip()
    values = {
        "name": clean_name,
        "category": normalize_stakeholder_category(category, clean_name),
        "description": str(description).strip(),
        "goals": _lines(goals),
        "interactions": _lines(interactions),
    }
    aliases = set(str(value) for value in item.get("aliases", ()) if str(value).strip())
    if old_name and old_name != clean_name:
        aliases.add(old_name)
    item.update(values)
    item["aliases"] = sorted(aliases)
    item["revision"] = int(item.get("revision", 1)) + 1
    item["last_editor"] = "user"
    sources = dict(item.get("field_sources") or {})
    sources.update({field: "user" for field in values})
    item["field_sources"] = sources
    suggestion_history = list(item.get("suggestion_history", ()))
    remaining_suggestions = []
    for suggestion in item.get("suggested_changes", ()):
        field = str(suggestion.get("field", ""))
        if field in values and values[field] == suggestion.get("suggested"):
            suggestion_history.append({**suggestion, "status": "accepted_by_user"})
        else:
            remaining_suggestions.append(suggestion)
    item["suggested_changes"] = remaining_suggestions
    item["suggestion_history"] = suggestion_history
    item["match_keys"] = sorted(
        set(item.get("match_keys", ()))
        | set(entity_match_keys("stakeholder", item))
    )
    selected_requirements = set(_lines(requirement_ids))
    selected_scenarios = set(_lines(scenario_ids))
    known_requirements = {str(value.get("id", "")) for value in result.get("claims", ())}
    known_scenarios = {str(value.get("id", "")) for value in result.get("scenarios", ())}
    if selected_requirements - known_requirements or selected_scenarios - known_scenarios:
        raise ContractViolation("利益相关方关联了不存在的需求或场景")
    for claim in result.get("claims", ()):
        if claim.get("stakeholder_id") == stakeholder_id or claim.get("id") in selected_requirements:
            claim["stakeholder_id"] = (
                stakeholder_id if claim.get("id") in selected_requirements else ""
            )
            claim["field_sources"] = {
                **dict(claim.get("field_sources") or {}),
                "stakeholder_id": "user",
            }
    for scenario in result.get("scenarios", ()):
        stakeholder_ids = set(str(value) for value in scenario.get("stakeholder_ids", ()))
        if scenario.get("id") in selected_scenarios:
            stakeholder_ids.add(stakeholder_id)
        else:
            stakeholder_ids.discard(stakeholder_id)
        scenario["stakeholder_ids"] = sorted(stakeholder_ids)
        scenario["field_sources"] = {
            **dict(scenario.get("field_sources") or {}),
            "stakeholder_ids": "user",
        }
    _invalidate_derived_model(result)
    result["analysis_coverage"] = {}
    return advance_content_revision(result)
```

Apply the same provenance rule to existing manual review and creation paths. In `add_stakeholder`, wrap the newly built item with `ensure_entity_metadata("stakeholder", item, editor="user")` and return `advance_content_revision(result)` only when a new item was actually added. In `review_item`, mark the edited value field, `status`, and stakeholder `category`/`category_label` (when applicable) as `user` in `field_sources`, set `last_editor="user"`, increment the entity revision, invalidate derived artifacts, and return `advance_content_revision(sync_review_queue(result))`. A no-op duplicate add returns unchanged content revision.

- [ ] **Step 4: Make scenario edits user-authored without changing ownership**

Keep the existing `producer` for provenance, but set `last_editor="user"` and mark each form field in `field_sources` as `user`. Preserve `scenario_type`, dimensions, lifecycle phase, generated source, ID, and review history. Continue validating Requirement IDs.

Add this after `updated` receives preserved generated metadata in `revise_scenario`:

```python
editable_fields = (
    "title", "scenario_type", "coverage_dimensions", "lifecycle_phase",
    "description", "trigger", "actors",
    "stakeholder_ids", "preconditions", "steps", "recovery_steps",
    "expected_outcomes", "faults", "requirement_ids",
)
updated["last_editor"] = "user"
updated["field_sources"] = {
    **dict(existing.get("field_sources") or {}),
    **{field: "user" for field in editable_fields},
}
updated["suggested_changes"] = list(existing.get("suggested_changes", ()))
updated["aliases"] = list(existing.get("aliases", ()))
updated["match_keys"] = sorted(
    set(existing.get("match_keys", ()))
    | set(entity_match_keys("scenario", updated))
)
```

Extend `build_scenario`, `add_scenario`, and `revise_scenario` to accept those fields. Validate `scenario_type`, `coverage_dimensions`, and `lifecycle_phase` against core/configured values; validate every `stakeholder_id` and Requirement ID against the current Workbench; normalize multiline values; and preserve generated dimension metadata not represented by an editable field. Run the same suggestion-resolution loop shown for stakeholders against the scenario's `editable_fields`: move a suggestion to `suggestion_history` with `status="accepted_by_user"` only when the submitted field equals its suggested value, and leave unrelated suggestions pending. After replacing the scenario in `result` and invalidating derived artifacts, return `advance_content_revision(result)`. Review-only status changes that are explicitly made by a human must do the same; automatic draft generation and LLM reconciliation must not.

In `add_scenario`, initialize every editable field with source `user` and advance content revision only after successful insertion. In `review_scenario`, mark `status` as user-authored, retain the review history, invalidate derived artifacts, and advance content revision. This gives manual create/edit/review the same stale-Job protection as stakeholder editing.

Add an editable coverage-decision policy in `requirements_workbench.py`:

```python
def edit_coverage_decision(
    state: dict[str, object],
    decision_id: str,
    *,
    status: str,
    rationale: str,
    source_requirement_ids: str | list[str] | tuple[str, ...],
) -> dict[str, object]:
    if status not in {"not_applicable", "rejected"}:
        raise ContractViolation("覆盖判定状态无效")
    result = ensure_workbench_metadata(state)
    decision = next(
        (item for item in result.get("coverage_decisions", ()) if item.get("id") == decision_id),
        None,
    )
    if decision is None:
        raise ContractViolation("覆盖判定不存在")
    requirement_ids = _lines(source_requirement_ids)
    known = {str(item.get("id", "")) for item in result.get("claims", ())}
    if not rationale.strip() or not requirement_ids or set(requirement_ids) - known:
        raise ContractViolation("覆盖判定必须有理由和有效需求依据")
    values = {
        "status": status,
        "rationale": rationale.strip(),
        "source_requirement_ids": requirement_ids,
    }
    decision.update(values)
    decision["last_editor"] = "user"
    decision["revision"] = int(decision.get("revision", 1)) + 1
    decision["field_sources"] = {
        **dict(decision.get("field_sources") or {}),
        **{field: "user" for field in values},
    }
    result["analysis_coverage"] = {}
    return advance_content_revision(result)
```

- [ ] **Step 5: Add stakeholder edit Web/API forms**

Add `POST /w/{workspace}/requirements/stakeholders/edit` and API `POST /api/v1/workspaces/{workspace}/requirements/stakeholders/{stakeholder_id}`. Render editable name, category, description, goals, interactions, associated Requirement checkboxes, and associated scenario checkboxes on the stakeholder detail page. Render each associated Concern and Need with the existing review endpoint's editable value/status form directly in this page, so users do not have to leave the selected stakeholder context. Keep every scenario field listed above editable and show `last_editor` plus revision.

```python
@router.post("/w/{workspace_name}/requirements/stakeholders/edit")
def edit_requirement_stakeholder(
    request: Request,
    workspace_name: str,
    stakeholder_id: Annotated[str, Form()],
    name: Annotated[str, Form()],
    category: Annotated[str, Form()] = "other",
    description: Annotated[str, Form()] = "",
    goals: Annotated[str, Form()] = "",
    interactions: Annotated[str, Form()] = "",
    requirement_ids: Annotated[list[str] | None, Form()] = None,
    scenario_ids: Annotated[list[str] | None, Form()] = None,
) -> Response:
    try:
        _facade(request).edit_requirement_stakeholder(
            workspace_name,
            stakeholder_id,
            name=name,
            category=category,
            description=description,
            goals=goals,
            interactions=interactions,
            requirement_ids=requirement_ids or [],
            scenario_ids=scenario_ids or [],
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(
        _requirements_module_location(workspace_name, "stakeholders") + "?name=" + quote(name.strip()),
        status_code=303,
    )
```

The API parses the same eight stakeholder fields from JSON and returns `{"status": "ok", "requirements": state}`. Extend the existing scenario Web/API routes with `scenario_type`, `coverage_dimensions`, `lifecycle_phase`, `trigger`, `stakeholder_ids`, and `recovery_steps`. Add Web/API POST routes for coverage-decision edit and render those decisions on `requirements-review.html`. Templates post all editable fields, including empty lists, so a human can intentionally clear a machine-generated value.

- [ ] **Step 6: Run application and Web edit tests**

Run: `.venv/bin/python -m pytest tests/application/test_requirements_workbench.py tests/application/test_scenarios.py tests/interface/web/test_pages.py -q`

Expected: PASS; user edits survive a subsequent reconciliation fixture and all fields remain editable.

- [ ] **Step 7: Commit editable entity provenance**

```bash
git add src/rflp_lite/application/requirements_workbench.py src/rflp_lite/application/scenarios.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/templates/requirements-stakeholders.html src/rflp_lite/interface/web/templates/requirements-scenarios.html src/rflp_lite/interface/web/templates/requirements-review.html tests/application/test_requirements_workbench.py tests/application/test_scenarios.py tests/interface/web/test_pages.py
git commit -m "feat: keep analyzed entities human editable"
```

---

### Task 8: Human Delete Preview, Suppression Registry, and Restore

**Files:**
- Create: `src/rflp_lite/application/entity_deletion.py`
- Create: `src/rflp_lite/application/use_cases/manage_analysis_entity.py`
- Modify: `src/rflp_lite/application/use_cases/dependencies.py`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Test: `tests/application/test_entity_deletion.py`
- Test: `tests/application/use_cases/test_manage_analysis_entity.py`

**Interfaces:**
- Produces: `preview_entity_deletion(state, entity_type, entity_id) -> dict[str, object]`, `delete_entity(state, entity_type, entity_id, plan_hash) -> dict[str, object]`, `restore_entity(state, entity_type, entity_id) -> dict[str, object]`, and use-case commands that persist each transition transactionally.

- [ ] **Step 1: Write failing deletion tests**

```python
def test_delete_preview_lists_dependencies_without_mutating_state() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "stakeholder", "st-1")
    assert preview["target"]["id"] == "st-1"
    assert preview["affected"]["concern_ids"] == ["concern-1"]
    assert state["stakeholders"][0]["id"] == "st-1"


def test_human_delete_creates_recoverable_suppression_record() -> None:
    state = linked_stakeholder_state()
    preview = preview_entity_deletion(state, "stakeholder", "st-1")
    deleted = delete_entity(state, "stakeholder", "st-1", preview["plan_hash"])
    assert deleted["stakeholders"] == []
    assert deleted["content_revision"] == int(state.get("content_revision", state.get("revision", 0))) + 1
    assert deleted["deletion_registry"][0]["entity_id"] == "st-1"
    restored = restore_entity(deleted, "stakeholder", "st-1")
    assert restored["stakeholders"][0]["id"] == "st-1"
    assert restored["concerns"][0]["id"] == "concern-1"
    assert restored["needs"][0]["id"] == "need-1"
    assert restored["content_revision"] == deleted["content_revision"] + 1
    assert restored["deletion_registry"] == []
```

- [ ] **Step 2: Run deletion tests and verify failure**

Run: `.venv/bin/python -m pytest tests/application/test_entity_deletion.py tests/application/use_cases/test_manage_analysis_entity.py -q`

Expected: FAIL because deletion preview and restore services are missing.

- [ ] **Step 3: Implement deterministic deletion plans**

The preview must include the target snapshot, affected IDs by group, relations to remove, references to detach, and a `plan_hash=canonical_hash(plan_without_hash)`. `delete_entity` must recompute the preview from current state and reject a stale hash. It then removes exactly the displayed targets/references, appends a deletion-registry entry with the target snapshot and impact, invalidates derived models, and never processes a model-generated delete operation.

Use one generic entity map:

```python
_ENTITY_GROUPS = {
    "stakeholder": "stakeholders",
    "requirement": "claims",
    "scenario": "scenarios",
}
_GROUP_ENTITY_TYPES = {
    "stakeholders": "stakeholder",
    "concerns": "concern",
    "needs": "need",
    "claims": "requirement",
    "structured_requirements": "requirement",
    "scenarios": "scenario",
}
```

The first implementation deliberately supports the three user-facing delete targets already present in the product: stakeholder, requirement, and scenario. Concern/Need remain editable/reviewable but are deleted only as previewed stakeholder dependencies; do not expose a half-correct direct Concern/Need delete. For stakeholder deletion, the plan removes that stakeholder and its exclusively machine-owned Concern/Need objects, detaches its name/ID from scenarios, and preserves requirements. Manually edited dependent objects remain with a `review_hint` instead of being silently removed. Requirement deletion removes both the Claim and same-ID structured Requirement view, detaches its ID from scenarios, and preserves the affected records in recovery data. Scenario deletion removes only that scenario plus its trace relations.

Implement the core preview and delete functions without accepting arbitrary group names:

```python
from __future__ import annotations

import json

from rflp_lite.application.intelligence.identity import (
    advance_content_revision,
    ensure_entity_metadata,
)
from rflp_lite.domain.canonical import canonical_hash, canonical_json
from rflp_lite.domain.errors import ContractViolation


def _clone(value: dict[str, object]) -> dict[str, object]:
    return json.loads(canonical_json(value))


def preview_entity_deletion(
    state: dict[str, object], entity_type: str, entity_id: str
) -> dict[str, object]:
    group = _ENTITY_GROUPS.get(entity_type)
    if group is None:
        raise ContractViolation("不支持删除该对象类型")
    target = next(
        (item for item in state.get(group, ()) if isinstance(item, dict) and item.get("id") == entity_id),
        None,
    )
    if target is None:
        raise ContractViolation("待删除对象不存在")
    concern_ids: set[str] = set()
    need_ids: set[str] = set()
    if entity_type == "stakeholder":
        concern_ids = {
            str(item["id"])
            for item in state.get("concerns", ())
            if isinstance(item, dict) and item.get("stakeholder_id") == entity_id
        }
        need_ids = {
            str(item["id"])
            for item in state.get("needs", ())
            if isinstance(item, dict) and item.get("stakeholder_id") == entity_id
        }
    removed_entity_ids = {entity_id}
    if entity_type == "stakeholder":
        removed_entity_ids.update(
            str(item["id"])
            for dependent_group in ("concerns", "needs")
            for item in state.get(dependent_group, ())
            if isinstance(item, dict)
            and item.get("stakeholder_id") == entity_id
            and item.get("last_editor") != "user"
        )
    affected = {
        "concern_ids": sorted(concern_ids),
        "need_ids": sorted(need_ids),
        "scenario_ids": sorted(
            str(item["id"])
            for item in state.get("scenarios", ())
            if isinstance(item, dict)
            and (
                (
                    entity_type == "stakeholder"
                    and (
                        entity_id in item.get("stakeholder_ids", ())
                        or target.get("name") in item.get("actors", ())
                    )
                )
                or (
                    entity_type == "requirement"
                    and entity_id in item.get("requirement_ids", ())
                )
            )
        ),
        "relation_ids": sorted(
            str(item.get("id", ""))
            for item in state.get("trace_links", ())
            if isinstance(item, dict)
            and removed_entity_ids.intersection(
                {str(item.get("source_id", "")), str(item.get("target_id", ""))}
            )
        ),
    }
    removed_snapshots: dict[str, list[dict[str, object]]] = {
        group: [dict(target)]
    }
    if entity_type == "stakeholder":
        removed_snapshots["concerns"] = [
            dict(item)
            for item in state.get("concerns", ())
            if isinstance(item, dict)
            and item.get("stakeholder_id") == entity_id
            and item.get("last_editor") != "user"
        ]
        removed_snapshots["needs"] = [
            dict(item)
            for item in state.get("needs", ())
            if isinstance(item, dict)
            and item.get("stakeholder_id") == entity_id
            and item.get("last_editor") != "user"
        ]
    if entity_type == "requirement":
        removed_snapshots["structured_requirements"] = [
            dict(item)
            for item in state.get("structured_requirements", ())
            if isinstance(item, dict) and item.get("id") == entity_id
        ]
    recovery = {
        "removed_snapshots": removed_snapshots,
        "scenario_references": [
            {
                "id": str(item["id"]),
                "stakeholder_ids": list(item.get("stakeholder_ids", ())),
                "actors": list(item.get("actors", ())),
                "requirement_ids": list(item.get("requirement_ids", ())),
                "field_sources": dict(item.get("field_sources") or {}),
            }
            for item in state.get("scenarios", ())
            if isinstance(item, dict) and str(item.get("id", "")) in affected["scenario_ids"]
        ],
        "dependent_references": [
            {
                "group": dependent_group,
                "id": str(item["id"]),
                "stakeholder_id": str(item.get("stakeholder_id", "")),
                "review_hint": str(item.get("review_hint", "")),
            }
            for dependent_group in ("concerns", "needs")
            for item in state.get(dependent_group, ())
            if entity_type == "stakeholder"
            and isinstance(item, dict)
            and item.get("stakeholder_id") == entity_id
            and item.get("last_editor") == "user"
        ],
        "trace_links": [
            dict(item)
            for item in state.get("trace_links", ())
            if isinstance(item, dict)
            and str(item.get("id", "")) in affected["relation_ids"]
        ],
    }
    plan = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "target": dict(target),
        "affected": affected,
        "recovery": recovery,
        "base_content_revision": int(
            state.get("content_revision", state.get("revision", 0))
        ),
    }
    return {**plan, "plan_hash": canonical_hash(plan)}


def delete_entity(
    state: dict[str, object],
    entity_type: str,
    entity_id: str,
    plan_hash: str,
) -> dict[str, object]:
    preview = preview_entity_deletion(state, entity_type, entity_id)
    if str(preview["plan_hash"]) != str(plan_hash):
        raise ContractViolation("删除影响已经变化，请重新预览")
    result = _clone(state)
    group = _ENTITY_GROUPS[entity_type]
    result[group] = [item for item in result.get(group, ()) if item.get("id") != entity_id]
    affected = preview["affected"]
    if entity_type == "stakeholder":
        for dependent_group, affected_key in (("concerns", "concern_ids"), ("needs", "need_ids")):
            retained: list[dict[str, object]] = []
            affected_ids = set(affected[affected_key])
            for item in result.get(dependent_group, ()):
                if item.get("id") not in affected_ids:
                    retained.append(item)
                    continue
                if item.get("last_editor") == "user":
                    item["stakeholder_id"] = ""
                    item["review_hint"] = "原利益相关方已由人工删除，请重新关联"
                    retained.append(item)
            result[dependent_group] = retained
        for scenario in result.get("scenarios", ()):
            scenario["stakeholder_ids"] = [value for value in scenario.get("stakeholder_ids", ()) if value != entity_id]
            scenario["actors"] = [value for value in scenario.get("actors", ()) if value != preview["target"].get("name")]
    elif entity_type == "requirement":
        result["structured_requirements"] = [
            item
            for item in result.get("structured_requirements", ())
            if item.get("id") != entity_id
        ]
        for scenario in result.get("scenarios", ()):
            scenario["requirement_ids"] = [
                value for value in scenario.get("requirement_ids", ())
                if value != entity_id
            ]
    removed_ids = {
        str(snapshot.get("id", ""))
        for snapshots in preview["recovery"]["removed_snapshots"].values()
        for snapshot in snapshots
    }
    result["trace_links"] = [
        item for item in result.get("trace_links", ())
        if not removed_ids.intersection(
            {str(item.get("source_id", "")), str(item.get("target_id", ""))}
        )
    ]
    registry = list(result.get("deletion_registry", ()))
    registry.append({
        "entity_id": entity_id,
        "entity_type": entity_type,
        "match_keys": list(preview["target"].get("match_keys", ())),
        "deleted_revision": int(state.get("revision", 0)),
        "deleted_by": "user",
        "snapshot": dict(preview["target"]),
        "impact": dict(affected),
        "recovery": dict(preview["recovery"]),
    })
    result["deletion_registry"] = registry
    result["rflp"], result["mbse"], result["baseline"] = None, None, None
    result["coverage"], result["analysis_coverage"] = {}, {}
    result["svg"], result["draft_graph"] = "", None
    return advance_content_revision(result)
```

Before removing dependent Concern/Need items, convert any `last_editor="user"` dependent into an unassigned record with `review_hint="原利益相关方已由人工删除，请重新关联"`; the test fixture must cover this branch.

- [ ] **Step 4: Implement restoration**

Restore the target snapshot under the original ID, remove its deletion-registry entry, reconcile surviving references, increment Workbench revision through repository save, and record `entity.restored`. If an active object already owns the same match key, merge the restored snapshot into that object and preserve user fields instead of creating a duplicate.

```python
def restore_entity(
    state: dict[str, object], entity_type: str, entity_id: str
) -> dict[str, object]:
    result = _clone(state)
    group = _ENTITY_GROUPS.get(entity_type)
    if group is None:
        raise ContractViolation("不支持恢复该对象类型")
    record = next(
        (
            item for item in result.get("deletion_registry", ())
            if item.get("entity_type") == entity_type and item.get("entity_id") == entity_id
        ),
        None,
    )
    if record is None:
        if any(item.get("id") == entity_id for item in result.get(group, ())):
            return result
        raise ContractViolation("已删除对象不存在")
    recovery = dict(record.get("recovery") or {})
    removed = recovery.get("removed_snapshots")
    removed_snapshots = removed if isinstance(removed, dict) else {
        group: [dict(record.get("snapshot") or {})]
    }
    for recovery_group, snapshots in removed_snapshots.items():
        if recovery_group not in _GROUP_ENTITY_TYPES:
            continue
        current_items = list(result.get(recovery_group, ()))
        for raw_snapshot in snapshots if isinstance(snapshots, list) else ():
            snapshot = ensure_entity_metadata(
                _GROUP_ENTITY_TYPES[recovery_group], raw_snapshot
            )
            keys = set(snapshot.get("match_keys", ()))
            existing = next(
                (
                    item for item in current_items
                    if item.get("id") == snapshot.get("id")
                    or keys.intersection(str(value) for value in item.get("match_keys", ()))
                ),
                None,
            )
            if existing is None:
                current_items.append(snapshot)
            else:
                for field, value in snapshot.items():
                    if dict(existing.get("field_sources") or {}).get(field) != "user":
                        existing[field] = value
        result[recovery_group] = sorted(
            current_items, key=lambda item: str(item.get("id", ""))
        )
    for patch in recovery.get("scenario_references", ()):
        scenario = next(
            (item for item in result.get("scenarios", ()) if item.get("id") == patch.get("id")),
            None,
        )
        if scenario is None:
            continue
        sources = dict(scenario.get("field_sources") or {})
        for field in ("stakeholder_ids", "actors", "requirement_ids"):
            if sources.get(field) == "user":
                continue
            scenario[field] = sorted(
                set(str(value) for value in scenario.get(field, ()))
                | set(str(value) for value in patch.get(field, ()))
            )
    for patch in recovery.get("dependent_references", ()):
        dependent = next(
            (
                item for item in result.get(str(patch.get("group", "")), ())
                if item.get("id") == patch.get("id")
            ),
            None,
        )
        if dependent is not None and not dependent.get("stakeholder_id"):
            dependent["stakeholder_id"] = patch.get("stakeholder_id", "")
            dependent["review_hint"] = patch.get("review_hint", "")
    existing_relation_keys = {
        (item.get("source_id"), item.get("predicate"), item.get("target_id"))
        for item in result.get("trace_links", ())
    }
    for relation in recovery.get("trace_links", ()):
        key = (
            relation.get("source_id"),
            relation.get("predicate"),
            relation.get("target_id"),
        )
        if key not in existing_relation_keys:
            result.setdefault("trace_links", []).append(dict(relation))
            existing_relation_keys.add(key)
    result["deletion_registry"] = [
        item
        for item in result.get("deletion_registry", ())
        if not (
            item.get("entity_type") == entity_type
            and item.get("entity_id") == entity_id
        )
    ]
    result["rflp"], result["mbse"], result["baseline"] = None, None, None
    result["coverage"], result["analysis_coverage"] = {}, {}
    result["svg"], result["draft_graph"] = "", None
    return advance_content_revision(result)
```

- [ ] **Step 5: Add transactional use cases**

Create command dataclasses `PreviewEntityDeletionCommand`, `DeleteEntityCommand`, and `RestoreEntityCommand`. Preview is read-only. Delete and restore run inside `repository.transaction()`, save the Workbench with events `entity.deleted` or `entity.restored`, and record the target ID, entity type, plan hash, and affected IDs in audit.

```python
@dataclass(frozen=True, slots=True)
class DeleteEntityCommand:
    entity_type: str
    entity_id: str
    plan_hash: str


class DeleteEntityUseCase:
    def __init__(self, repository) -> None:
        self.repository = repository

    def execute(self, command: DeleteEntityCommand) -> dict[str, object]:
        with self.repository.transaction():
            state = self.repository.load_workbench()
            if not isinstance(state, dict):
                raise ContractViolation("requirements workbench is empty")
            preview = preview_entity_deletion(
                state, command.entity_type, command.entity_id
            )
            updated = delete_entity(
                state,
                command.entity_type,
                command.entity_id,
                command.plan_hash,
            )
            self.repository.save_workbench(updated, "entity.deleted")
            self.repository.record_audit("entity.deleted", {
                "entity_type": command.entity_type,
                "entity_id": command.entity_id,
                "plan_hash": command.plan_hash,
                "affected": preview["affected"],
            })
        return updated
```

Implement preview and restore with the same explicit repository boundary:

```python
@dataclass(frozen=True, slots=True)
class PreviewEntityDeletionCommand:
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class RestoreEntityCommand:
    entity_type: str
    entity_id: str


class PreviewEntityDeletionUseCase:
    def __init__(self, repository) -> None:
        self.repository = repository

    def execute(
        self, command: PreviewEntityDeletionCommand
    ) -> dict[str, object]:
        state = self.repository.load_workbench()
        if not isinstance(state, dict):
            raise ContractViolation("requirements workbench is empty")
        return preview_entity_deletion(
            state, command.entity_type, command.entity_id
        )


class RestoreEntityUseCase:
    def __init__(self, repository) -> None:
        self.repository = repository

    def execute(self, command: RestoreEntityCommand) -> dict[str, object]:
        with self.repository.transaction():
            state = self.repository.load_workbench()
            if not isinstance(state, dict):
                raise ContractViolation("requirements workbench is empty")
            record = next(
                (
                    item for item in state.get("deletion_registry", ())
                    if item.get("entity_type") == command.entity_type
                    and item.get("entity_id") == command.entity_id
                ),
                None,
            )
            updated = restore_entity(
                state, command.entity_type, command.entity_id
            )
            if record is not None:
                self.repository.save_workbench(updated, "entity.restored")
                self.repository.record_audit("entity.restored", {
                    "entity_type": command.entity_type,
                    "entity_id": command.entity_id,
                    "affected": dict(record.get("impact") or {}),
                })
        return updated
```

Repository construction and close remain in the facade/composition boundary, matching existing requirement review use cases. The idempotent early-return restore does not write another revision or duplicate audit event.

- [ ] **Step 6: Run deletion and use-case tests**

Run: `.venv/bin/python -m pytest tests/application/test_entity_deletion.py tests/application/use_cases/test_manage_analysis_entity.py -q`

Expected: PASS; stale plans fail, deletion is recoverable, and restoration is idempotent.

- [ ] **Step 7: Commit human deletion domain support**

```bash
git add src/rflp_lite/application/entity_deletion.py src/rflp_lite/application/use_cases/manage_analysis_entity.py src/rflp_lite/application/use_cases/dependencies.py src/rflp_lite/bootstrap/container.py src/rflp_lite/application/web_facade.py tests/application/test_entity_deletion.py tests/application/use_cases/test_manage_analysis_entity.py
git commit -m "feat: add recoverable human entity deletion"
```

---

### Task 9: Delete/Restore UI, Suggestions, and Audit Visibility

**Files:**
- Modify: `src/rflp_lite/application/scenarios.py`
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/api_v1.py`
- Modify: `src/rflp_lite/interface/web/presenters.py`
- Modify: `src/rflp_lite/interface/web/templates/requirements-stakeholders.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-scenarios.html`
- Modify: `src/rflp_lite/interface/web/templates/requirements-review.html`
- Modify: `src/rflp_lite/interface/web/templates/project-management.html`
- Modify: `src/rflp_lite/interface/web/static/app.css`
- Test: `tests/interface/web/test_pages.py`
- Test: `tests/interface/web/test_api_v1.py`
- Test: `tests/application/test_scenarios.py`
- Test: `tests/e2e/test_professional_mbse_workflow.py`

**Interfaces:**
- Consumes: management use cases from Task 8 and `suggested_changes` from Task 2.
- Produces: delete preview/delete/restore Web and API endpoints plus visible suggestion and deletion history controls.

- [ ] **Step 1: Write failing delete/restore route tests**

```python
def test_stakeholder_delete_requires_preview_hash(client) -> None:
    stakeholder_id = create_stakeholder(client)
    preview = client.post(
        f"/api/v1/workspaces/demo/requirements/entities/stakeholder/{stakeholder_id}/delete-preview"
    )
    assert preview.status_code == 200
    plan_hash = preview.json()["preview"]["plan_hash"]
    deleted = client.post(
        f"/api/v1/workspaces/demo/requirements/entities/stakeholder/{stakeholder_id}/delete",
        json={"plan_hash": plan_hash},
    )
    assert deleted.status_code == 200
    restored = client.post(
        f"/api/v1/workspaces/demo/requirements/entities/stakeholder/{stakeholder_id}/restore"
    )
    assert restored.status_code == 200


def test_entity_page_shows_model_suggestion_without_overwriting_value(client) -> None:
    state = seed_user_edited_stakeholder_with_suggestion(client)
    page = client.get("/w/demo/requirements/stakeholders")
    assert state["stakeholders"][0]["name"] in page.text
    assert "模型建议" in page.text
    assert "版本与来源" in page.text
```

- [ ] **Step 2: Run Web tests and verify missing routes**

Run: `.venv/bin/python -m pytest tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py -q`

Expected: FAIL with 404 responses for deletion management routes.

- [ ] **Step 3: Add Web and API deletion routes**

Expose these thin facade methods, each opening the selected workspace repository, executing the Task 8 use case, and closing the repository in `finally`:

```python
def preview_requirement_entity_deletion(
    self, workspace_name: str, entity_type: str, entity_id: str
) -> dict[str, object]:
    repository = self.dependencies.repository_factory(
        self.workspace(workspace_name).path / ".rflp" / "model.db"
    )
    try:
        return PreviewEntityDeletionUseCase(repository).execute(
            PreviewEntityDeletionCommand(entity_type, entity_id)
        )
    finally:
        repository.close()

def delete_requirement_entity(
    self, workspace_name: str, entity_type: str, entity_id: str, plan_hash: str
) -> dict[str, object]:
    repository = self.dependencies.repository_factory(
        self.workspace(workspace_name).path / ".rflp" / "model.db"
    )
    try:
        return DeleteEntityUseCase(repository).execute(
            DeleteEntityCommand(entity_type, entity_id, plan_hash)
        )
    finally:
        repository.close()

def restore_requirement_entity(
    self, workspace_name: str, entity_type: str, entity_id: str
) -> dict[str, object]:
    repository = self.dependencies.repository_factory(
        self.workspace(workspace_name).path / ".rflp" / "model.db"
    )
    try:
        return RestoreEntityUseCase(repository).execute(
            RestoreEntityCommand(entity_type, entity_id)
        )
    finally:
        repository.close()
```

Add the three API endpoints with literal response envelopes:

```python
@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/delete-preview",
    response_model=None,
)
def preview_analysis_entity_deletion(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        preview = _facade(request).preview_requirement_entity_deletion(
            workspace_name, entity_type, entity_id
        )
        return {"status": "ok", "preview": preview}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/delete",
    response_model=None,
)
async def delete_analysis_entity(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        payload = await request.json()
        if not isinstance(payload, dict) or not str(payload.get("plan_hash", "")):
            raise ContractViolation("删除前必须提供影响预览哈希")
        state = _facade(request).delete_requirement_entity(
            workspace_name, entity_type, entity_id, str(payload["plan_hash"])
        )
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError, ValueError) as exc:
        return _error(exc)


@api_v1.post(
    "/workspaces/{workspace_name}/requirements/entities/{entity_type}/{entity_id}/restore",
    response_model=None,
)
def restore_analysis_entity(
    request: Request, workspace_name: str, entity_type: str, entity_id: str
) -> JSONResponse | dict[str, object]:
    try:
        state = _facade(request).restore_requirement_entity(
            workspace_name, entity_type, entity_id
        )
        return {"status": "ok", "requirements": state}
    except (ContractViolation, RflpError, OSError) as exc:
        return _error(exc, 404)
```

Replace the current irreversible scenario and requirement delete routes with these three generic POST-only Web routes. Remove `WebFacade.delete_requirement_scenario`, `WebFacade.delete_requirement`, and the direct `delete_scenario` application function after all callers/tests use previewed deletion. Never accept a template name or redirect destination from form data; derive the module from the validated entity type:

```python
_ENTITY_MODULES = {
    "stakeholder": ("stakeholders", "requirements-stakeholders.html"),
    "scenario": ("scenarios", "requirements-scenarios.html"),
    "requirement": ("review", "requirements-review.html"),
}


def _entity_module(entity_type: str) -> tuple[str, str]:
    try:
        return _ENTITY_MODULES[entity_type]
    except KeyError as exc:
        raise ContractViolation("不支持管理该对象类型") from exc


@router.post("/w/{workspace_name}/requirements/entities/delete-preview")
def preview_requirement_entity_delete(
    request: Request,
    workspace_name: str,
    entity_type: Annotated[str, Form()],
    entity_id: Annotated[str, Form()],
) -> Response:
    try:
        module, template_name = _entity_module(entity_type)
        preview = _facade(request).preview_requirement_entity_deletion(
            workspace_name, entity_type, entity_id
        )
        context = _requirements_context(
            request, workspace_name, f"requirements-{module}"
        )
        context["delete_preview"] = present_delete_preview(
            preview, context.get("state") or {}
        )
        return templates.TemplateResponse(
            request=request, name=template_name, context=context
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)


@router.post("/w/{workspace_name}/requirements/entities/delete")
def delete_requirement_entity_route(
    request: Request,
    workspace_name: str,
    entity_type: Annotated[str, Form()],
    entity_id: Annotated[str, Form()],
    plan_hash: Annotated[str, Form()],
) -> Response:
    try:
        module, _ = _entity_module(entity_type)
        _facade(request).delete_requirement_entity(
            workspace_name, entity_type, entity_id, plan_hash
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(
        _requirements_module_location(workspace_name, module), status_code=303
    )


@router.post("/w/{workspace_name}/requirements/entities/restore")
def restore_requirement_entity_route(
    request: Request,
    workspace_name: str,
    entity_type: Annotated[str, Form()],
    entity_id: Annotated[str, Form()],
) -> Response:
    try:
        module, _ = _entity_module(entity_type)
        _facade(request).restore_requirement_entity(
            workspace_name, entity_type, entity_id
        )
    except (ContractViolation, RflpError, OSError) as exc:
        return _run_error(request, exc)
    return RedirectResponse(
        _requirements_module_location(workspace_name, module), status_code=303
    )
```

- [ ] **Step 4: Render deletion and suggestion controls**

Add `present_delete_preview(preview, state)` in `presenters.py`. It resolves IDs to human-readable labels and returns `target_label`, `affected_groups`, `entity_type`, `entity_id`, and `plan_hash`; it must preserve the raw IDs beside labels for auditability.

In stakeholder and scenario details, replace direct deletion with a preview form:

```html
<form method="post" action="/w/{{ workspace.name }}/requirements/entities/delete-preview">
  <input type="hidden" name="entity_type" value="stakeholder">
  <input type="hidden" name="entity_id" value="{{ stakeholder_view.selected.id }}">
  <button class="button compact danger" type="submit">预览删除影响</button>
</form>
```

Use `entity_type="scenario"` and the scenario ID in the scenario template. When `delete_preview` exists, render the server result and require a second POST:

```html
<section class="callout danger-callout" aria-labelledby="delete-impact-title">
  <h3 id="delete-impact-title">确认删除 {{ delete_preview.target_label }}</h3>
  {% for group in delete_preview.affected_groups %}
    <div class="impact-group">
      <strong>{{ group.label }}</strong>
      <ul>{% for item in group.items %}<li>{{ item.label }} <code>{{ item.id }}</code></li>{% else %}<li>无</li>{% endfor %}</ul>
    </div>
  {% endfor %}
  <form method="post" action="/w/{{ workspace.name }}/requirements/entities/delete">
    <input type="hidden" name="entity_type" value="{{ delete_preview.entity_type }}">
    <input type="hidden" name="entity_id" value="{{ delete_preview.entity_id }}">
    <input type="hidden" name="plan_hash" value="{{ delete_preview.plan_hash }}">
    <button class="button danger" type="submit">确认人工删除</button>
  </form>
</section>
```

Render `state.deletion_registry` under “已删除内容”. Each row shows type, original label/ID, deleted revision, impact counts, and a restore POST form. Never render an automatic delete action.

Render `state.analysis_review_hints` beside the deletion history. A suppressed-object hint must say that the model rediscovered the object but did not restore it, and offer only the human restore control tied to its deletion-registry record.

Render each entity's `review_hint` and `possible_duplicate_ids` beside its provenance. The UI may link to the possible duplicate but must not auto-merge or auto-delete it.

Add `WebFacade.requirement_entity_history(workspace_name, entity_type, entity_id)`. It reads `repository.workbench_revisions()`, extracts the matching entity snapshot from the group mapped in Task 8 (or its deletion snapshot), removes consecutive entries with the same `canonical_hash(snapshot)`, and returns revision, event, `last_editor`, field sources, analysis block/input hash, provider/model, and source Requirement IDs. Include this read-only history in stakeholder/scenario presenters and render a collapsed “版本与来源” list. This exposes audit history without adding another persistence model or a hard lock.

Change the requirement deletion form in `project-management.html` to POST `entity_type=requirement` and the Requirement ID to `/requirements/entities/delete-preview`; the old `/requirements/delete` action must no longer exist. Update its route tests and professional workflow test to preview, extract `plan_hash`, then confirm deletion.

For every `suggested_changes` entry, show `current`, `suggested`, `block_id`, and `input_hash`. An “采用此建议” form must post the complete current entity to its ordinary stakeholder/scenario edit route, changing only the suggested field to the proposed value. This deliberately records the accepted value as a new human edit; do not add a machine-side “accept suggestion” bypass.

- [ ] **Step 5: Add accessible styling**

Use existing panel, callout, status-badge, button, compact-list, and focus styles. Add only these minimal rules; retain visible `<label>` text and the existing `:focus-visible` rule:

```css
.impact-group { display: grid; grid-template-columns: minmax(8rem, 0.35fr) 1fr; gap: 12px; }
.impact-group ul { margin: 0; }
.suggestion-diff { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.suggestion-diff del, .suggestion-diff ins { display: block; padding: 12px; white-space: pre-wrap; }
.danger-callout { border-color: var(--bad-border); background: var(--bad-soft); }
@media (max-width: 720px) {
  .impact-group, .suggestion-diff { grid-template-columns: 1fr; }
}
```

- [ ] **Step 6: Run Web/API tests**

Run: `.venv/bin/python -m pytest tests/application/test_scenarios.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/interface/test_interaction_closure.py tests/e2e/test_professional_mbse_workflow.py -q`

Expected: PASS; deletion requires a current preview hash, restore is visible, and model suggestions never replace displayed human values automatically.

- [ ] **Step 7: Commit deletion and suggestion UI**

```bash
git add src/rflp_lite/application/scenarios.py src/rflp_lite/application/web_facade.py src/rflp_lite/interface/web/routes.py src/rflp_lite/interface/web/api_v1.py src/rflp_lite/interface/web/presenters.py src/rflp_lite/interface/web/templates/requirements-stakeholders.html src/rflp_lite/interface/web/templates/requirements-scenarios.html src/rflp_lite/interface/web/templates/requirements-review.html src/rflp_lite/interface/web/templates/project-management.html src/rflp_lite/interface/web/static/app.css tests/application/test_scenarios.py tests/interface/web/test_pages.py tests/interface/web/test_api_v1.py tests/interface/test_interaction_closure.py tests/e2e/test_professional_mbse_workflow.py
git commit -m "feat: expose human analysis management controls"
```

---

### Task 10: End-to-End Closure, Derived Models, and Documentation

**Files:**
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `tests/interface/web/test_auto_requirements.py`
- Modify: `tests/e2e/test_professional_mbse_workflow.py`
- Modify: `tests/e2e/test_cross_workspace_and_partial_failure.py`
- Create: `tests/e2e/test_incremental_reanalysis.py`
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: every prior task.
- Produces: verified user workflow, architecture documentation, and regression evidence.

- [ ] **Step 1: Write the failing end-to-end acceptance test**

```python
def test_incremental_and_full_reanalysis_preserve_human_work(tmp_path, monkeypatch) -> None:
    client, model = configured_client(tmp_path, monkeypatch)
    client.post("/w/demo/requirements/analyze", data={"text": "操作员应启动系统"})
    wait_for_analysis(client)
    first = requirements_state(client)
    operator = next(item for item in first["stakeholders"] if item["category"] == "operator")

    client.post(
        "/w/demo/requirements/stakeholders/edit",
        data={"stakeholder_id": operator["id"], "name": "现场操作负责人", "category": "operator", "description": "人工描述", "goals": "安全启动", "interactions": "启动系统"},
    )
    client.post("/w/demo/requirements/analyze", data={"text": "审计人员应检查故障恢复记录"})
    wait_for_analysis(client)
    second = requirements_state(client)
    assert any(item["name"] == "现场操作负责人" for item in second["stakeholders"])
    assert any(item["category"] == "regulator" for item in second["stakeholders"])
    regulator = next(item for item in second["stakeholders"] if item["category"] == "regulator")
    assert any(item.get("stakeholder_id") == regulator["id"] for item in second["concerns"])
    assert any(item.get("stakeholder_id") == regulator["id"] for item in second["needs"])
    assert {item["scenario_type"] for item in second["scenarios"]} >= {"normal", "boundary", "failure", "recovery", "misuse"}

    client.post("/w/demo/requirements/reanalyze")
    wait_for_analysis(client)
    third = requirements_state(client)
    assert len({item["id"] for item in third["stakeholders"]}) == len(third["stakeholders"])
    assert any(item["name"] == "现场操作负责人" for item in third["stakeholders"])
    edited = next(item for item in third["stakeholders"] if item["name"] == "现场操作负责人")
    assert edited["field_sources"]["name"] == "user"
    assert third["rflp"] is not None
    assert third["mbse"] is not None
    assert third["analysis_progress"]["source_total"] == len(third["analysis_progress"]["analyzed_source_ids"])

    preview = delete_preview(client, "stakeholder", operator["id"])
    delete_with_preview(client, preview)
    client.post("/w/demo/requirements/reanalyze")
    wait_for_analysis(client)
    fourth = requirements_state(client)
    deleted_keys = {
        key
        for item in fourth["deletion_registry"]
        if item["entity_id"] == operator["id"]
        for key in item["match_keys"]
    }
    assert deleted_keys
    assert not any(
        deleted_keys.intersection(item.get("match_keys", ()))
        for item in fourth["stakeholders"]
    )
```

Define `configured_client` in this test module with a deterministic six-block fake model whose second input adds a regulator, regulator Concern/Need, all five scenario types, and architecture entities/relations. `wait_for_analysis` polls the existing Job endpoint until `completed`, `degraded`, `failed`, `interrupted`, or `superseded`, with a five-second test deadline. `requirements_state`, `delete_preview`, and `delete_with_preview` are thin wrappers over the API routes introduced in Tasks 6 and 9; they assert every response before returning JSON so a transport failure cannot appear as a domain assertion.

- [ ] **Step 2: Run the acceptance test and capture the exact integration failure**

Run: `.venv/bin/python -m pytest tests/e2e/test_incremental_reanalysis.py -q`

Expected before Step 3: FAIL specifically at `third["rflp"]` or `third["mbse"]` if the final reconciled state is not yet connected to derived-model refresh. If it already passes because Task 5 preserved the existing refresh correctly, proceed without manufacturing a failure.

- [ ] **Step 3: Ensure derived RFLP/MBSE models refresh from reconciled state**

After all blocks complete, reload and revision-check the Workbench once more, then generate RFLP and MBSE from that current reconciled state. Replace the current inline completion block in `enrichment_jobs.py` with this helper:

```python
import json


def _refresh_derived_models(
    state: dict[str, object], diagnostics: list[dict[str, object]]
) -> dict[str, object]:
    from rflp_lite.application.mbse_modeling import generate_mbse_revision
    from rflp_lite.application.requirements_workbench import generate_model

    current = json.loads(canonical_json(state))
    current["rflp"], current["mbse"], current["baseline"] = None, None, None
    current["coverage"], current["svg"], current["draft_graph"] = {}, "", None
    try:
        return generate_mbse_revision(generate_model(current))
    except (ContractViolation, InvariantViolation, ValueError, TypeError, KeyError) as exc:
        diagnostics.append({
            "code": "derived_model_deferred",
            "severity": "warning",
            "message": "分块结果已保存，RFLP/MBSE 需在需求检查页重新生成。",
            "error_type": type(exc).__name__,
        })
        return current
```

Inside one repository transaction, reload `current`, call `_snapshot_is_current(current, snapshot_content_revision, snapshot_input_hash)`, run `_refresh_derived_models(current, diagnostics)`, and save the returned state. If the guard fails, exit the transaction, return `_supersede(job_id, "derived_models")`, and do not save. Human edit/delete/restore paths continue clearing `rflp`, `mbse`, `baseline`, `coverage`, `svg`, and `draft_graph`; the next explicit generation or full/incremental analysis rebuilds them from current IDs.

- [ ] **Step 4: Add concurrency, large-input, and project-isolation E2E cases**

Add these exact assertions to `test_incremental_reanalysis.py` and `test_cross_workspace_and_partial_failure.py`:

```python
def test_all_55_regions_are_analyzed(client) -> None:
    seed_regions(client, 55)
    job = post_full_reanalysis(client, "demo")
    terminal = wait_for_job(client, "demo", job["id"])
    assert terminal["source_total"] == 55
    assert terminal["source_analyzed"] == 55
    assert set(requirements_state(client, "demo")["analysis_progress"]["analyzed_source_ids"]) == {
        f"region-{index}" for index in range(55)
    }


def test_human_edit_supersedes_stale_job(client, controllable_model) -> None:
    job = post_full_reanalysis(client, "demo")
    controllable_model.wait_until_called()
    edit_selected_stakeholder(client, "demo", name="人工保留名称")
    controllable_model.release()
    assert wait_for_job(client, "demo", job["id"])["status"] == "superseded"
    assert selected_stakeholder(client, "demo")["name"] == "人工保留名称"


def test_same_revision_full_reanalysis_reuses_active_job(client) -> None:
    first = post_full_reanalysis(client, "demo")
    second = post_full_reanalysis(client, "demo")
    assert first["id"] == second["id"]


def test_failed_scenario_block_keeps_successful_blocks(client, scenario_failing_model) -> None:
    terminal = run_analysis(client, "demo", scenario_failing_model)
    state = requirements_state(client, "demo")
    assert terminal["status"] == "degraded"
    assert state["stakeholders"]
    assert state["claims"]
    assert terminal["blocks"]["scenarios"] == "failed"


def test_workspace_analysis_records_do_not_leak(client) -> None:
    seed_distinct_workspace_analysis(client, "alpha", "甲方专属角色")
    seed_distinct_workspace_analysis(client, "beta", "乙方专属角色")
    delete_first_stakeholder(client, "alpha")
    alpha = requirements_state(client, "alpha")
    beta = requirements_state(client, "beta")
    assert "甲方专属角色" not in {item["name"] for item in beta["stakeholders"]}
    assert "乙方专属角色" not in {item["name"] for item in alpha["stakeholders"]}
    assert alpha["deletion_registry"] and not beta["deletion_registry"]
    alpha_ids = collect_all_entity_ids(alpha)
    beta_ids = collect_all_entity_ids(beta)
    alpha_only_ids = alpha_ids - beta_ids
    assert all(
        link.get("source_id") not in alpha_only_ids
        and link.get("target_id") not in alpha_only_ids
        for link in beta.get("trace_links", ())
    )
```

`collect_all_entity_ids` walks the Workbench entity collections and the architecture buckets but ignores scalar metadata. Deterministic identity may legitimately produce the same local ID for the same semantic entity in two workspaces. The isolation test therefore verifies absence of cross-workspace content and references, not global ID inequality.

- [ ] **Step 5: Update documentation**

Document automatic incremental analysis, full reanalysis, always-editable human fields, non-delete LLM contract, deletion registry/restore, complete source batching, new endpoints, Job `superseded`, and the six-block canonical-reference flow. Remove statements that claim one unpartitioned request or fixed source limits.

- [ ] **Step 6: Run focused feature tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/application/intelligence \
  tests/application/use_cases/test_reanalyze_requirements.py \
  tests/application/use_cases/test_manage_analysis_entity.py \
  tests/application/test_entity_deletion.py \
  tests/interface/web/test_requirements_enrichment.py \
  tests/interface/web/test_auto_requirements.py \
  tests/e2e/test_incremental_reanalysis.py \
  tests/e2e/test_cross_workspace_and_partial_failure.py -q
```

Expected: PASS.

- [ ] **Step 7: Run architecture and full regression suites**

Run:

```bash
.venv/bin/python -m pytest tests/architecture -q
.venv/bin/python -m pytest -q
```

Expected: all tests PASS. Any pre-existing unrelated failure must be recorded with its exact test name and reproduced on the pre-feature commit before being classified as unrelated.

- [ ] **Step 8: Perform a manual browser smoke test**

Verify in one workspace:

1. submit an initial requirement;
2. wait for automatic analysis;
3. edit a stakeholder and a scenario;
4. add a requirement that introduces another stakeholder;
5. confirm automatic stakeholder/Concern/Need/scenario supplementation;
6. click “重新分析全部需求” and confirm no duplicates;
7. preview and delete one entity;
8. reanalyze and confirm it stays deleted;
9. restore it from “已删除内容”;
10. confirm refreshed RFLP/MBSE views contain only current IDs.

- [ ] **Step 9: Commit end-to-end closure and documentation**

```bash
git add src/rflp_lite/application/intelligence/enrichment_jobs.py tests/interface/web/test_auto_requirements.py tests/e2e/test_professional_mbse_workflow.py tests/e2e/test_cross_workspace_and_partial_failure.py tests/e2e/test_incremental_reanalysis.py docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md README.md
git commit -m "test: verify incremental requirements reanalysis"
```

## Final Verification Checklist

- [ ] New requirements automatically analyze and supplement stakeholders, Concern/Need, scenarios, requirements, and architecture.
- [ ] The full-reanalysis button runs all six blocks against the latest revision.
- [ ] Cross-block relations use reconciled formal IDs.
- [ ] Repeated runs are idempotent.
- [ ] Human values remain editable and survive automated analysis.
- [ ] Model disagreements with human values appear only as suggestions.
- [ ] Automated code has no delete operation.
- [ ] Human deletion requires an impact preview and is recoverable.
- [ ] Deleted identities are suppressed until human restoration.
- [ ] Every source is processed through stable batches.
- [ ] Stale jobs become superseded and cannot overwrite current state.
- [ ] Existing partial-failure, project-isolation, RFLP/MBSE, and Web regressions pass.
