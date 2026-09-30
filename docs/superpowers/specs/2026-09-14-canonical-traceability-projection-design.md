# Canonical Traceability Projection Design

## Context

AI4MBSE already has a typed `ModelGraph`, a per-requirement vertical coverage
resolver, and several traceability projections.  The vertical completion path
uses live, typed target statuses and V&V scope checks, but the older
Requirements/RFLP/Trace Matrix and generation summary still assemble parts of
the same path independently.  That creates a product risk: two screens or a
deliverable can disagree about whether a requirement is complete.

## Goal

Make one semantic Requirement trace resolver the source for all user-facing
traceability projections and generation summaries:

```text
Requirement → Function → LogicalComponent → PhysicalBlock
           ├→ VerificationCase
           └→ ValidationCase
```

Every surface must agree on active/ready target status, technical-requirement
lineage, exact gaps, V&V scope consistency, and longest valid path.

## Non-goals

- No new entity kind, relation predicate, database table, or model schema.
- No automatic repair, model mutation, or change to Review/CAS policy.
- No local model invocation, Ollama access, or live-provider experiment.
- No removal of low-level predicate diagnostics; they remain available for
  invalid-edge reporting.
- No change to the legacy acceptance meaning that only accepted Requirements
  enter its dedicated coverage gate; the gate will consume the same canonical
  target semantics where it reports a path.

## Design

### 1. Canonical per-requirement trace

Extend `src/rflp_lite/methodology/vertical_coverage.py` with a read-only
`resolve_requirement_trace(graph, requirement_id)` boundary.  It returns typed
IDs for functions, logical components, physical blocks, VerificationCases and
ValidationCases, plus:

- exact stage gaps (`function`, `logical`, `physical`, `verification`,
  `verification_scope`, `validation`, `validation_scope`);
- a semantic five-column coverage map;
- the longest valid RFLP prefix;
- whether the requirement is semantically complete.

Resolution uses the existing named predicates and requirement lineage.  Only
`validated`, `accepted`, and `locked` target nodes count as coverage.  A
technical Requirement may inherit Function/Logical scope from its root and
may satisfy Physical directly.  V&V IDs remain visible for review, but a Case
counts as semantically covered only when its payload scope agrees with the
graph-derived scope.

`trace_targets` and `requirement_trace_status` remain compatibility wrappers,
but delegate to this boundary.  Invalid typed edges are still reported before
missing-stage status so imported/user mistakes remain diagnosable.

### 2. Shared projections

Use the canonical trace in:

- `build_traceability_summary`, so generation status and stage summaries use
  the same ready targets as Methodology completion;
- `build_traceability_view`, including coverage percent and exact gaps;
- Requirements and RFLP projections through their existing common helpers;
- the Web `/projects/{id}/trace` view/API, replacing its unrestricted graph
  breadth-first path with the same typed path and missing labels;
- the unified deliverable's traceability artifact, without changing its
  existing top-level artifact names.

The public response keeps existing fields (`functions`, `logical_components`,
`physical_blocks`, `verification_cases`, `validation_cases`, `gaps`,
`coverage_percent`, `status`) and adds bounded `stage_coverage` data where it
helps the UI explain why a row is incomplete.  The UI may show canonical IDs
and business labels, but must not expose TaskSpec/Patch/CAS internals.

### 3. Consistent semantics

- A requirement with only candidate/deprecated downstream nodes is incomplete.
- A wrong predicate is `INVALID_PREDICATE`, even if a similarly named node
  exists.
- A V&V Case with IDs but stale or incomplete scope is incomplete and reports
  the corresponding scope gap.
- A technical requirement's direct physical satisfaction is included in its
  display path and completion calculation.
- All paths and lists are deterministic by canonical ID.

## Data flow

```text
ModelGraph
    ↓
resolve_requirement_trace
    ├── generation TraceabilitySummary
    ├── Requirements / RFLP / Trace Matrix projections
    ├── /trace API and workbench view
    └── deliverable traceability.json
```

The resolver is pure and LLM-free.  Model writes continue through the existing
Structured Runtime → Compiler → Validator → CAS path; this change only removes
semantic disagreement among read projections.

## Acceptance criteria

1. A complete generated model produces identical Requirement target IDs and
   complete status in generation summary, Trace Matrix, RFLP focus, `/trace`,
   and the exported traceability artifact.
2. A candidate or deprecated downstream node does not satisfy a trace, and all
   affected surfaces report the same missing stage.
3. A wrong typed predicate remains `INVALID_PREDICATE` across Requirements,
   RFLP and Trace Matrix views.
4. A stale Verification/Validation scope is visible as a semantic gap and is
   not counted as complete by any projection.
5. A technical Requirement with a direct PhysicalBlock target retains its
   root RFLP IDs and direct physical target consistently.
6. Existing full tests, SysML round-trip, deliverables, compile/lint/import
   gates remain green.
