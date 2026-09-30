# Complete design product flow

## Goal

Expose one explicit, opt-in application path that can carry a requirement-backed
project through concept selection, CAD preview/execution, design review and
ModelGraph/deliverable write-back. Preserve the existing default behavior that
stops at human review boundaries.

## Scope

- Add `complete_design` to the application and Web product-flow entry points.
- When enabled, select the requested concept candidate or the deterministic
  first Pareto-front candidate, apply it, approve/execute the ready CAD plan,
  run design review, and apply the CAD model.
- Return every intermediate record in the flow response and keep review status
  visible. A design review that is not `passed` produces
  `completed_with_warnings`, never a silent success.
- Add an offline end-to-end test for requirement → concept → CAD → review →
  ModelGraph → deliverable.

## Non-goals

- Do not remove clarification or review gates from the default path.
- Do not start a local model, remote model, SSH session or FreeCAD process.
- Do not auto-approve formal engineering evidence or manufacturing findings.
