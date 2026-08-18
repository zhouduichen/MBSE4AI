# Project Analysis Vertical Slice Implementation Plan

**Goal:** Extract the project-scan analysis orchestration from `WebFacade` while preserving its public API, persistence calls, and `project.analyzed` audit event.

**Architecture:** Keep `application.project_bridge.analyze_project_state` as the deterministic state transformation. Add a narrow `ProjectAnalysisService` that loads the workbench, invokes that transformation through an injected callable, and persists the resulting baseline, evidence, tasks, and audit record. `WebFacade` only adapts its existing dependency bundle and delegates.

**Constraints:** Do not change verify/test execution, routes, payloads, database schema, or package/archive files. Do not use the global dependency registry inside the new service.

## Tasks

- [x] Add fake-port tests for analysis persistence and a WebFacade delegation test.
- [x] Implement `ProjectAnalysisDependencies` and `ProjectAnalysisService.analyze(workspace, source)`.
- [x] Wire the service into `WebFacade.analyze_workspace_project` and remove only its duplicated orchestration.
- [x] Run focused tests, architecture checks, Import Linter, compile, diff, and full pytest.
