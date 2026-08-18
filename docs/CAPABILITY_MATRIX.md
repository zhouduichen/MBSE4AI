# Capability Matrix

| Capability | Current implementation | Phase 0/1 policy | Later phase |
| --- | --- | --- | --- |
| Requirements ingestion | TXT/Markdown/DOCX/PDF paths with optional document dependencies | Preserved; artifact transformation and persistence now run through an explicit requirements-analysis service | Further Phase 2 workflow slices |
| Requirements review | Workbench candidate/review/stale flows | Preserve DTOs and routes | Phase 2 policy split |
| Incremental LLM analysis | Six block jobs with one repair path | Repository/job/model construction injected; analysis baseline, queue, completion, and retry orchestration use the explicit service; output contracts unchanged | Phase 3 strict contracts |
| RFLP generation | Deterministic and LLM-assisted paths | No semantic behavior change | Phase 5 evidence-backed model |
| MBSE views | Shared semantic model plus Graphviz/PlantUML/Matrix/fallback | Preserved and routed through injected diagram factories | Phase 5 semantic correction |
| Project bridge | Read-only scan, delta, task contracts, evidence | Preserved and routed through injected scanner/test ports | Phase 2 service split |
| Persistence | SQLite aggregate plus audit/ledger/revision tables | Application access routed through repository factory | Phase 4 recovery/CAS strengthening |
| Jobs | Local JSON job ledger and daemon thread | Preserved and routed through injected job factory | Phase 4 recoverable state machine |
| CLI/Web | Existing paths and payloads | Startup and facade wiring use composition root; payloads unchanged | Phase 6 interaction closure |
| Quality gates | pytest, schema validation, Import Linter, build | AST guard and global forbidden-import gates verified | Phase 7 CI hardening |

## Completion rule

Only behavior and boundaries verified by tests are marked complete. Missing
engineering information remains explicit as a gap; this matrix does not turn
planned work into an accepted product capability.
