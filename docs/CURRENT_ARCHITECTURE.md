# Current Architecture

## Baseline

RFLP-Lite is a local modular monolith. The supported product path is:

`Artifact -> Requirement -> RFLP -> MBSE -> Simulation/Baseline/Delta/Task/Evidence`

The runtime is Python 3.11+, SQLite, FastAPI/Jinja/HTMX, and optional local or
OpenAI-compatible model/rendering integrations. Workspaces remain isolated
under the configured workspace root and SQLite remains the durable source of
truth for the local aggregate and audit history.

## Current entry points

- `rflp_lite.interface.cli:entrypoint` exposes the `rflp` CLI.
- `rflp_lite.interface.web.app:create_app` creates the local FastAPI app.
- `rflp_lite.application.web_facade:WebFacade` is the compatibility service
  used by routes and API handlers.
- `rflp_lite.application.demo:run_demo` is the deterministic vertical-slice
  entry point used by the CLI and tests.

## Current boundary leaks

Before Phase 1, several Application modules construct concrete adapters or
call adapter functions directly:

- `application.web_facade` constructs `SQLiteRepository`, LLM, discipline,
  scheme, tracking, and SVG adapters.
- `application.requirements_workbench` constructs document/claim readers and
  calls `chat_completion` directly.
- `application.intelligence.enrichment_jobs` constructs `SQLiteRepository`.
- `application.project_bridge` calls the project scanner and test executor.
- `application.mbse_render` constructs Graphviz, PlantUML, and Matrix engines.
- `application.demo`, `application.compile`, `application.ingest`, and
  `application.concept_acceptance` use concrete readers, solvers, or stores.
- `interface.cli` and `interface.web.routes` construct repositories or
  import test-execution/tracking helpers.

These are the baseline facts to remove incrementally; they are not reasons to
replace the current modular monolith with distributed infrastructure.

## Phase 0/1 verification

The first migration slice is now verified: Application and Interface have no
direct `rflp_lite.adapters` imports, concrete construction is centralized in
`bootstrap/container.py`, and the legacy adapter-facing test-execution module
continues to re-export the port-owned value objects. The AST boundary guard,
Import Linter, full pytest suite, schema validation, and package build pass.

The remaining items in the later-phase table are intentionally still open:
strict generated-output contracts, job recovery/CAS strengthening, semantic
MBSE evidence rules, UI closure, and CI hardening.

## Requirements analysis vertical slice

The first Phase 2 slice is now explicit: `RequirementsAnalysisService` owns
workspace loading, artifact transformation, baseline persistence, input-copy
creation, enrichment submission, and enrichment-status persistence. `WebFacade`
keeps the existing public methods and supplies a narrow dependency bundle from
the composition root. Retry uses the same explicit repository, job, and runner
ports and does not consult the global compatibility registry.

`requirements_workbench.py` remains the state-transition module. Review,
generation, scenario, and project-bridge orchestration remain in the facade
until their own vertical slices are specified and verified; this change does
not claim that the whole facade has been decomposed.

The slice is covered by fake-port service tests and a facade delegation test.
The full pytest suite, architecture boundary tests, Import Linter, compile
check, and diff check pass. No package/archive was regenerated for this slice.

## Phase 1 target boundary

`interface -> application -> ports -> domain`

`bootstrap -> application + adapters`

`adapters -> ports + domain`

The bootstrap composition root owns concrete construction. Application
services receive protocols/factories and retain compatibility wrappers for
existing CLI/Web calls. Adapter implementations remain local and replaceable.

## Compatibility surface to preserve

- Existing CLI command names and options.
- Existing Web route paths, templates, and JSON API payloads.
- Existing workspace directory and `.rflp` storage layout.
- Existing workbench migrations and deterministic hashes.
- Existing optional adapter fallbacks, especially built-in SVG/matrix output.
