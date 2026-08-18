# Requirements Analysis Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the requirements-analysis and incremental-enrichment orchestration from `WebFacade` into a narrow, explicitly injected application service without changing public CLI/Web behavior.

**Architecture:** Keep `requirements_workbench.py` as the pure state-transition module. Add `RequirementsAnalysisService` under `application/use_cases` for workspace loading, persistence, task submission, and task-status persistence. `WebFacade` remains a compatibility facade and supplies a narrow dependency bundle; the service never calls the global dependency registry.

**Tech Stack:** Python 3.11+, dataclasses, typing Protocol, SQLite repository port, local durable job service, pytest, Import Linter.

## Global Constraints

- Preserve `WebFacade.analyze_requirements(...)` and `retry_requirement_enrichment(...)` signatures and return shapes.
- Preserve event names, SQLite transaction boundaries, input-file paths, workbench JSON, job states, and existing exception classes.
- Do not change prompts, generated-output schemas, MBSE semantics, route paths, CLI options, or UI copy.
- The new service receives only narrow dependencies and must not call `require_dependencies()`.
- Do not package, commit, or modify unrelated reference files in the workspace.

---

### Task 1: Make artifact transformation functions explicitly injectable

**Files:**
- Modify: `src/rflp_lite/application/requirements_workbench.py:268-274,1018-1022`
- Test: `tests/application/test_ingest_compile.py`

**Interfaces:**
- `analyze_artifact(filename, content, *, dependencies=None) -> dict[str, object]`
- `merge_artifact(state, filename, content, *, dependencies=None) -> dict[str, object]`
- Existing calls without `dependencies` continue using the Phase 1 compatibility registry.

- [x] **Step 1: Add an explicit-dependency characterization assertion**

  Extend the existing ingestion/compile test with a minimal fake dependency bundle that delegates `artifact_reader`, `document_parser_factory`, and `claim_extractor_factory`, then call `analyze_artifact(..., dependencies=fake_dependencies)` and assert the artifact path and source spans are unchanged.

- [x] **Step 2: Run the focused test before implementation**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/application/test_ingest_compile.py
  ```

  Expected: the existing tests pass and the new explicit-dependency call fails because the function does not yet accept the keyword.

- [x] **Step 3: Thread the optional dependency through both functions**

  Change the compatibility lookup to:

  ```python
  deps = require_dependencies(dependencies)
  ```

  and make `merge_artifact` forward the same dependency value to `analyze_artifact`. Do not alter the transformation logic or serialized output.

- [x] **Step 4: Run the focused test after implementation**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/application/test_ingest_compile.py tests/application/test_requirements_workbench.py
  ```

  Expected: PASS.

### Task 2: Implement the narrow requirements-analysis service

**Files:**
- Create: `src/rflp_lite/application/use_cases/__init__.py`
- Create: `src/rflp_lite/application/use_cases/requirements_analysis.py`
- Test: `tests/application/test_requirements_analysis_service.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RequirementsAnalysisDependencies:
    repository_factory: RepositoryFactory
    job_service_factory: JobServiceFactory
    enrichment_runner_factory: Callable[[Path], EnrichmentJobRunner]
    load_state: Callable[[WorkspaceRef], dict[str, object] | None]
    analyze_artifact: Callable[[str, bytes], dict[str, object]]
    merge_artifact: Callable[[dict[str, object], str, bytes], dict[str, object]]


class RequirementsAnalysisService:
    def analyze(
        self, workspace: WorkspaceRef, filename: str, content: bytes, *,
        merge: bool = True, model: GenerativeModel | None = None,
    ) -> dict[str, object]: ...

    def retry(
        self, workspace: WorkspaceRef, job_id: str, *,
        model: GenerativeModel | None = None,
    ) -> dict[str, object]: ...
```

- [x] **Step 1: Write fake-port tests for new and merge flows**

  Build a fake repository that records `transaction`, `save_workbench`, `record_audit`, and `save_requirement_records`; a fake job service that returns both `queued` and `degraded` records; and a fake enrichment runner. Assert that `analyze` saves `requirements.analyzed` for a new artifact, `requirements.merged` for an existing artifact, writes the input copy, and preserves the task status branch.

- [x] **Step 2: Write retry-path and no-global-registry tests**

  Configure the service with only `RequirementsAnalysisDependencies`, clear the compatibility registry in the test, and assert `retry` reads the old job, calls the runner with the supplied model, updates `auto_analysis`, and saves `requirements.enrichment_retry_queued` without raising a missing-global-dependency error.

- [x] **Step 3: Run the new tests to capture the missing service**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/application/test_requirements_analysis_service.py
  ```

  Expected: FAIL because the new package and service do not exist.

- [x] **Step 4: Implement exact state and persistence orchestration**

  Move only the logic currently inside `WebFacade.analyze_requirements` and `retry_requirement_enrichment` into the service. Keep these operations explicit:

  ```python
  state = deps.merge_artifact(current, safe_name, content) if merge and current else deps.analyze_artifact(safe_name, content)
  state = bind_project_scope(state, workspace.name)
  state["analysis_config"] = normalize_analysis_config(state.get("analysis_config"))
  if state.get("spans"):
      state = generate_draft_model(state)
      state = accept_initial_workbench(state)
  ```

  Then preserve the existing input copy, transaction events, requirement-record projection, enrichment submission, and queued/immediate-completion branches. Implement the record projection as a private pure helper in the service.

- [x] **Step 5: Run service tests and existing enrichment tests**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/application/test_requirements_analysis_service.py tests/application/intelligence/test_enrichment_jobs.py
  ```

  Expected: PASS.

### Task 3: Wire the service through WebFacade and remove duplicate orchestration

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py:116-126,930-1072,1323-1349`
- Modify: `src/rflp_lite/bootstrap/container.py`
- Test: `tests/application/test_web_facade.py`
- Test: `tests/interface/web/test_requirements_enrichment.py`

**Interfaces:**
- `WebFacade` constructs `RequirementsAnalysisService` with a narrow bundle derived from its injected Phase 1 dependencies.
- `WebFacade.analyze_requirements(...)` delegates to `service.analyze(...)`.
- `WebFacade.retry_requirement_enrichment(...)` delegates to `service.retry(...)`.
- `_project_analysis_model()` remains the compatibility model factory for this slice; it passes a `GenerativeModel | None` into the service.

- [x] **Step 1: Add a facade delegation characterization test**

  Replace the service on a facade instance with a spy implementing `analyze` and `retry`; call both public facade methods and assert workspace, filename/content, merge flag, job ID, and model are forwarded exactly once.

- [x] **Step 2: Run facade and Web enrichment tests before wiring**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/application/test_web_facade.py tests/interface/web/test_requirements_enrichment.py
  ```

  Expected: existing behavior passes; the new spy test fails until the facade delegates.

- [x] **Step 3: Build the narrow dependency bundle in WebFacade**

  Bind `repository_factory`, `job_service_factory`, `load_state=self.requirements`, the explicit artifact/merge functions, and an enrichment-runner factory that passes the facade's existing `ApplicationDependencies` into `EnrichmentJobRunner`. Do not expose the full bundle to the new service.

- [x] **Step 4: Replace only the two orchestration bodies with delegation**

  Keep `_auto_complete_requirements`, review methods, save methods, and all public signatures unchanged. Remove only the duplicated analyze/retry persistence logic after the service passes compatibility tests.

- [x] **Step 5: Run facade, Web, and CLI regression tests**

  Run:

  ```bash
  RFLP_CONFIG_DIR=/tmp/rflp-codex-empty .venv/bin/python -m pytest -q tests/application/test_web_facade.py tests/interface/web/test_requirements_enrichment.py tests/interface/test_cli.py
  ```

  Expected: PASS.

### Task 4: Quality gates and handoff

**Files:**
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `docs/superpowers/plans/2026-08-18-requirements-analysis-vertical-slice.md`

- [x] **Step 1: Run static and focused quality gates**

  Run:

  ```bash
  .venv/bin/python -m pytest -q tests/architecture/test_dependency_boundaries.py tests/application/test_requirements_analysis_service.py
  .venv/bin/lint-imports
  .venv/bin/python -m compileall -q src tests
  git diff --check
  ```

  Expected: all commands exit 0 and no Application/Interface adapter import appears.

- [x] **Step 2: Run the full regression suite**

  Run:

  ```bash
  RFLP_CONFIG_DIR=/tmp/rflp-codex-empty .venv/bin/python -m pytest -q
  ```

  Expected: PASS; the empty configuration directory prevents unrelated persistent LLM settings from causing network calls in degraded-mode tests.

- [x] **Step 3: Update the architecture record**

  Record that the requirements-analysis vertical slice now has a narrow service boundary, while review/generation/scenario/project use cases remain in the facade for later slices. Do not claim `requirements_workbench.py` has been split.

- [x] **Step 4: Review the final diff and leave packaging untouched**

  Run `git status --short` and confirm only the intended source, test, spec, plan, and architecture files changed. Do not modify or regenerate any ZIP artifact.
