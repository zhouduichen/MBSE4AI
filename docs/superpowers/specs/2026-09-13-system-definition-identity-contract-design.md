# `system_definition` Entity Identity Contract Design

## Goal

Align the `system_definition` TaskSpec and prompt with the repository state so a
fixture that already contains one System-of-Interest enriches that entity
instead of proposing another one.

## Contract

- If the context contains exactly one active `SYSTEM`, the proposal must have
  no `entities`, exactly one `updates` entry targeting that canonical entity,
  and no `deprecations`.
- If the context contains no `SYSTEM`, the proposal must have exactly one new
  `SYSTEM` entity, no `updates`, and no `deprecations`.
- A `system_definition` proposal must leave the graph with at least one active
  `SYSTEM`; adding a second System-of-Interest is rejected by the identity
  validator.
- SYSTEM payloads use explicit fields for mission, boundary, objectives,
  environment assumptions, exclusions, and open questions.
- Proposal `local_ref` values remain proposal-scoped and unique. The Compiler
  rejects duplicates; it never renames them.

## Implementation Boundary

Only the `system_definition` prompt, TaskSpec completion contract, output
schema, and the task-scoped identity validation rule change. Compiler behavior,
Patch application, CAS, and workflow failure routing remain unchanged.

## Verification

Add deterministic tests for:

1. Existing SYSTEM → one update, no added SYSTEM, revision increment after
   application.
2. Missing SYSTEM → exactly one added SYSTEM.
3. Duplicate proposal `local_ref` → Compiler rejection.
4. Second SYSTEM proposal → `identity_conflict` rejection.

Then run the real Qwen/Ollama `system_definition` probe with
`max_output_tokens=4000`; only after this contract is stable should the
three-task dependency chain resume.
