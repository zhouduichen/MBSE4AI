# PR08 Industrial MBSE Review & Visualization Design

## Scope

PR08 adds an engineering review surface on top of the existing immutable
`ModelGraph` and repository. It does not replace the domain model, runtime,
workflow runner, or repository. The implementation is split into five
reviewable slices: projections, requirements and traceability, RFLP, behavior
and assurance, and history/audit.

## Architecture

```text
SQLite ModelRepository / ModelGraph
        |
        v
application.projections (pure read ViewModels)
        |
        +--> ReviewService (validated Patch/CAS/revision/audit)
        |
        v
resource API + resource pages
        |
        v
HTML tables, detail panels, deterministic SVG
```

Projection functions receive one graph snapshot and repository read data. They
must be deterministic, side-effect free, and must reuse the named trace rules
and coverage matrix semantics. Every top-level projection includes the
project, revision, and snapshot hash. Templates consume dictionaries produced
by the projection boundary; they do not infer relationships or statuses.

Review commands use `ModelService.apply_patch`, with the current graph
revision as CAS. A command records an audit event after the repository applies
the patch. No route or template writes SQLite. Locked entities remain
protected by the existing domain patch policy; a stale revision is returned as
a conflict.

## ViewModel contract

The projection package provides typed frozen dataclasses for:

- requirement rows and requirement details;
- traceability rows and RFLP graph nodes/edges/gaps;
- operational, behavior, and assurance summaries;
- gate summaries, runs, steps, revisions, and revision diffs.

All collections are sorted by stable identifiers. Entity IDs and source IDs are
retained. Requirement coverage is calculated for every requirement for review
visibility, while gate-compatible accepted-only coverage remains available in
the same projection.

## Review state and commands

Supported transitions are Candidate → Accepted, Candidate → Rejected,
Accepted → Locked, Locked → Accepted (unlock), and editable non-locked
entities → user-modified revision. Rejection changes status and preserves the
entity. Edit merges a bounded payload patch, marks the entity as user modified,
and records a stale downstream signal. Re-analysis delegates to the existing
`AnalysisService`/workflow runner; it never calls an LLM from the web layer.

## Resource surface

The resource API exposes requirements, details, traceability, RFLP and focused
RFLP trace, operational/behavior/assurance summaries, history and revision
diff. Review actions are POST commands with stable JSON responses and map
not-found, locked, invalid transition, and CAS errors to distinct HTTP
statuses. The UI adds Requirements, RFLP, Behavior & Assurance, and History
pages while retaining the existing analysis/model pages.

## Deterministic diagram strategy

RFLP and behavior diagrams are generated from projection nodes and edges only.
The renderer is an intentionally small SVG layout with stable ordering and
text labels. It highlights a selected requirement, dims unrelated nodes, and
renders missing trace gaps as explicit issue nodes. SVG is presentation only;
the projection remains the source of engineering semantics.

## Persistence additions

The existing revision, patch, run, step, issue, and audit tables are reused.
Small repository read methods list revisions and patches and load revision
snapshots. This supports history and diff without introducing a second model
store. Existing rows remain immutable from the UI.

## Verification

Unit tests cover deterministic projections, predicate-aware trace gaps,
coverage/status aggregation, review transitions, locked/CAS failures, and
revision diffs. Web tests cover the JSON routes and the complete review story
on a fixture containing candidate, accepted, locked, missing, and invalid
trace data. The final acceptance report records baseline/final commits,
tests, metrics, screenshots or render checks, limitations, and unfinished
items.
