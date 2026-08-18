# Low-Coupling Phase 0 + Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a behavior-preserving Ports & Adapters boundary for repositories, jobs, project analysis, test execution, document parsing, rendering, and generation without changing the existing CLI/Web paths.

**Architecture:** Keep the project as a modular monolith. Application code receives protocol-shaped dependencies; adapters implement those protocols; `interface` and CLI obtain a fully wired application from `bootstrap/container.py`. Existing public functions remain as compatibility facades while concrete construction moves to the composition root.

**Tech Stack:** Python 3.11+, `typing.Protocol`, dataclasses, SQLite, FastAPI/Jinja/HTMX, pytest, Import Linter, setuptools build.

## Global Constraints

- Do not introduce microservices, Redis, Kafka, Celery, PostgreSQL, React/Vue, or a front-end build chain.
- Preserve the existing CLI commands, Web routes, workspace layout, JSON payloads, and deterministic behavior.
- Application and Interface must not import `rflp_lite.adapters`; only `rflp_lite.bootstrap` may assemble concrete adapters.
- Adapters may depend on Ports and Domain, but must not depend on Application or Interface.
- Every migration remains readable through the existing `migrate_workbench_state` path.
- Add characterization tests before moving behavior and keep refactoring separate from behavior changes.

## Execution status

Phase 0 and the repository/job/project-analysis/test-execution slice of Phase 1
are complete and verified. The implementation keeps the existing public paths,
adds compatibility re-exports, and leaves strict output contracts, recovery
semantics, MBSE evidence correction, and UI/CI closure for the later phases in
the source execution plan.

### Task 1: Freeze the current architecture and compatibility surface

**Files:**
- Create: `docs/CURRENT_ARCHITECTURE.md`
- Create: `docs/CAPABILITY_MATRIX.md`
- Create: `tests/architecture/test_dependency_boundaries.py`
- Modify: `.importlinter`

**Interfaces:**
- Produces a documented list of composition-root responsibilities, current adapter factories, public CLI/Web entry points, and the forbidden dependency rule used by later tasks.

- [x] **Step 1: Write the failing architecture guard**

  Add tests that scan Python AST imports under `src/rflp_lite/application` and `src/rflp_lite/interface`, reject imports whose module starts with `rflp_lite.adapters`, and allow `rflp_lite.bootstrap` as the only composition root.

- [x] **Step 2: Run the guard and record the baseline**

  Run: `.venv/bin/python -m pytest tests/architecture/test_dependency_boundaries.py -q`

  Expected: FAIL and list the current direct adapter imports. Do not weaken the test to match the baseline.

- [x] **Step 3: Document the baseline**

  Record current file responsibilities, the known direct-import locations, the preserved external entry points, and the Phase 1 target boundary in `docs/CURRENT_ARCHITECTURE.md`. Record each supported capability and its current status in `docs/CAPABILITY_MATRIX.md`.

- [x] **Step 4: Add explicit Import Linter contracts**

  Add `application-no-adapters` and `interface-no-adapters` forbidden contracts to `.importlinter`, with `rflp_lite.bootstrap` excluded from the source modules because it is the composition root.

- [x] **Step 5: Verify the baseline artifacts**

  Run: `.venv/bin/lint-imports`

  Expected: the new global contracts fail with the same direct imports listed by the AST guard; existing contracts must remain unchanged.

### Task 2: Add pure dependency contracts and test-execution value objects

**Files:**
- Create: `src/rflp_lite/ports/repositories.py`
- Create: `src/rflp_lite/ports/jobs.py`
- Create: `src/rflp_lite/ports/project_analysis.py`
- Create: `src/rflp_lite/ports/test_execution.py`
- Create: `tests/ports/test_repositories.py`
- Create: `tests/ports/test_jobs.py`
- Create: `tests/ports/test_project_analysis.py`
- Create: `tests/ports/test_test_execution.py`
- Modify: `src/rflp_lite/adapters/test_execution_config.py`

**Interfaces:**
- `RepositoryFactory = Protocol` with `__call__(path: Path) -> WorkbenchRepositoryPort`.
- `WorkbenchRepositoryPort` exposes the repository methods already consumed by `demo`, `WebFacade`, and enrichment, including `transaction`, `close`, `load_workbench`, `save_workbench`, audit, baseline, requirement, scheme, concept, and trace persistence methods.
- `JobRepositoryPort` exposes `create`, `get`, `update`, and `list` for durable job records.
- `ProjectScannerPort.scan(path) -> tuple[ActualModel, dict[str, object]]`.
- `TestExecutionPort.run(...) -> tuple[object, ...]`.
- `ResourceLimits`, `DEFAULT_TEST_TIMEOUT`, and `build_limits(...)` become dependency-free value/config definitions in `ports.test_execution`; the existing adapter module re-exports them for compatibility.

- [ ] **Step 1: Write protocol and value-object tests**

  Verify a small fake repository/factory satisfies the runtime shape, `ResourceLimits` remains JSON-normalizable, and invalid limits still raise the same `ContractViolation` messages.

- [ ] **Step 2: Run the focused tests**

  Run: `.venv/bin/python -m pytest tests/ports/test_repositories.py tests/ports/test_jobs.py tests/ports/test_project_analysis.py tests/ports/test_test_execution.py -q`

  Expected: FAIL because the new ports do not exist.

- [x] **Step 3: Implement dependency-free contracts**

  Add only protocols, immutable DTO/value objects, and validation that does not import any adapter. Keep the existing `ResourceLimits` field names and defaults byte-for-byte compatible.

- [x] **Step 4: Preserve adapter import compatibility**

  Change `adapters/test_execution_config.py` to re-export the port-owned definitions and keep `normalized_limits` as the adapter-compatible helper.

- [x] **Step 5: Run the focused tests again**

  Run: `.venv/bin/python -m pytest tests/ports/test_repositories.py tests/ports/test_jobs.py tests/ports/test_project_analysis.py tests/ports/test_test_execution.py tests/adapters/test_execution_config.py -q`

  Expected: PASS.

### Task 3: Build the composition root and dependency bundle

**Files:**
- Create: `src/rflp_lite/bootstrap/__init__.py`
- Create: `src/rflp_lite/bootstrap/container.py`
- Create: `tests/bootstrap/test_container.py`
- Modify: `src/rflp_lite/interface/web/app.py`
- Modify: `src/rflp_lite/interface/cli.py`

**Interfaces:**
- `ApplicationContainer` is a frozen dataclass containing repository, job, document, model, project-scan, test-execution, diagram, discipline, scheme, and tracking factories.
- `build_container(workspace_root: Path, fixture_root: Path | None = None) -> ApplicationContainer` constructs all concrete adapters in one place.
- `create_app(..., container: ApplicationContainer | None = None)` uses an injected container when supplied and otherwise calls `build_container`.

- [ ] **Step 1: Write the container wiring test**

  Assert that `build_container` returns concrete SQLite/LLM/renderer/scanner/test-runner implementations, and that `create_app` stores the same container and facade on `app.state`.

- [ ] **Step 2: Run the wiring test to see the missing boundary**

  Run: `.venv/bin/python -m pytest tests/bootstrap/test_container.py -q`

  Expected: FAIL because `bootstrap.container` and the injectable `create_app` signature do not exist.

- [x] **Step 3: Implement the composition root**

  Move all concrete construction currently performed in `WebFacade`, `routes`, `cli`, and enrichment entry points into `build_container`. The container may import adapters; no Application or Interface module may do so.

- [x] **Step 4: Route Web and CLI startup through the container**

  Change only startup/wiring code. Keep command parsing, route paths, facade method names, and response payloads unchanged.

- [x] **Step 5: Run the wiring and startup tests**

  Run: `.venv/bin/python -m pytest tests/bootstrap/test_container.py tests/interface/web/test_app.py tests/interface/test_cli.py::test_web_command_uses_safe_defaults -q`

  Expected: PASS.

### Task 4: Inject repository, job, generation, and parsing dependencies into Application

**Files:**
- Modify: `src/rflp_lite/application/web_facade.py`
- Modify: `src/rflp_lite/application/intelligence/enrichment_jobs.py`
- Modify: `src/rflp_lite/application/requirements_workbench.py`
- Modify: `src/rflp_lite/application/compile.py`
- Modify: `src/rflp_lite/application/ingest.py`
- Modify: `src/rflp_lite/application/requirement_inference.py`
- Modify: `src/rflp_lite/application/project_bridge.py`
- Modify: `src/rflp_lite/application/demo.py`
- Modify: `src/rflp_lite/application/concept_acceptance.py`
- Modify: `src/rflp_lite/application/mbse_render.py`
- Modify: `src/rflp_lite/application/intelligence/service.py`
- Modify: `src/rflp_lite/application/intelligence/bridge.py`
- Create: `tests/application/test_dependency_injection.py`

**Interfaces:**
- Every migrated Application service accepts the relevant port/factory as an optional constructor or function argument supplied by `ApplicationContainer`.
- Compatibility functions retain their existing signatures by accepting a `dependencies` keyword only where needed; the container-backed path is used by Web/CLI.
- `merge`/domain behavior remains unchanged in this phase; only construction and calls cross the new ports.

- [ ] **Step 1: Add characterization tests around existing behavior**

  Cover `run_demo`, `WebFacade.create_workspace`, enrichment load/save, `compile_claims`, `ingest_requirements`, project scanning, and MBSE rendering with fake ports. Assert the existing return shapes and stable hashes.

- [ ] **Step 2: Run the characterization tests**

  Run: `.venv/bin/python -m pytest tests/application/test_dependency_injection.py -q`

  Expected: FAIL for the fake-injection cases while existing behavior remains available.

- [x] **Step 3: Replace direct construction with ports**

  Remove `from rflp_lite.adapters...` imports from Application. Replace concrete constructors with injected factories and keep a single compatibility wrapper at the boundary where an old function still needs to be called.

- [x] **Step 4: Move direct LLM calls behind `GenerativeModel`**

  Adapt `requirement_inference` and the legacy requirements suggestion path to receive a model port. Preserve the current one-call/one-repair behavior and error types.

- [x] **Step 5: Run focused behavior tests**

  Run: `.venv/bin/python -m pytest tests/application/test_dependency_injection.py tests/application/test_demo_workflow.py tests/application/test_web_facade.py tests/application/intelligence/test_enrichment_jobs.py tests/application/test_project_bridge.py -q`

  Expected: PASS.

### Task 5: Remove Interface adapter imports and add architecture gates

**Files:**
- Modify: `src/rflp_lite/interface/cli.py`
- Modify: `src/rflp_lite/interface/web/routes.py`
- Modify: `src/rflp_lite/interface/web/app.py`
- Modify: `tests/architecture/test_dependency_boundaries.py`
- Modify: `.importlinter`
- Modify: `README.md`
- Modify: `PRODUCT.md`
- Modify: `DESIGN.md`

**Interfaces:**
- CLI and routes call only Application APIs or container-provided DTO/config helpers; no interface module imports `rflp_lite.adapters`.
- AST guard and Import Linter both enforce the same rule.

- [x] **Step 1: Move limit parsing behind a dependency-free port API**

  Expose a dependency-free `build_test_limits` application helper or DTO and have CLI/routes use it; keep the existing CLI option names and defaults.

- [x] **Step 2: Move scheme import, tracking, and repository actions behind the container dependency bundle**

  Add narrow facade methods where the interface currently constructs `SQLiteRepository`, reads scheme sources, or calls MLflow directly. Do not put SQL or adapter logic into the route/CLI module.

- [x] **Step 3: Run the architecture guard**

  Run: `.venv/bin/python -m pytest tests/architecture/test_dependency_boundaries.py -q`

  Expected: PASS with no direct adapter imports under Application or Interface.

- [x] **Step 4: Run Import Linter and interface regression tests**

  Run: `.venv/bin/lint-imports`

  Expected: all contracts kept, including `application-no-adapters` and `interface-no-adapters`.

  Run: `.venv/bin/python -m pytest tests/interface tests/e2e/test_professional_mbse_workflow.py -q`

  Expected: PASS with unchanged routes and payloads.

### Task 6: Phase 0 + Phase 1 verification and handoff

**Files:**
- Modify: `docs/CURRENT_ARCHITECTURE.md`
- Modify: `docs/CAPABILITY_MATRIX.md`
- Modify: `README.md`
- Modify: `docs/DEVELOPMENT_STATUS.md`

- [x] **Step 1: Run the complete quality gate**

  Run:

  ```bash
  .venv/bin/python -m compileall -q src
  .venv/bin/lint-imports
  .venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
  .venv/bin/python -m pytest -q
  .venv/bin/python -m build --no-isolation
  ```

  Expected: compile, architecture, schema, tests, and wheel/sdist build all pass. If an environment-specific optional dependency is unavailable, record the exact command and failure without changing source to hide it.

- [x] **Step 2: Update the architecture and capability records**

  Mark only verified boundaries as complete; list remaining Phase 2–7 work explicitly.

- [x] **Step 3: Review the final diff**

  Run: `git diff --check` and `git status --short`.

  Expected: no whitespace errors; unrelated user files remain untouched.
