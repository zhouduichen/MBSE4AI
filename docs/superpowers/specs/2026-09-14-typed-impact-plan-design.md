# Typed Impact Plan for Local MBSE Iteration

## Context

AI4MBSE already has a typed `ModelGraph`, five-stage R→F→L→P→V&V generation,
deterministic methodology findings, Controller actions, and targeted
re-analysis endpoints. The missing product behavior is an explicit change
impact contract. At present impact is calculated as an internal, undirected
graph walk and a user edit returns only a new revision. A user cannot see which
downstream engineering stages and V&V cases must be reconsidered before
starting a local iteration.

This increment turns impact analysis into a reusable product capability. It
does not introduce another orchestration framework or replace ModelGraph as
the semantic source of truth.

## Goals

1. Calculate a deterministic, typed impact plan from one or more changed
   entities and the current graph revision.
2. Preserve the engineering meaning of the graph: requirements drive
   functions, functions are allocated to logical components, logical
   components are allocated to physical blocks, and requirements drive
   Verification/Validation cases.
3. Expose the plan immediately after a user edit and through a read-only API.
4. Use the same plan to select the earliest affected vertical stage and all
   required downstream stages for targeted re-analysis.
5. Return before/after traceability and V&V impact information after an
   iteration, while preserving accepted, locked, and user-modified entities.
6. Keep existing API fields and controller behavior backward compatible where
   practical.

## Non-goals

- No local LLM invocation or model service startup.
- No asynchronous job queue in this increment.
- No automatic overwrite of accepted, locked, or user-modified graph nodes.
- No replacement of the existing five-stage generation contract with all
  23 fine-grained task calls.
- No new SysML language coverage; ModelGraph remains the semantic IR and
  SysML remains the interchange projection.

## Design

### 1. Impact planner

Add `rflp_lite.methodology.impact` with a side-effect-free `ImpactPlan` and a
single planner entry point. The plan is calculated against an explicit graph
revision and contains:

- `trigger_entity_ids` and their `trigger_kinds`;
- `impacted_entity_ids` and `impacted_stages`;
- `selected_stages`, ordered from the earliest affected vertical stage through
  Assurance;
- legacy `recommended_tasks` for Controller compatibility;
- bounded `impact_paths`, where each path retains entity IDs and relation
  predicates;
- impacted VerificationCase and ValidationCase IDs;
- a deterministic reason and graph `revision`/`snapshot_hash`.

The traversal uses an allowlisted relation policy rather than treating every
graph edge as equivalent. Forward delivery edges include `satisfiedBy`,
`allocatedTo`, `realizedBy`, `verifiedBy`, `validatedBy`, `supportedBy`, and
`mitigatedBy`. Reverse traversal is allowed for trace edges so a change in a
function, logical component, or physical block can find its driving
requirement and downstream assurance. Behavioral context edges
(`decomposes`, `derivedFrom`, `exchangesWith`, `connectedTo`, `participatesIn`,
and `occursIn`) are included only when they connect the changed entity's
typed neighborhood; they do not create an unbounded all-graph cascade.

The planner maps entity kinds to vertical stages using the existing
`VerticalStage` ordering. A requirement change selects Requirements through
Assurance; a function change selects Functional through Assurance; a logical
change selects Logical, Physical, and Assurance; a physical or assurance
change selects the corresponding stage and any downstream assurance work.
If no valid seed exists, the planner raises the existing domain not-found
error instead of returning a misleading empty plan.

### 2. Application integration

`ModelGenerationService` consumes the planner for `controller_plan`,
`reanalyze`, `continue_generation`, and the final result of a generation run.
`ReviewService.request_reanalysis` uses the same plan rather than maintaining
its own task-selection fallback. The existing stage executor remains the
single mutation path; the planner only decides scope and reports impact.

After targeted re-analysis, the result includes:

- the original trigger revision and final revision;
- selected and actually executed stages;
- before/after traceability summaries;
- impacted V&V case IDs and unresolved finding codes;
- the resulting methodology report and Controller plan.

The executor continues to pass controller decisions into structured stage
generation and the existing compiler continues to protect locked or
user-modified entities.

### 3. API and workbench behavior

Add a read-only endpoint:

```text
GET /projects/{project_id}/entities/{entity_id}/impact
```

It returns the current revision, snapshot hash, impact plan, and current
Controller recommendation. The entity edit response also includes the same
impact and Controller fields, so the UI can show consequences without a
second manual request. Existing `review`, `revision`, and re-analysis fields
remain present.

The entity detail workbench displays a compact “变更影响” block after an edit
or re-analysis request: impacted stages, affected V&V count, and the next
action. Detailed paths remain available in the API response and advanced
diagnostics. The existing Accept/Lock/Continue controls remain authoritative;
impact analysis does not silently execute a model change.

### 4. Error and concurrency behavior

- Impact reads are side-effect free and are bound to the returned revision.
- Edit and execute operations retain `expected_revision` checks and return
  HTTP 409 for stale writes.
- If a changed entity is locked, the existing edit conflict is returned before
  impact calculation.
- If no downstream generation is needed, the plan reports an explicit
  `no_downstream_work` outcome.
- Paths, IDs, and Controller actions are bounded and deterministically sorted
  so the result is stable for the UI, audits, and tests.

## Verification

The implementation is accepted when all of the following hold using only
deterministic offline runtimes:

1. A requirement change reaches Function, LogicalComponent, PhysicalBlock,
   VerificationCase, and ValidationCase through typed paths, while a
   disconnected entity is excluded.
2. Function, logical, and physical changes select the correct earliest
   vertical stage and downstream stages.
3. The impact endpoint and edit response carry the same revision-bound plan.
4. Targeted re-analysis returns before/after traceability and V&V impact
   metadata and does not overwrite locked or user-modified entities.
5. Existing Controller trade-study, evidence collection, continuation, and
   SysML round-trip tests remain green.
6. Compile, full pytest, Ruff, architecture metrics, and import-boundary
   checks pass.

## Rollout order

1. Implement the planner and unit tests.
2. Replace the internal impact walk and integrate application responses.
3. Add API/UI presentation and endpoint tests.
4. Run the complete offline verification gate, commit, and push.
