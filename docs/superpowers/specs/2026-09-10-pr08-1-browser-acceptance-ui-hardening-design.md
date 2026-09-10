# PR08.1 Browser Acceptance & UI Hardening Design

## Objective

Close the PR08 acceptance gap with a real desktop-browser walkthrough and only the small UI/ingestion fixes exposed by that walkthrough. The acceptance target is the complete review chain:

`Documents → Analysis → Requirements → Traceability → RFLP → Assurance → History`

This increment does not introduce a new workflow engine, agent system, persistence model, or benchmark behavior.

## Findings to address

1. The Analysis upload control advertises text/document formats, while the existing deterministic E2E fixture path is JSON-aware. A browser acceptance run therefore cannot load the complete fixture through the visible upload flow.
2. Requirement detail exposes a Re-analyze action whose current feedback can be read as if execution has started, although the endpoint only creates an auditable request.
3. Requirement detail has review actions but no visible statement-edit control, so the required Edit → refresh acceptance path cannot be exercised through the UI.

## Design

### Fixture upload

Keep the uploaded file in the project `inputs/` directory. When the uploaded file is a valid MBSE fixture JSON, route it through the existing `seed_fixture` use case; otherwise preserve the current document-parser path. Add `.json` to the visible Analysis input hint so the browser control and backend behavior agree.

### Requirement review semantics

Keep the existing guarded review endpoints and revision checks. Add a compact statement editor to the requirement detail page and submit it to the existing `edit` endpoint. After successful Accept, Reject, Edit, Lock, or Unlock, reload the page so the rendered status is the post-action state.

For Re-analyze, preserve the auditable request creation behavior but expose its state explicitly:

`Requested → Pending Execution → Running → Completed / Failed / Cancelled`

This PR only creates the request. Its response therefore reports `status=requested`, `execution_status=pending_execution`, and the user-facing label `已创建重新分析请求，尚未执行`; it must not claim that an LLM run has started.

### Browser acceptance evidence

Use one isolated, complete campus-delivery-robot project. Load it through the visible Analysis upload control, then inspect each review page in a desktop viewport. Exercise the empty state, missing trace, gate-fail, long requirement text, evidence links, review actions with refresh, re-analysis feedback, and revision diff. Capture screenshots at the key review surfaces and write `UI_ACCEPTANCE_REPORT.md` with the exact route, observed result, and any known limitation.

## Acceptance criteria

- The browser can upload the JSON acceptance fixture from Analysis and the project becomes reviewable.
- The seven-page chain renders without an error at desktop width.
- Requirement editing is available in the browser and its saved text/status survives refresh.
- Re-analyze visibly says the request was created and has not executed.
- Accept/Reject/Edit/Lock behavior and revision diff are observable after refresh.
- Empty, missing-trace, gate-fail, long-text, and evidence states are represented in the report.
- Automated tests, lint, compile, and architecture metrics remain green.
- `UI_ACCEPTANCE_REPORT.md` and screenshot artifacts are committed without staging unrelated benchmark changes.
