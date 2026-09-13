# Task-Level Relation Predicate Policy Design

## Goal

Prevent LLM proposals from selecting relation predicates that are outside a
TaskSpec's methodologically valid write vocabulary.

## Contract

`TaskSpec.allowed_predicates` is represented by `PatchPolicy.allowed_predicates`
and is projected into the provider-facing TaskProposal schema. The first three
real tasks use these policies:

| Task | Allowed predicates |
| --- | --- |
| `system_definition` | none |
| `stakeholder_analysis` | `hasConcern` |
| `stakeholder_requirements` | `derivedFrom` |

For `stakeholder_requirements`, the preferred trace is
`Requirement --derivedFrom--> Concern`; when no Concern is available,
`Requirement --derivedFrom--> Stakeholder` is allowed. `supportedBy` is not
allowed for this task.

Tasks without an explicit policy retain the existing full vocabulary until
their method-specific matrices are reviewed.

## Implementation Boundary

The change is limited to TaskSpec construction, PatchPolicy propagation,
provider schema generation, the three task prompts, and contract tests. The
Compiler and endpoint validator remain fail-closed final defenses; no automatic
relation rewriting or retry behavior is added.

## Verification

Run the full test suite, then use the fixed Ollama
`qwen3.5:9b-q8_0` / `max_output_tokens=4000` setup for:

1. `stakeholder_requirements ×10`.
2. `system_definition → stakeholder_analysis → stakeholder_requirements ×5`.
3. If the chain is 5/5, add `lifecycle_analysis` and `scenario_exploration`
   for a five-task Operational prefix ×5.

The 23-task lifecycle remains out of scope.
