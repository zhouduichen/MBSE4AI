# User-Facing MBSE Workbench Design

## Context

The vertical generation path now creates a real editable ModelGraph across
requirements, functions, logical architecture, physical candidates, and V&V.
The web workbench exposes that capability, but the primary view still leaks
implementation vocabulary such as task IDs, action kinds, internal metric
names, and raw entity identifiers.  That makes the product read like a
Harness diagnostic console instead of an AI systems-engineering workbench.

## Goals

- Present the vertical result as a user-facing engineering conclusion and a
  clear next action.
- Translate stage, status, quality-check, controller, and trade-study data at
  the presentation boundary without changing the domain or API contracts.
- Keep advanced diagnostics, raw IDs, payloads, and execution ledgers
  available behind explicit advanced/details sections for engineering review.
- Make the same friendly controller vocabulary available on the Assurance
  page, while retaining stable data attributes for existing actions.
- Keep the model workbench focused on editable engineering objects and
  traceability rather than runtime implementation details.

## Non-goals

- No change to the typed ModelGraph, generation runtime, Controller policy, or
  remote-provider integration.
- No local model invocation, local model setup, or provider experiment.
- No removal of advanced JSON/SysML export or diagnostic data from APIs.
- No new UI framework or dependency.

## Design

The web presentation adapter decorates vertical stage results, methodology
findings, and Controller actions with localized labels and concise quality
summaries.  The original machine-facing fields remain in the view model where
scripts need them, but templates use the friendly fields for visible text.

The generation summary becomes the primary product surface:

- each stage shows a Chinese engineering name, localized status, entity/relation
  counts, completion-check summary, and a plain next-step hint;
- traceability metrics use Chinese labels for complete RFLP and V&V closure;
- methodology findings are presented as “工程检查”, with friendly impact and
  suggested action text;
- Controller actions show “收集证据 / 补充输入 / 重新分析 / 方案权衡” and
  the affected stage, while task IDs remain hidden from the main view;
- physical and logical candidates show engineering names and statuses, with
  technical identifiers available only in advanced details.

The Model workbench uses Chinese engineering-layer names and entity-kind /
status labels.  Raw entity IDs and payload JSON remain inside details or data
attributes needed by actions.  The Assurance page uses the same Controller
decoration and replaces raw action/task vocabulary in the visible action card.

## Acceptance criteria

1. A generated analysis page visibly presents five friendly engineering stages,
   a quality-check summary, traceability closure, and a plain next action.
2. The primary generation and assurance surfaces do not visibly render
   `task_id`, `trade_study`, `collect_evidence`, `collect_input`,
   `reanalyze`, `Methodology Findings`, or raw completion issue codes.
3. Controller and trade-study buttons retain stable action/option data IDs and
   execute through the existing endpoints.
4. Raw diagnostic ledgers, IDs, payload JSON, and runtime detail remain
   available only in explicitly advanced/detail areas.
5. Existing deterministic page/API behavior, model editing, exports, and all
   repository quality gates remain green.
