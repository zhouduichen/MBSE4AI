# Implementation Plan: Unified Pipeline Result Projection

> **For Codex:** Execute this plan task-by-task. Keep the complete lifecycle as the default product path and do not run a model locally on the developer machine.

## Goal

Expose the existing 23-task lifecycle run as one engineering result: ModelGraph revision, traceability, methodology findings, controller actions, and deliverable metadata must be available through the API, web workbench, and persisted deliverable view. The projection must be read-only and must not invoke an LLM.

## Constraints

- Keep `ModelGraph` as the only source of truth.
- Reuse `build_traceability_summary`, `MethodologyEngine`, and `SystemsEngineeringController`.
- Do not mutate CAS, revisions, audit state, or locked entities while building a report.
- Preserve explicit five-stage `mode=generate` compatibility.
- Tests must use offline fixtures or an explicitly injected remote/runtime stub; never start a local model.

## Task 1: Add the read-only report service (TDD)

Files:

- Add `src/rflp_lite/application/pipeline_report.py`.
- Add `tests/application/test_pipeline_report.py`.

Implementation:

1. Write a failing test that builds a complete offline graph with the existing service fixture, calls `PipelineReportService.build(project_id)`, and asserts traceability, methodology, controller, revision, and snapshot hash are present.
2. Assert the graph revision/hash and repository run/patch counts are unchanged before and after the projection.
3. Implement `PipelineReportService(repository, methodology_engine=None, controller=None)` with a `build(project_id)` method. Load the graph, call `build_traceability_summary(graph)`, `MethodologyEngine.analyze(graph)`, and `SystemsEngineeringController.plan(graph, methodology)`, and return plain JSON-compatible dictionaries plus `report_revision` and `report_snapshot_hash`.
4. Run the focused test.

## Task 2: Attach the report to the pipeline API

Files:

- Modify `src/rflp_lite/application/analysis_service.py`.
- Modify `src/rflp_lite/interface/web/resource_api.py`.
- Extend the existing pipeline API test and structured 23-task E2E test.

Implementation:

1. Add `AnalysisService.pipeline_report(project_id)` delegating to a `PipelineReportService` created from `runner.model_repository`.
2. In `_invoke_pipeline`, attach the report fields to the normal pipeline payload after `_run_payload(result)` and before returning it.
3. Assert API report revision/hash equal the deliverable revision/hash.
4. Assert a structured pipeline still makes exactly the catalog’s 23 model calls, proving report projection adds no model invocation.

## Task 3: Render the report in the default workbench

Files:

- Modify `src/rflp_lite/interface/web/resource_pages.py`.
- Modify `src/rflp_lite/interface/web/templates/analysis.html`.
- Extend `tests/interface/web/test_analysis_workflow.py`.

Implementation:

1. Add `_decorate_pipeline_run` to obtain a report only for pipeline runs, preserve API-provided report fields, and apply the existing methodology/controller presentation helpers.
2. Call it from `build_analysis_view` after generation decoration.
3. Let the result panel render for either a generated stage result or a pipeline report. Keep the stage rail conditional so pipeline runs do not require stage results. Use the title `完整生命周期结果` for pipeline mode and retain `完整模型生成结果` for generate mode.
4. Add a page test using `VerticalRuleRuntime` that posts the default analysis request and asserts the lifecycle result, engineering checks, logical architecture candidates, physical feasibility matrix, and next engineering actions are visible.

## Task 4: Verify, document, and publish

Files:

- Update `README.md`, `CURRENT_ARCHITECTURE.md`, and `DEVELOPMENT_STATUS.md` to describe the unified pipeline report and current R→F→L→P→V&V product path.
- Mark the corresponding design spec as implemented: `docs/superpowers/specs/2026-09-14-pipeline-result-projection-design.md`.

Verification:

1. Run focused application/API/web/E2E tests.
2. Run the complete pytest suite.
3. Run compile, Ruff, architecture metrics, and import-boundary checks used by the repository.
4. Run `git diff --check`, review the diff for accidental model execution or unrelated changes, commit, and push the branch to GitHub.

## Self-review checklist

- [ ] Default web/API path is a single complete lifecycle result.
- [ ] Report projection is read-only and makes no LLM calls.
- [ ] ModelGraph revision and snapshot hash are surfaced consistently.
- [ ] Existing explicit `mode=generate` behavior remains intact.
- [ ] The result is visible in the workbench, not only in raw JSON.
- [ ] Tests measure vertical completion rather than repeated stability runs.
- [ ] No local model is started on this computer.
