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

## Historical boundary leaks and compatibility boundary

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

The Phase 2A/2B migration removed these leaks from the new Use Case path. The
following compatibility callers remain intentionally scoped for later
migration: legacy `requirements_workbench.analyze_artifact`, `ingest`,
`compile`, `demo`, `concept_acceptance`, `mbse_render`, `llm_profiles`, and
older CLI commands that still use `require_dependencies()` to preserve their
public construction surface. New files under `application/use_cases/` do not
use the global locator and do not import adapters. This is a migration
boundary, not a reason to replace the local modular monolith with distributed
infrastructure.

## Phase 0/1 verification

The first migration slice is now verified: Application and Interface have no
direct `rflp_lite.adapters` imports, concrete construction is centralized in
`bootstrap/container.py`, and the legacy adapter-facing test-execution module
continues to re-export the port-owned value objects. The AST boundary guard,
Import Linter, full pytest suite, schema validation, and package build pass.

Phases 2A, 2B, 3A, 3B, 5, 4, 6, and 7 are implemented and covered by focused
architecture, contract, semantic, recovery, interaction, and E2E tests. The
compatibility callers above remain explicit follow-up work and do not
participate in the new six-block analysis or Use Case paths.

## Requirements analysis vertical slice

The Phase 2 slice is now explicit: `RequirementsAnalysisService` owns
workspace loading, artifact transformation, baseline persistence, input-copy
creation, enrichment submission, and enrichment-status persistence. `WebFacade`
keeps the existing public methods and supplies a narrow dependency bundle from
the composition root. Retry uses the same explicit repository, job, and runner
ports and does not consult the global compatibility registry.

`application/use_cases/` now contains explicit bundles and thin orchestration
for requirement review, RFLP/MBSE generation, project analysis, test
execution, evidence recording, and enrichment blocks. `WebFacade` and the
existing routes retain their public names and payloads while translating into
these Use Cases. `requirements_workbench.py` remains the compatibility
state-transition module.

The slice is covered by fake-port service tests, dependency-boundary guards,
and facade delegation tests. LLM generation now uses only
`GenerativeModel.complete_json(GenerationRequest)` from Application code;
raw `chat_completion` is adapter-internal.

## Strict analysis and merge boundary

The six blocks (`system_scope`, `stakeholders`, `concerns_needs`,
`requirements`, `scenarios`, `architecture`) each have a versioned strict
schema. Responses are checked for bounded fields, enums, finite confidence,
source regions, workspace, and input hash before they become typed DTOs.
`ValidatedBlockResult` is the production merge boundary. A semantic validator
rejects duplicate IDs, missing sources, unknown relations, invalid relation
endpoints, and cross-workspace content. A failed block records diagnostics and
does not overwrite successful blocks; one bounded repair and per-block retry
are supported.

## Evidence-constrained MBSE

`build_mbse_semantic_model()` emits formal Function, Logical, and Physical
entities only when architecture evidence exists. Missing realizations are
represented as explicit `needs-analysis` gaps. Formal `satisfiedBy`,
`allocatedTo`, and `realizedBy` relations require matching evidence; unknown
relation predicates are diagnosed and excluded rather than normalized to an
unrelated relation. Technical requirements are emitted only when the input
contains technical evidence such as a non-analysis verification method,
parameters, constraints, or a domain rule.

## Recoverable jobs and interaction closure

Local JSON Job records now include attempt, lease, heartbeat, error,
idempotency, and per-block state. Startup recovery marks expired running jobs
as interrupted; retry selects only failed/degraded/interrupted blocks and
preserves successful results. The requirements page shows Chinese block labels,
diagnostics, provenance, gaps, and one-block retry. MBSE view switching reads
saved semantic state and does not invoke an LLM.

## Phase 1 target boundary

`interface -> application -> ports -> domain`

`bootstrap -> application + adapters`

`adapters -> ports + domain`

The bootstrap composition root owns concrete construction. Application
services receive protocols/factories and retain compatibility wrappers for
existing CLI/Web calls. Adapter implementations remain local and replaceable.

## Quality gates

The implemented path is guarded by AST dependency checks, raw LLM bypass
checks, strict six-block contract fixtures, semantic relation fixtures,
cross-workspace and partial-failure E2E tests, compile checks, Import Linter,
and the existing schema validation command.

## Compatibility surface to preserve

- Existing CLI command names and options.
- Existing Web route paths, templates, and JSON API payloads.
- Existing workspace directory and `.rflp` storage layout.
- Existing workbench migrations and deterministic hashes.
- Existing optional adapter fallbacks, especially built-in SVG/matrix output.
