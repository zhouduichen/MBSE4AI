# Partial Model Requirement Derivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the default vertical generator derive a reviewable Requirement from an existing partial ModelGraph when the input contains operational or system context but no requirement yet.

**Architecture:** Keep ModelGraph as the source of truth and add the derived Requirement inside the existing `vertical.requirements` rule runtime. The derivation only uses typed fields already present in the graph, preserves idempotence, and then lets the existing Functional, Logical, Physical, and V&V stages consume the new requirement normally.

**Tech Stack:** Python 3.12, immutable ModelGraph patches, pytest, existing `VerticalRuleRuntime` and `ModelGenerationService`.

## Global Constraints

- Do not replace user-modified or locked entities.
- Do not invent vendor, component, or measured physical values.
- Preserve typed relations and the existing five-stage order.
- Keep the derived Requirement reviewable and traceable to its source context.

---

### Task 1: Specify partial-model derivation behavior

**Files:**
- Modify: `tests/e2e/test_vertical_model_generation.py`
- Modify: `tests/runtime/test_vertical_rule_runtime.py`

**Interfaces:**
- Consumes: `build_v2_services`, `VerticalRuleRuntime`, `EntityKind`, `RelationPredicate`.
- Produces: regression coverage proving a partial operational model can enter the existing five-stage product path and that the runtime emits a typed, source-linked Requirement.

- [ ] **Step 1: Write the failing end-to-end test**

Add a test that seeds a project with one existing `ACTIVITY` using the existing `Patch`/`AddEntity` API, runs `generate` without `requirement_text`, and asserts the generated Requirement, complete trace, and source relation:

```python
def test_partial_operational_model_derives_requirement_and_completes_vertical_chain(tmp_path: Path):
    services = build_v2_services(tmp_path / "workspaces", runtime=VerticalRuleRuntime())
    services.projects.create("warehouse")
    activity = make_entity(
        EntityKind.ACTIVITY,
        "监测并告警活动",
        {"steps": ["采集温度", "判断阈值", "发送告警"], "goal": "监测仓储温度并在超限时告警"},
    )
    graph = services.model("warehouse").graph("warehouse")
    services.model("warehouse").apply_patch(
        "warehouse",
        Patch.create("warehouse", "import.partial-model", (AddEntity(activity),), "导入部分运行模型", graph.revision),
        graph.revision,
    )

    result = services.generation("warehouse").generate("warehouse")
    graph = services.model("warehouse").graph("warehouse")

    requirement = next(item for item in graph.entities if item.kind is EntityKind.REQUIREMENT)
    assert requirement.payload["derived_from_kind"] == EntityKind.ACTIVITY.value
    assert requirement.payload["source_context_ids"] == [activity.id]
    assert any(
        relation.source_id == requirement.id
        and relation.predicate is RelationPredicate.DERIVED_FROM
        and relation.target_id == activity.id
        for relation in graph.relations
    )
    assert result.traceability.complete_count == 1
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `./.venv/bin/pytest tests/e2e/test_vertical_model_generation.py::test_partial_operational_model_derives_requirement_and_completes_vertical_chain -q`

Expected: FAIL because the current offline Requirements stage leaves a partial graph without any Requirement, so downstream stages cannot create an end-to-end path.

- [ ] **Step 3: Add direct runtime coverage for source selection and idempotence**

Add a test in `tests/runtime/test_vertical_rule_runtime.py` that builds a `ContextBundle` containing an `ACTIVITY` with `goal`, executes `vertical.requirements`, and asserts exactly one Requirement is in the patch with `derived_from_kind`, `source_context_ids`, `statement`, and a `derivedFrom` relation. Execute the same request against the patched graph and assert the second response has `patch is None`, proving no new Requirement is emitted.

- [ ] **Step 4: Run the runtime test and verify it fails**

Run: `./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py -q`

Expected: the new source-link assertions fail because the runtime currently only iterates existing requirements.

### Task 2: Implement typed requirement derivation

**Files:**
- Modify: `src/rflp_lite/runtime/rule_based.py`

**Interfaces:**
- Consumes: `_VerticalPatchBuilder`, `EntityKind.ACTIVITY`, `EntityKind.OPERATIONAL_SCENARIO`, `EntityKind.SYSTEM`, and `make_entity` through the existing builder.
- Produces: a validated derived Requirement in the `vertical.requirements` patch, linked with `RelationPredicate.DERIVED_FROM` to the selected context entity.

- [ ] **Step 1: Add bounded context selection helpers**

Implement helpers next to `_requirements` that select the first active Activity with a non-empty `goal`, `objective`, `purpose`, or `statement`; otherwise select an Operational Scenario with `goal`, `outcome`, or `name`; otherwise select a System with `mission`; and finally use the project id. Return both the short source text and source entity. Strip sentence punctuation, cap the text at 48 characters, and never use a placeholder such as `待确认`.

- [ ] **Step 2: Create the Requirement only when the stage has none**

At the start of `VerticalRuleRuntime._requirements`, if `_requirements(request)` is empty, create:

```python
derived = builder.add(
    EntityKind.REQUIREMENT,
    f"系统应{subject}",
    {
        "statement": f"系统应{subject}",
        "source": "derived_from_existing_model",
        "derived_from_kind": source.kind.value,
        "source_context_ids": [source.id],
        "level": "system",
        "type": "functional",
        "obligation": "系统应",
        "verification_method": "test",
    },
)
builder.relate(derived, RelationPredicate.DERIVED_FROM, source)
requirements = (derived,)
```

Use the existing builder so status, producer, stable identity, revision, and idempotence follow the current patch contract. If no active context entity exists, use the project id as the subject and do not create a fabricated relation.

- [ ] **Step 3: Run focused tests and verify they pass**

Run: `./.venv/bin/pytest tests/runtime/test_vertical_rule_runtime.py tests/e2e/test_vertical_model_generation.py::test_partial_operational_model_derives_requirement_and_completes_vertical_chain -q`

Expected: PASS.

### Task 3: Document and verify the product path

**Files:**
- Modify: `README.md`
- Modify: `docs/CURRENT_ARCHITECTURE.md`

**Interfaces:**
- Consumes: the implemented partial-model behavior and its regression tests.
- Produces: user-facing documentation that existing partial ModelGraph context can be used as generation input and is completed through the same five stages.

- [ ] **Step 1: Document the supported partial-model entry**

Update the existing input sections to state that a non-empty imported or manually edited ModelGraph may omit Requirement; the Requirements stage derives one from typed Activity, Operational Scenario, or System context, marks it as a reviewable generated entity, and records `derivedFrom` traceability.

- [ ] **Step 2: Run the full quality gate**

Run: `./.venv/bin/python scripts/verify_full.py`

Expected: all tests, compile checks, architecture metrics, Ruff, and Import Linter pass.

- [ ] **Step 3: Review the final diff and commit**

Run: `git diff --check && git status --short && git diff --stat`

Expected: only the planned runtime, tests, documentation, and plan files are changed. Commit with:

```bash
git add src/rflp_lite/runtime/rule_based.py tests/e2e/test_vertical_model_generation.py tests/runtime/test_vertical_rule_runtime.py README.md docs/CURRENT_ARCHITECTURE.md docs/superpowers/plans/2026-09-14-partial-model-requirement-derivation.md
git commit -m "feat: derive requirements from partial models"
```

- [ ] **Step 4: Push the current branch**

Run: `git push origin codex/web-audit-2026-08-18`

Expected: the branch is up to date with origin and the commit hash is reported to the user.

## Self-Review

- Spec coverage: this slice covers the stated existing-model input path, preserves ModelGraph as the semantic source, and reuses the full R→F→L→P→V&V pipeline; it does not expand the 23-task compatibility path.
- Placeholder scan: no TODO/TBD steps are used; all implementation and verification commands are concrete.
- Type consistency: tests use the existing `services.model(...).add_entity` API and the runtime uses existing `EntityKind`, `RelationPredicate`, and `_VerticalPatchBuilder` interfaces.
