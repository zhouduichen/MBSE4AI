# PR08.1 Browser Acceptance & UI Hardening Plan

## 1. Record the acceptance design

- [x] Add the PR08.1 design specification.
- [x] Keep the work limited to browser acceptance, wording, and small UI hardening.

## 2. Harden the visible review flow

- [x] Make uploaded JSON fixtures use the existing deterministic fixture ingestion path and advertise `.json` in Analysis.
- [x] Add a read-only Documents page for uploaded project inputs and link it into the review navigation.
- [x] Add an editable requirement statement control backed by the existing guarded `edit` action.
- [x] Make Re-analyze feedback explicitly distinguish request creation from execution, including `Pending Execution`.
- [x] Add focused regression tests for uploaded fixtures, edit behavior, and re-analysis state.

## 3. Run the real browser acceptance

- [x] Create/use an isolated complete campus-delivery-robot acceptance project.
- [x] Walk `Documents → Analysis → Requirements → Traceability → RFLP → Assurance → History` in a desktop viewport.
- [x] Exercise empty state, missing trace, gate fail, long text, evidence links, Accept/Reject/Edit/Lock refresh, and Revision Diff.
- [x] Save screenshots and write `UI_ACCEPTANCE_REPORT.md` with route-by-route observations.

## 4. Verify and hand off

- [x] Run focused tests, the full suite, lint/import checks, compile checks, and architecture metrics.
- [x] Confirm unrelated benchmark working-tree changes remain unstaged.
- [x] Commit only PR08.1 code, acceptance artifacts, and its plan/spec; do not push or merge without an explicit request.
