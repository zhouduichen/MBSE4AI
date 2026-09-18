# Capability Matrix

| Capability | Current implementation | Phase 0/1 policy | Later phase |
| --- | --- | --- | --- |
| Projects / documents | Managed project directories, TXT/Markdown/DOCX/PDF ingestion, source regions | `ProjectService` + document parser port | Richer layout extraction |
| Requirements / use-case intelligence | Structured `IntakeDraft` from document regions or text; entity/attribute/explicit and inferred constraint candidates; Use Case, Operational Scenario and Activity framework; source/evidence traceability; candidate review/apply | Remote structured model proposal plus deterministic schema/constraint/ModelGraph compiler; offline path is explicitly degraded | Domain datasets, richer ambiguity resolution and accepted scenario libraries |
| Concept layout generation (2.1) | Versioned declaration-only domain pack; JSON/CSV historical scheme import and similarity retrieval; deterministic 3–5 feasible candidates; hard-constraint margins; reproducible conceptual 2D top/side SVG; candidate application to `PhysicalBlock` | Fixed-wing v1 example pack and deterministic reference-guided generator; formal candidate approval remains human-controlled | More domain packs, richer historical libraries and high-fidelity geometry |
| Multidisciplinary rapid evaluation (2.2) | Aerodynamics, structures and weight/CG adapters run in bounded parallel batches with cache keys, failure isolation, source/version/hash evidence and Pareto/optimization feedback | Built-in analytical evaluators are development evidence; missing/failed discipline cannot pass; remote tools/surrogates use the same adapter port | Customer-approved simulation/surrogate adapters and validated formal evidence |
| Natural-language CAD intent and execution plan (3.1) | Natural-language design intent, explicit clarification questions, unit-normalized parameters, allowlisted CAD operation plan, preview → approval → execution gate, parametric preview payload and ModelGraph `PhysicalBlock` write-back | Vendor-neutral preview adapter is development evidence; local model profiles are never invoked; remote structured model is opt-in | Customer-approved CAD adapter and real revision/feature evidence |
| Drawing/PMI annotation (3.2) | Shared semantic dimensions, hole callouts, datum A and basic GD&T recommendations with deterministic collision-aware placement for top/isometric views | Preview annotations are development evidence and require human review for formal drawings | Real 2D drawing/3D PMI adapter, standards configuration and customer acceptance |
| DFM/DFA design review (3.3) | Versioned preview rules for material, envelope, wall thickness, fillet radius, hole edge distance and tool access; findings carry severity, feature/location, evidence, recommendation and review status | Findings are development evidence; formal manufacturing conclusions are not claimed | Customer-approved rule library, geometry kernel integration and validated process limits |
| Typed ModelGraph | Entity kinds, closed relations, status, provenance, evidence and stable IDs | `domain` is the only model truth | More domain-specific profiles |
| Methodology | 23 TaskSpecs across four phases plus Closure; V&V plans require method, objective, precondition, test condition, input, stimulus, procedure, expected result and acceptance criteria | `WorkflowRunner`, Context, validators and gates | Additional task templates |
| Executable V&V plans | VerificationCase and ValidationCase expose the same nine-field executable plan; source evidence and execution evidence remain separate | Shared `VV_PLAN_FIELDS`, semantic completion findings and revision-bound deliverables | Method-specific procedures and approved external adapters |
| Runtime | Offline deterministic RuleRuntime and optional OpenAI-compatible structured runtime | Responses become validated local Patches | Provider-specific optimizations |
| Repository | SQLite transactions, CAS revisions, FTS, Run/Step/Patch/Issue ledger | `SQLiteModelRepository` v2 | Remote repository adapter |
| Evidence / repair | Project-scoped retrieval, optional Web gap, Gate Issue and bounded repair | Evidence never silently blocks optional sources | Richer ranking and review |
| CLI / Web | `ai4mbse`, resource API and five resource pages | Composition root owns concrete adapters | Auth and collaboration |
| Quality gates | pytest, compileall, architecture budget, ruff and Import Linter | All current checks pass | CI packaging matrix |

## Completion rule

Only behavior and boundaries verified by tests are marked complete. Missing
engineering information remains explicit as a gap; this matrix does not turn
planned work into an accepted product capability.
