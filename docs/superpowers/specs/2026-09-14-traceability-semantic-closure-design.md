# Traceability Semantic Closure Design

## Context

The vertical generator creates a complete-looking R→F→L→P→V&V path and
stores the path in both graph relations and V&V payloads.  Current completion
and traceability checks mostly count relation edges, however.  A stale or
incorrect V&V scope could therefore still appear complete even when its
payload does not identify the actual downstream implementation.

## Goals

- Make vertical completion and global cross-analysis validate semantic scope,
  not just the existence of relation edges.
- Check each active requirement's function, logical, physical, verification,
  and validation scope against the ModelGraph.
- Require V&V payload scope IDs to agree with the real path, including direct
  physical scope for technical requirements.
- Expose a deterministic finding and metric when a V&V scope is stale or
  incomplete, so Controller can route the issue back to assurance/reanalysis.
- Preserve the existing typed graph, stable IDs, user edits, locked entities,
  SysML projection, and API shape.

## Non-goals

- No local model invocation or live-provider experiment.
- No automatic repair of an inconsistent user or imported V&V plan.
- No requirement that a V&V case include every possible parallel downstream
  alternative; the generated primary path remains the canonical scope.
- No new entity kind or relationship predicate.

## Design

The completion evaluator derives a canonical scope for every active
requirement using the same predicates as `build_traceability_summary`:
requirement lineage → satisfied function → allocated logical component →
allocated physical block, with direct Requirement→PhysicalBlock support for
technical requirements.  It then checks that each linked VerificationCase and
ValidationCase carries matching `requirement_ids`, `function_ids`,
`logical_ids`, and `physical_ids`.  Missing or extra scope is a semantic
completion failure.  Cases without a linked requirement remain incomplete.

The Methodology Engine records a bounded `vv_scope_mismatch` finding with the
affected requirement/case/downstream IDs and a `verification_validation`
recommended action.  Its metrics expose the count and ratio of V&V cases with
scope consistent with the graph.  Existing execution evidence is not deleted;
an inconsistent plan becomes a review item until the user or a downstream
reanalysis corrects it.

## Acceptance criteria

1. A generated five-stage model passes semantic scope checks for all primary
   R→F→L→P→V&V paths.
2. Mutating a V&V case scope without changing graph relations marks global
   cross-analysis and the assurance stage incomplete and emits a bounded
   `vv_scope_mismatch` finding.
3. Technical requirements with direct physical allocation use that physical
   ID in the expected V&V scope.
4. Multi-requirement models check each requirement independently and do not
   accept one requirement's V&V scope as another's.
5. Existing deterministic tests, exports, SysML roundtrip, page behavior, and
   architecture gates remain green.
