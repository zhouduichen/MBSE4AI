# Default Vertical Completion Quality Design

## Context

The product's default generation path presents five user-facing stages, while
the existing methodology already defines 23 finer-grained reasoning tasks.
The five-stage path currently checks only whether each stage produced a
required entity kind. That allows a structurally valid response to look
complete even when its required relations, payload evidence, or reverse
checks are missing.

This slice makes the five-stage path an honest projection of the 23-task
method. It does not add another model call or a new workflow engine. It adds a
deterministic completion report at each stage and closes the corresponding
gaps in the deterministic vertical runtime.

## Goals

- Evaluate every internal reasoning task listed by the active vertical stage.
- Return bounded, machine-readable checks and issue codes with each stage.
- Mark a stage `needs_review` when its typed graph does not satisfy an
  internal completion rule, while preserving structurally valid candidate
  output for review and downstream repair.
- Keep the deterministic offline vertical runtime's normal output complete
  against the same rules.
- Preserve the five-stage UX and the existing R→F→L→P→V&V traceability API.
- Never start or call a local model service; this is graph validation and
  deterministic runtime work only.

## Non-goals

- No repeated stability benchmark runs.
- No new provider, prompt, schema, compiler, audit, or UI subsystem.
- No automatic acceptance of an LLM result that fails semantic completion.
- No change to the legacy 23-task `WorkflowRunner` control flow.

## Design

### Stage completion evaluator

Add a pure `evaluate_vertical_stage(stage, graph)` function next to the
existing task completion rules. It evaluates the stage's `reasoning_tasks` in
order using the existing deterministic semantic rules. Each check contains
the task id and a boolean result; failed checks produce stable
`completion_semantic:<task_id>` issue codes. Existing required-kind checks
remain separate so callers can distinguish missing object types from missing
relations or payload evidence.

### Application integration

After a stage patch is applied, `ModelGenerationService` evaluates the current
graph and includes the checks and issue codes in `StageResult` and its JSON
representation. Missing kinds and completion issues both make the stage
`needs_review` and add a bounded warning. The stage still completes its run
record and preserves structurally valid candidates, so a reviewer can inspect
and repair the graph instead of losing the model.

The same behavior applies to targeted reanalysis and Controller-driven
continuation because both already use `_execute_stage`.

### Deterministic runtime closure

The offline vertical runtime will emit the semantic markers required by the
existing completion rules:

- operational requirements are marked as derived by system requirement
  derivation and linked to the concern;
- requirements receive functional behavior ids after functions are created;
- physical candidates explicitly state when no technical constraint is
  present;
- requirements receive a reverse feasibility review;
- verification cases receive a checked cross-analysis marker.

These markers are evidence in the ModelGraph, not a claim that physical
measurements have been performed. Existing `needs_measurement` feasibility
and V&V evidence states remain unchanged.

### Compatibility

The new `StageResult` fields are additive. Existing result consumers keep
their current fields. Existing happy-path deterministic tests should remain
completed; structured-model fixtures that intentionally omit semantic
relations should now report `completed_with_warnings` and expose the exact
missing internal tasks.

## Acceptance criteria

1. A complete deterministic five-stage generation has all internal stage
   checks passing and remains `completed`.
2. An incomplete structured functional response is persisted as a candidate,
   has `stage_results[functional].status == "needs_review"`, and reports the
   failed internal task without failing the whole run.
3. Stage JSON/audit-facing data includes checks and issue codes.
4. Targeted reanalysis exposes the same stage completion information.
5. Full pytest, compile, lint, import-layer, architecture-budget, and diff
   gates pass.

