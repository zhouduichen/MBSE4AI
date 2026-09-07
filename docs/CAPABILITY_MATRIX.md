# Capability Matrix

| Capability | Current implementation | Phase 0/1 policy | Later phase |
| --- | --- | --- | --- |
| Projects / documents | Managed project directories, TXT/Markdown/DOCX/PDF ingestion, source regions | `ProjectService` + document parser port | Richer layout extraction |
| Typed ModelGraph | Entity kinds, closed relations, status, provenance, evidence and stable IDs | `domain` is the only model truth | More domain-specific profiles |
| Methodology | 23 TaskSpecs across four phases plus Closure | `WorkflowRunner`, Context, validators and gates | Additional task templates |
| Runtime | Offline deterministic RuleRuntime and optional OpenAI-compatible structured runtime | Responses become validated local Patches | Provider-specific optimizations |
| Repository | SQLite transactions, CAS revisions, FTS, Run/Step/Patch/Issue ledger | `SQLiteModelRepository` v2 | Remote repository adapter |
| Evidence / repair | Project-scoped retrieval, optional Web gap, Gate Issue and bounded repair | Evidence never silently blocks optional sources | Richer ranking and review |
| CLI / Web | `ai4mbse`, resource API and five resource pages | Composition root owns concrete adapters | Auth and collaboration |
| Quality gates | pytest, compileall, architecture budget, ruff and Import Linter | All current checks pass | CI packaging matrix |

## Completion rule

Only behavior and boundaries verified by tests are marked complete. Missing
engineering information remains explicit as a gap; this matrix does not turn
planned work into an accepted product capability.
