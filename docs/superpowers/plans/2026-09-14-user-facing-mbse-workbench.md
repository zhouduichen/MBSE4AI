# User-Facing MBSE Workbench Plan

## 1. Build presentation decoration

- Add localized vertical-stage, quality-check, finding, Controller, and
  trade-study view helpers at the web presentation boundary.
- Apply the decoration to generated runs and the Assurance controller view.

## 2. Make the primary pages business-facing

- Update the analysis generation summary to use friendly stage, quality,
  traceability, finding, and next-action text.
- Move raw task/runtime information behind advanced diagnostics and hide task
  IDs from visible action cards.
- Update the Model workbench layer/entity labels and keep raw payloads/IDs in
  detail affordances.
- Update Assurance action cards to use the same friendly view model.

## 3. Verify and publish

- Add page-level regression tests for friendly text, hidden internals, and
  retained stable action attributes.
- Run deterministic tests, compile, lint, architecture metrics, and import
  contracts.
- Review for local-model access, commit, and push the slice to the current
  GitHub branch.
