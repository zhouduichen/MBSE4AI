# Physical-to-V&V Reasoning Closure Design

## Context

The default five-stage path already produces physical candidates, propagated
constraints, V&V plans, and Controller trade-study actions.  Those artifacts
are currently related mostly by separate payload fields and reports.  A user
can see that a physical candidate is infeasible, but the model does not carry
one explicit impact scope from the candidate back through its logical and
functional owners to the driving requirements and forward to the V&V cases.

## Goals

- Preserve a deterministic, provider-independent impact scope for each
  physical candidate: requirement, function, logical component, and physical
  canonical IDs.
- Expose concrete resolution options with a re-entry task/stage and the
  affected IDs, so a Trade Study is an actionable engineering decision.
- Put the same RFLP scope and constraint fields into generated VerificationCase
  and ValidationCase plans.
- Keep unknown measurements unknown; do not turn a plan or static check into
  a measured feasibility claim.
- Keep the existing typed ModelGraph, Controller, CAS, and SysML contracts
  unchanged; this slice only enriches existing payload/report contracts.

## Non-goals

- No local model invocation or live-provider experiment.
- No vendor, CAD, simulation, or optimizer integration.
- No new `trade_study` entity kind; the decision remains a typed payload on
  the physical candidate and a Controller action until a dedicated MBSE
  concept is justified by product use.

## Design

### Physical reasoning scope

`PhysicalFeasibilityRow` records `logical_ids`, `function_ids`, and bounded
`resolution_options`.  Each option has an option label, re-entry task/stage,
impact entity IDs, and an explicit user-decision flag.  The option set is
derived from observed conflicts, so a conflict exposes the four engineering
directions already supported by Controller: alter performance/resource
constraints, replace the physical/computing candidate, revise the requirement
budget, or increase the relevant resource budget.

The deterministic vertical physical runtime stores the same scope and options
on each `physical_block` payload under `impact_chain` and
`resolution_options`.  This makes the reasoning inspectable in ModelGraph and
available to the workbench without requiring a report-only interpretation.

### V&V scope

For each requirement, the vertical V&V runtime resolves existing
Requirement→Function→LogicalComponent→PhysicalBlock allocations, plus direct
technical Requirement→PhysicalBlock allocations.  Both V&V case payloads
record these IDs, the propagated constraint fields, a verification objective,
and explicit open questions when execution evidence is absent.  Input/source
references remain in `evidence_ids`, while actual test or demonstration
results are tracked in `execution_evidence_ids`; scenario and activity/branch
coverage remains separate from execution evidence.

### Feedback boundary

Controller decisions continue to be user-selected.  Selecting an option
passes its target and decision context into downstream reanalysis; no option
silently changes an accepted or locked engineering fact.  V&V execution still
uses the existing evidence boundary and can re-enter the affected path after a
failed result.

## Acceptance criteria

1. A physical feasibility row and its ModelGraph physical block expose the
   same requirement/function/logical/physical impact scope.
2. A physical conflict exposes four actionable options, each with a re-entry
   task/stage and affected IDs including the driving requirement and physical
   candidate.
3. Generated VerificationCase and ValidationCase payloads contain the same
   downstream RFLP scope and explicit constraint fields; missing evidence is
   represented as an open question rather than a pass.
4. Existing independent multi-requirement paths, controller decisions, SysML
   roundtrip, and all deterministic quality gates remain green.
