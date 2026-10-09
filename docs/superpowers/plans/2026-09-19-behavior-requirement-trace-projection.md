# 1.2 Behavior Requirement Trace Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose existing Requirement-to-behavior trace relations in the behavior projection, UI, and engineering deliverable without changing ModelGraph storage or generation semantics.

**Architecture:** Keep `build_behavior_view()` as the single read-side projection. Compute behavior-to-requirement IDs from explicit `derivedFrom` graph relations, with a payload-only fallback for legacy behavior entities that have `requirement_ids` but no relation. Include Requirement only in the relation projection, not in the existing behavior `records` groups, so current consumers retain their shape while the API and deliverable become navigable.

**Tech Stack:** Python 3, immutable `ModelGraph`, FastAPI test client, pytest, Jinja2 templates, offline `VerticalRuleRuntime`.

## Global Constraints

- Do not change ModelGraph entities, relation predicates, compiler write paths, or CAS behavior.
- Do not start a web server, SSH session, FreeCAD, local model, or remote model.
- Use `derivedFrom` relations as the authoritative source; payload fallback is read-only compatibility behavior.
- Keep the existing behavior API fields and sequence-diagram format backward compatible.

---

### Task 1: Add failing projection and compatibility tests

**Files:**
- Create: `tests/application/test_behavior_projection.py`
- Modify: `tests/interface/web/test_requirements_use_case.py:45-65`
- Modify: `tests/application/test_deliverables.py` (add behavior artifact coverage)

**Interfaces:**
- Consumes: `build_behavior_view(graph)`, `VerticalRuleRuntime`, `build_v2_services`, and the existing requirements/use-case API fixture.
- Produces: executable assertions for explicit graph relations, legacy payload fallback, UI visibility, and deliverable parity.

- [ ] **Step 1: Write the failing projection test**

Create a graph containing one Requirement, Use Case, Operational Scenario, and Activity. Add these relations:

```python
Relation("r-uc", requirement.id, RelationPredicate.DERIVED_FROM, use_case.id),
Relation("r-activity", requirement.id, RelationPredicate.DERIVED_FROM, activity.id),
Relation("uc-activity", use_case.id, RelationPredicate.DECOMPOSES, activity.id),
```

Call `build_behavior_view(graph)` and assert:

```python
assert {row["source"] for row in view["relations"]} >= {requirement.id}
use_case_view = next(item for item in view["use_cases"] if item["id"] == use_case.id)
assert use_case_view["requirement_ids"] == [requirement.id]
scenario_view = next(item for item in view["scenarios"] if item["id"] == scenario.id)
assert scenario_view["requirement_ids"] == [requirement.id]
assert view["sequence_diagrams"][0]["requirement_ids"] == [requirement.id]
```

- [ ] **Step 2: Add a payload-fallback test**

Create a Use Case with `{"requirement_ids": [requirement.id]}` and no Requirement relation. Assert its `use_cases[*].requirement_ids` is returned by the projection, while `view["relations"]` contains no fabricated relation whose source is the Requirement. This proves the fallback is read-only and does not manufacture graph edges.

- [ ] **Step 3: Extend the existing API/UI test**

After applying the existing document-to-use-case draft, assert that every applied requirement ID appears in a behavior relation row and in the Use Case `requirement_ids`; assert the HTML contains the `需求：` label and one applied requirement ID.

- [ ] **Step 4: Add deliverable parity coverage**

Generate an offline project with `VerticalRuleRuntime`, build the engineering package, and assert:

```python
behavior = package["artifacts"]["behavior"]["content"]
assert behavior == build_behavior_view(services.model("p1").graph("p1"))
assert any(row["source"].startswith("requirement-") for row in behavior["relations"])
```

- [ ] **Step 5: Run the focused tests and verify they fail**

Run:

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" ./.venv/bin/python -m pytest \
  tests/application/test_behavior_projection.py \
  tests/interface/web/test_requirements_use_case.py \
  tests/application/test_deliverables.py -q
```

Expected: the new assertions fail because Requirement endpoints are currently excluded from the behavior projection and the new fields are absent.

### Task 2: Implement canonical behavior-to-requirement projection

**Files:**
- Modify: `src/rflp_lite/application/projections/behavior.py:12-205`

**Interfaces:**
- Consumes: `ModelGraph.entity_index`, `ModelGraph.relations`, `RelationPredicate.DERIVED_FROM`, and behavior payloads.
- Produces: `_requirement_ids_for_entity(graph, entity) -> list[str]`, expanded behavior `relations`, and `requirement_ids` fields for use cases, scenarios, and sequence diagrams.

- [ ] **Step 1: Add a read-only requirement ID helper**

Implement a helper with this behavior:

```python
def _requirement_ids_for_entity(graph: ModelGraph, entity: Entity) -> list[str]:
    index = graph.entity_index
    explicit = sorted(
        relation.source_id
        for relation in graph.relations
        if relation.target_id == entity.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and index.get(relation.source_id) is not None
        and index[relation.source_id].kind is EntityKind.REQUIREMENT
    )
    if explicit:
        return list(dict.fromkeys(explicit))
    payload_ids = entity.payload.get("requirement_ids", ())
    return list(dict.fromkeys(
        str(value) for value in payload_ids or ()
        if str(value) in index and index[str(value)].kind is EntityKind.REQUIREMENT
    ))
```

The helper must never create or return a relation object. It only returns IDs that already resolve to Requirement entities.

- [ ] **Step 2: Expand relation filtering without changing records**

Define a relation-only kind set containing the existing behavior kinds plus `EntityKind.REQUIREMENT`. Use it only when filtering `graph.relations`; keep `_KINDS` unchanged for `records`.

- [ ] **Step 3: Add requirement IDs to behavior projections**

For each Use Case and Operational Scenario, call the helper and include `"requirement_ids"`. Pass the Scenario IDs into `_sequence_diagrams()` and include the same list on each diagram. Keep ordering deterministic by sorting IDs.

- [ ] **Step 4: Run focused tests**

Run the same focused pytest command from Task 1. Expected: all new projection and API assertions pass; UI assertions may remain failing until Task 3.

### Task 3: Make the behavior page show the trace

**Files:**
- Modify: `src/rflp_lite/interface/web/templates/behavior.html:5-8`

**Interfaces:**
- Consumes: `use_cases[*].requirement_ids`, `scenarios[*].requirement_ids`, and `sequence_diagrams[*].requirement_ids` from `build_behavior_view()`.
- Produces: human-readable requirement references while preserving the current editable entity IDs and Mermaid output.

- [ ] **Step 1: Add requirement references to Use Case cards**

Render a compact line after the Use Case goal:

```jinja2
<small>来源需求：{{ item.requirement_ids|join('、') or '—' }}</small>
```

- [ ] **Step 2: Add requirement references to Scenario cards**

Render the same `来源需求` line in each Operational Scenario card before its steps.

- [ ] **Step 3: Add requirement references to sequence cards**

Render `requirement_ids` next to the existing editable entity IDs so the displayed sequence framework visibly retains its source trace.

- [ ] **Step 4: Run the focused web tests**

Run:

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" ./.venv/bin/python -m pytest \
  tests/interface/web/test_requirements_use_case.py -q
```

Expected: all API and HTML assertions pass.

### Task 4: Verify the complete offline slice and publish

**Files:**
- Modify: `README.md` and `DEVELOPMENT_STATUS.md` only if the current status table does not mention behavior requirement back-links.
- No additional source changes unless a focused test exposes a real contract defect.

**Interfaces:**
- Consumes: all changes from Tasks 1–3.
- Produces: verified offline behavior artifact and a pushed Git commit.

- [ ] **Step 1: Run the complete local verification gate**

Run:

```bash
RFLP_CONFIG_DIR="$(mktemp -d)" AI4MBSE_CAD_BACKEND=preview ./.venv/bin/python scripts/verify_full.py
```

Expected: compileall, pytest, architecture metrics, Ruff, and import-linter all pass. This command must not invoke a model or server.

- [ ] **Step 2: Inspect the final diff and worktree**

Run:

```bash
git diff --check
git status --short
git diff --stat HEAD~1
```

Expected: only the scoped projection, template, tests, and plan/status documentation are changed; no generated database or secrets are present.

- [ ] **Step 3: Commit the implementation**

```bash
git add src/rflp_lite/application/projections/behavior.py \
  src/rflp_lite/interface/web/templates/behavior.html \
  tests/application/test_behavior_projection.py \
  tests/interface/web/test_requirements_use_case.py \
  tests/application/test_deliverables.py
git commit -m "feat: expose requirement links in behavior projection"
```

- [ ] **Step 4: Push the branch to GitHub**

```bash
git push origin codex/web-audit-2026-08-18
```
