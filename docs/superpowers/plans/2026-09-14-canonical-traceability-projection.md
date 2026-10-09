# Canonical Traceability Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use the available task-by-task implementation workflow. Steps use checkbox syntax for tracking.

**Goal:** Make generation summaries, traceability projections, RFLP views, the /trace API, and exported trace artifacts agree on one semantic Requirement→F→L→P→V&V path.

**Architecture:** Extend the existing pure vertical_coverage module with a per-requirement canonical trace value object. Existing projection helpers remain the compatibility boundary for callers, but delegate target selection, readiness, technical lineage, V&V scope, gaps, and primary path calculation to that value object. Web and deliverable code consume the existing projection shapes plus bounded stage coverage data; canonical projection code remains read-only. The lifecycle runner may promote an LLM output to `validated` only after its existing completion checks pass.

**Tech Stack:** Python 3.11+, frozen dataclasses, existing ModelGraph/RelationPredicate, FastAPI/Jinja projections, pytest, compileall, Ruff, Import Linter.

## Global Constraints

- ModelGraph remains the only model source of truth; every resolver is pure and read-only.
- Only validated, accepted, and locked target entities count as semantic coverage; candidate/deprecated targets remain visible only through diagnostics or review data.
- Technical Requirements inherit root Function/Logical scope and may use direct Requirement→PhysicalBlock satisfaction.
- V&V IDs count only when typed Case entities have scope matching the graph-derived trace.
- Preserve existing public keys and compatibility wrappers; add fields without renaming current response fields.
- Do not add entities, relations, tables, dependencies, or a second status machine.
- Do not invoke a local model, access Ollama, or run a live-provider experiment.
- All writes, if any existing flow is exercised by tests, continue through Structured Runtime → Compiler → Validator → PatchPolicy → CAS.

---

### Task 1: Add the canonical per-requirement trace contract

**Files:**
- Modify: src/rflp_lite/methodology/vertical_coverage.py
- Test: tests/methodology/test_vertical_coverage.py

**Interfaces:**
- Consumes: ModelGraph, RequirementCoverageRow, CoverageStage, requirement_lineage, and vv_scope_matches.
- Produces: CanonicalRequirementTrace, resolve_requirement_trace(graph, requirement_id), and resolve_rflp_paths(graph, requirement_id) for all later projections.

- [x] **Step 1: Write failing tests for the public trace contract.**

Add these imports and tests to tests/methodology/test_vertical_coverage.py:

~~~python
from rflp_lite.methodology.vertical_coverage import (
    resolve_requirement_trace,
    resolve_rflp_paths,
)


def test_canonical_trace_returns_ready_targets_and_semantic_coverage():
    graph, first, _second = _two_requirement_graph()

    trace = resolve_requirement_trace(graph, first.id)

    assert trace.function_ids
    assert trace.logical_component_ids
    assert trace.physical_ids
    assert trace.verification_case_ids
    assert trace.validation_case_ids
    assert trace.gaps == ()
    assert trace.stage_coverage == {
        "functional": True,
        "logical": True,
        "physical": True,
        "verification": True,
        "validation": True,
    }
    assert trace.primary_path == (
        first.id,
        trace.function_ids[0],
        trace.logical_component_ids[0],
        trace.physical_ids[0],
    )
    assert trace.complete is True


def test_canonical_trace_excludes_non_ready_targets_and_reports_scope_gaps():
    graph, first, _second = _two_requirement_graph()
    verification = next(
        item for item in graph.entities
        if item.kind is EntityKind.VERIFICATION_CASE
    )
    stale = verification.__class__(
        verification.meta,
        {**verification.payload, "physical_ids": []},
    )
    graph = ModelGraph(
        graph.project_id,
        tuple(stale if item.id == stale.id else item for item in graph.entities),
        graph.relations,
        graph.revision,
    )

    trace = resolve_requirement_trace(graph, first.id)

    assert trace.function_ids
    assert "verification_scope" in trace.gaps
    assert "validation" not in trace.gaps
    assert trace.stage_coverage["verification"] is False
    assert trace.complete is False


def test_canonical_rflp_paths_are_deterministic_and_ready_only():
    graph, first, second = _two_requirement_graph()
    physical = resolve_vertical_coverage(graph, "physical")
    row = _row(physical, first.id)

    assert resolve_rflp_paths(graph, first.id) == (
        (first.id, row.function_ids[0], row.logical_component_ids[0], row.physical_ids[0]),
    )
    assert resolve_rflp_paths(graph, second.id) == ()
~~~

The test file already imports EntityKind, ModelGraph, and the helper functions
used above. Keep the assertions deterministic by selecting IDs from the
already sorted resolver row rather than inventing IDs. The existing
`_two_requirement_graph()` fixture must provide two validated Requirements,
validated Function/Logical/Physical entities, and validated VerificationCase
and ValidationCase entities. Its first Requirement has a complete
`SATISFIED_BY → ALLOCATED_TO → ALLOCATED_TO` path plus typed V&V relations;
each Case payload must include the exact graph-derived `function_ids`,
`logical_component_ids`, `physical_ids`, and `requirement_ids` scope fields.
The second Requirement must point to a deprecated Function so it has no ready
functional target. Update the helper only if those semantics are not already
present; do not weaken production readiness rules to fit the test.

- [x] **Step 2: Run the focused tests to verify the contract is not implemented.**

Run:

~~~bash
./.venv/bin/pytest -q tests/methodology/test_vertical_coverage.py
~~~

Expected: FAIL with an import or attribute error for resolve_requirement_trace
or resolve_rflp_paths.

- [x] **Step 3: Implement CanonicalRequirementTrace and its resolvers.**

Add this contract beside VerticalCoverage in
src/rflp_lite/methodology/vertical_coverage.py:

~~~python
@dataclass(frozen=True, slots=True)
class CanonicalRequirementTrace:
    requirement_id: str
    function_ids: tuple[str, ...]
    logical_component_ids: tuple[str, ...]
    physical_ids: tuple[str, ...]
    verification_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    gaps: tuple[str, ...]
    stage_coverage: Mapping[str, bool]
    primary_path: tuple[str, ...]
    complete: bool

    def target_dict(self) -> Mapping[str, tuple[str, ...]]:
        return {
            "functions": self.function_ids,
            "logical": self.logical_component_ids,
            "physical": self.physical_ids,
            "verification": self.verification_case_ids,
            "validation": self.validation_case_ids,
        }

    def as_dict(self) -> Mapping[str, object]:
        return {
            "requirement_id": self.requirement_id,
            **{key: list(value) for key, value in self.target_dict().items()},
            "gaps": list(self.gaps),
            "stage_coverage": dict(self.stage_coverage),
            "primary_path": list(self.primary_path),
            "complete": self.complete,
        }
~~~

Implement resolve_requirement_trace with these exact rules:

1. Resolve the Requirement from graph.entity_index; for a missing/non-
   Requirement ID return empty target tuples, all five stage flags False,
   gaps=("requirement",), primary_path=(requirement_id,), and complete=False.
2. Call _resolve_row(graph, requirement, CoverageStage.PHYSICAL) for the RFLP
   target IDs and _resolve_row(graph, requirement,
   CoverageStage.VERIFICATION_VALIDATION) for V&V IDs and scope checks.
   Include root lineage and valid Requirement IDs listed in
   `source_requirement_ids` in the source set, so derived requirements and
   their V&V payloads use the same inherited scope.
3. Set stage_coverage to True for functional/logical/physical when the
   corresponding target tuple is non-empty. Set verification/validation to
   True only when the typed Case tuple is non-empty and neither matching scope
   gap is present.
4. Build gaps in this order: function, logical, physical, then the assurance
   row missing values. A technical requirement uses the direct physical target
   behavior already implemented by _resolve_row.
5. Build primary_path as the Requirement followed by the first sorted function,
   logical, and physical ID that exists. Do not include V&V IDs in this RFLP
   path.

Implement resolve_rflp_paths using the same source IDs, _target_ids, and
predicate sets as _resolve_row; emit every sorted valid four-node path and
return an empty tuple when no complete ready path exists. For a technical
Requirement with only direct physical satisfaction, return no four-node path;
its direct physical target remains available in CanonicalRequirementTrace.

Import Mapping from collections.abc in this module if needed, and keep all new
functions side-effect free.

- [x] **Step 4: Run the focused tests to verify the canonical contract.**

Run:

~~~bash
./.venv/bin/pytest -q tests/methodology/test_vertical_coverage.py
~~~

Expected: all resolver tests pass.

- [x] **Step 5: Commit the isolated resolver.**

~~~bash
git add src/rflp_lite/methodology/vertical_coverage.py tests/methodology/test_vertical_coverage.py
git commit -m "feat: add canonical requirement trace resolver"
~~~

### Task 2: Migrate application projections and generation summary

**Files:**
- Modify: src/rflp_lite/application/projections/common.py
- Modify: src/rflp_lite/application/projections/traceability.py
- Modify: src/rflp_lite/methodology/coverage_matrix.py
- Modify: src/rflp_lite/application/model_generation.py
- Modify: src/rflp_lite/methodology/workflow.py
- Modify: src/rflp_lite/runtime/rule_based.py
- Test: tests/application/projections/test_traceability_projection.py
- Test: tests/application/test_model_generation.py
- Test: tests/methodology/test_coverage_matrix.py
- Test: tests/methodology/test_completion_conditions.py

**Interfaces:**
- Consumes: resolve_requirement_trace and resolve_rflp_paths from Task 1.
- Produces: existing trace_targets, requirement_trace_status,
  build_traceability_view, build_requirement_coverage, and
  build_traceability_summary with one consistent target source.

- [x] **Step 1: Add failing cross-surface assertions.**

Extend tests/application/projections/test_traceability_projection.py with:

~~~python
def test_traceability_projection_uses_ready_targets_and_scope_semantics():
    graph, first, second = _two_requirement_graph_fixture()

    view = build_traceability_view(graph)
    first_row = next(row for row in view["rows"] if row["requirement_id"] == first.id)
    second_row = next(row for row in view["rows"] if row["requirement_id"] == second.id)

    assert first_row["status"] == "PASS"
    assert first_row["coverage_percent"] == 100.0
    assert second_row["functions"] == ()
    assert "function" in second_row["gaps"]
    assert second_row["status"] == "MISSING_FUNCTION"
    assert first_row["stage_coverage"] == {
        "functional": True,
        "logical": True,
        "physical": True,
        "verification": True,
        "validation": True,
    }
~~~

Use a local `_two_requirement_graph_fixture()` helper in this test module. It
must create two validated Requirements, validated Function/Logical/Physical
entities, and validated VerificationCase/ValidationCase entities. The first
Requirement gets a complete ready chain and V&V payloads whose
`requirement_ids`, `function_ids`, `logical_component_ids`, and
`physical_ids` exactly match the graph-derived scope. The second Requirement
gets only a relation to a deprecated Function. Add a separate stale V&V scope
assertion by replacing the first VerificationCase with the same entity ID and
an empty `physical_ids` list; it must expect `verification_scope` in gaps and
a non-PASS status. Do not alter the existing invalid-predicate assertions.

Add a model-generation assertion that compares the first row target IDs with
the corresponding TraceabilitySummary.paths prefix. Build the graph directly
from the existing test fixture/service helper, and use the actual
`requirement_id` from the row; do not introduce undefined `service` or
`repository` variables:

~~~python
    summary = build_traceability_summary(graph)
    row = next(item for item in build_traceability_view(graph)["rows"] if item["requirement_id"] == requirement_id)
assert tuple(summary.paths[0][:4]) == tuple(
    [requirement_id, row["functions"][0], row["logical_components"][0], row["physical_blocks"][0]]
)
~~~

- [x] **Step 2: Run the projection tests to verify old semantics are exposed.**

Run:

~~~bash
./.venv/bin/pytest -q tests/application/projections/test_traceability_projection.py tests/application/test_model_generation.py -k "traceability or technical_requirement"
~~~

Expected: the new ready/status/scope assertions fail before migration.

- [x] **Step 3: Delegate common trace helpers to the canonical resolver.**

In src/rflp_lite/application/projections/common.py, import
resolve_requirement_trace. Replace the body of trace_targets with:

~~~python
def trace_targets(graph: ModelGraph, requirement_id: str) -> dict[str, tuple[str, ...]]:
    return dict(resolve_requirement_trace(graph, requirement_id).target_dict())
~~~

Update requirement_trace_status to keep its existing return type while using
the canonical trace gaps and target dictionary. Preserve this order:

1. rejected/deprecated Requirement → REJECTED;
2. invalid typed predicate → INVALID_PREDICATE;
3. no gaps → PASS;
4. one gap → its existing MISSING_* code, or
   INVALID_VERIFICATION_SCOPE / INVALID_VALIDATION_SCOPE for scope gaps;
5. multiple gaps → BLOCKED.

Keep trace_invalid_predicates unchanged except for consuming the delegated
trace_targets result.
When a completed lifecycle task produces LLM entities, promote those output
entities to `validated` after completion checks pass; incomplete or semantically
invalid output remains `candidate` for review.

- [x] **Step 4: Update the traceability projection and coverage matrix.**

In src/rflp_lite/application/projections/traceability.py, calculate each row
from resolve_requirement_trace and retain the current public fields. Add these
fields to each row:

~~~python
"stage_coverage": dict(trace.stage_coverage),
"primary_path": list(trace.primary_path),
~~~

Calculate coverage_percent as the percentage of the five boolean
stage_coverage values, so scope-mismatched V&V is not counted as covered even
when its Case ID is displayed. Keep requirement_function_matrix unchanged
except that its Function IDs come from canonical trace.function_ids.

In src/rflp_lite/methodology/coverage_matrix.py, keep the accepted-Requirement
gate boundary and evidence/hazard calculations, but obtain F/L/P/V/V IDs,
semantic gaps, and paths from resolve_requirement_trace and
resolve_rflp_paths. Preserve the matrix's existing evidence, hazard, and
typed-assurance gate gaps. The existing evidence gap remains an additional
gate-only gap after semantic trace gaps; it must not alter the user-facing
canonical trace status.

- [x] **Step 5: Replace duplicated target traversal in generation summary.**

In src/rflp_lite/application/model_generation.py, import
resolve_requirement_trace, remove the private _trace_targets usage from
build_traceability_summary, and compute each row as:

~~~python
trace = resolve_requirement_trace(graph, requirement.id)
functions = trace.function_ids
logical = trace.logical_component_ids
physical = trace.physical_ids
verification = trace.verification_case_ids if trace.stage_coverage["verification"] else ()
validation = trace.validation_case_ids if trace.stage_coverage["validation"] else ()
rflp = all(trace.stage_coverage[key] for key in ("functional", "logical", "physical"))
end_to_end = trace.complete
path = tuple(dict.fromkeys((*trace.primary_path, *verification[:1], *validation[:1])))
~~~

Exclude both rejected and deprecated Requirements from summary counts. Keep
the TraceabilitySummary field names and count semantics unchanged.

- [x] **Step 6: Run migrated application tests.**

Run:

~~~bash
./.venv/bin/pytest -q tests/application/projections/test_traceability_projection.py tests/methodology/test_coverage_matrix.py tests/application/test_model_generation.py
~~~

Expected: all selected tests pass, including candidate/deprecated and stale
scope cases.

- [x] **Step 7: Commit the projection migration.**

~~~bash
git add src/rflp_lite/application/projections/common.py src/rflp_lite/application/projections/traceability.py src/rflp_lite/methodology/coverage_matrix.py src/rflp_lite/application/model_generation.py tests/application/projections/test_traceability_projection.py tests/methodology/test_coverage_matrix.py tests/application/test_model_generation.py
git commit -m "refactor: unify traceability projections"
~~~

### Task 3: Migrate RFLP and /trace Web/API views

**Files:**
- Modify: src/rflp_lite/application/projections/rflp.py
- Modify: src/rflp_lite/interface/web/resource_pages.py
- Test: tests/interface/web/test_model_trace.py
- Test: tests/interface/web/test_traceability_matrix.py
- Test: tests/interface/web/test_vertical_generation_api.py
- Test: tests/interface/web/test_requirements_workbench.py

**Interfaces:**
- Consumes: resolve_requirement_trace, resolve_rflp_paths, and the canonical
  build_traceability_view fields from Task 2.
- Produces: existing RFLP projection shape and /projects/{id}/trace shape,
  with canonical IDs and missing semantics.

- [x] **Step 1: Add a broken-graph API acceptance test.**

Extend tests/interface/web/test_model_trace.py with a graph containing a
validated Requirement, a candidate Function, and a deprecated Function
connected by the same `SATISFIED_BY` relation. Add a stale VerificationCase
scope and assert:

~~~python
trace = client.get("/projects/p1/trace").json()
path = trace["paths"][0]
assert path["complete"] is False
assert "Function" in path["missing"]
assert path["nodes"][1] is None

matrix = client.get("/projects/p1/traceability").json()
row = matrix["rows"][0]
assert row["status"] == "MISSING_FUNCTION"
assert "function" in row["gaps"]
~~~

Add a complete-fixture assertion that the /trace path first four node IDs,
Trace Matrix IDs, and RFLP selected_trace IDs are identical.

- [x] **Step 2: Run Web trace tests to verify the unrestricted path is exposed.**

Run:

~~~bash
./.venv/bin/pytest -q tests/interface/web/test_model_trace.py tests/interface/web/test_traceability_matrix.py
~~~

Expected: the broken-graph test fails because the current /trace builder uses
an unrestricted breadth-first traversal.

- [x] **Step 3: Use canonical projection rows in the RFLP projection.**

In src/rflp_lite/application/projections/rflp.py, replace rflp_paths calls
for selected paths and gap prefixes with resolve_rflp_paths and
resolve_requirement_trace. Keep edges and relation_is_valid_trace unchanged
so invalid predicates remain visible. For each gap, use:

~~~python
trace = resolve_requirement_trace(graph, entity.id)
path = trace.primary_path
gaps = trace.gaps
~~~

When a selected Requirement has no complete path, return its primary prefix and
the same gaps used by the Trace Matrix.

- [x] **Step 4: Rebuild build_trace_view from canonical rows.**

In src/rflp_lite/interface/web/resource_pages.py, keep _trace_node and the
existing output keys, but replace `_kind_path` traversal in build_trace_view
with build_traceability_view(graph, issues) rows. For each row, construct the
five main nodes from the first ID in functions, logical_components,
physical_blocks, and verification_cases, then construct validation from the
first validation_cases ID. Set:

~~~python
"complete": row["status"] == "PASS",
"missing": [_TRACE_GAP_LABELS[gap] for gap in row["gaps"]],
"vv_complete": row["stage_coverage"]["verification"] and row["stage_coverage"]["validation"],
~~~

Use English compatibility labels for the API's existing `path["missing"]`
values (`Function`, `Logical`, `Physical`, `Verification`, `Validation`) and
add `Verification scope` / `Validation scope` for scope gaps. Preserve the
existing Chinese labels 功能, 逻辑, 物理, 验证, and 确认 in node metadata and
UI text. If a gap is a scope gap, report it explicitly rather than hiding the
Case ID.

- [x] **Step 5: Run Web and API acceptance tests.**

Run:

~~~bash
./.venv/bin/pytest -q tests/interface/web/test_model_trace.py tests/interface/web/test_traceability_matrix.py tests/interface/web/test_vertical_generation_api.py
~~~

Expected: all existing and new tests pass, and no template sees TaskSpec,
Patch, CAS, or raw internal task names.

- [x] **Step 6: Commit the Web/API migration.**

~~~bash
git add src/rflp_lite/application/projections/rflp.py src/rflp_lite/interface/web/resource_pages.py tests/interface/web/test_model_trace.py tests/interface/web/test_traceability_matrix.py tests/interface/web/test_vertical_generation_api.py
git commit -m "feat: align web trace views with canonical semantics"
~~~

### Task 4: Verify deliverables, documentation, and repository gates

**Files:**
- Modify: tests/application/test_deliverables.py
- Modify: tests/application/test_sysml_v2.py
- Modify: docs/CURRENT_ARCHITECTURE.md
- Modify: docs/DEVELOPMENT_STATUS.md
- Modify: docs/superpowers/README.md

**Interfaces:**
- Consumes: canonical projection output from Tasks 1–3.
- Produces: evidence that JSON/ZIP deliverables, SysML round-trip, and user
  documentation describe one trace semantics.

- [x] **Step 1: Add deliverable consistency assertions.**

Extend tests/application/test_deliverables.py with a generated complete model
assertion. Import `build_traceability_summary` and use the existing
`_services_with_complete_graph` helper. Update that helper's entities to
`EntityStatus.VALIDATED` and give the VerificationCase/ValidationCase payloads
the exact requirement and graph-derived F/L/P scope IDs, so the fixture is a
semantically complete canonical trace rather than merely a candidate graph:

~~~python
services = _services_with_complete_graph(tmp_path)
package = services.deliverables("p1").build("p1")
trace_rows = package["artifacts"]["traceability"]["content"]["rows"]
graph = services.model("p1").graph("p1")
summary = build_traceability_summary(graph)
for row in trace_rows:
    if row["status"] == "PASS":
        assert row["coverage_percent"] == 100.0
assert package["artifacts"]["traceability"]["content"]["revision"] == graph.revision
~~~

Add a broken-graph assertion using the existing service/repository fixture
style: build a project with a Requirement and a deprecated or missing Function,
call the application traceability projection and the deliverable builder from
the same graph snapshot, and compare each matching row's `status` and `gaps`.
Do not change artifact names or ZIP member order.

- [x] **Step 2: Run deliverable and SysML regression tests.**

Run:

~~~bash
./.venv/bin/pytest -q tests/application/test_deliverables.py tests/application/test_sysml_v2.py
~~~

Expected: PASS with unchanged SysML entity/relation round-trip behavior.

- [x] **Step 3: Update architecture and status documentation.**

Add one paragraph to docs/CURRENT_ARCHITECTURE.md stating that
resolve_requirement_trace is the source for generation summaries, all
traceability projections, /trace, and the deliverable artifact. Add one
completed row to docs/DEVELOPMENT_STATUS.md and two links to the Current list
in docs/superpowers/README.md for the canonical trace design and plan.

- [x] **Step 4: Run the complete repository quality gates.**

Run each command separately from /Users/huangjiahao/Downloads/AI4MBSE:

~~~bash
./.venv/bin/pytest -q
./.venv/bin/python -m compileall -q src tests scripts
./.venv/bin/ruff check src tests scripts
./.venv/bin/python scripts/architecture_metrics.py
./.venv/bin/lint-imports
git diff --check
~~~

Expected: pytest passes; compileall and Ruff are silent/green; architecture
metrics report zero module cycles, zero adapter-to-application edges, zero
functions over 150 lines, and zero web facade methods; Import Linter reports
5 kept contracts and 0 broken; diff check is clean.

- [x] **Step 5: Review for prohibited local-model access and inspect the diff.**

Run:

~~~bash
rg -n "127\\.0\\.0\\.1:11434|ollama|localhost:11434|Ollama" src tests docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md
git diff --stat HEAD~3..HEAD
git status --short
~~~

The search may find historical configuration labels or documentation, but no
command in this plan or test may start a local model or call port 11434. The
working tree must be clean before push.

- [ ] **Step 6: Commit documentation and push the complete implementation.**

~~~bash
git add docs/CURRENT_ARCHITECTURE.md docs/DEVELOPMENT_STATUS.md docs/superpowers/README.md docs/superpowers/plans/2026-09-14-canonical-traceability-projection.md src/rflp_lite/methodology/vertical_coverage.py src/rflp_lite/methodology/workflow.py tests/application/projections/test_rflp_projection.py tests/application/test_deliverables.py tests/methodology/test_completion_conditions.py
git commit -m "feat: complete canonical traceability integration"
git push origin codex/web-audit-2026-08-18
~~~
