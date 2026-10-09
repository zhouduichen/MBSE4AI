# Unified Pipeline Intake Design

## Context

The default five-stage generation path already converts text and imported documents through `IntakeDraft → CAS → ModelGraph` before R→F→L→P→V&V. The explicit 23-task pipeline still calls `RequirementInputService` at the Web boundary and the CLI only compiles `--text`; an ingested Word/PDF can therefore be present in the repository while the pipeline starts without the structured Use Case/Activity framework.

## Decision

Introduce one application-level `InputPreparationService` that owns the input boundary for both generation paths. It accepts a project, optional text/document IDs, the selected runtime and runtime metadata, and returns a serializable preparation result. When input is present it uses `RequirementsUseCaseService` with a provider that explicitly supports the intake lens, otherwise it uses the deterministic degraded intake fallback. Existing stage-only injected test runtimes keep the legacy `RequirementInputService` compatibility path; this is an adapter compatibility rule, not a second product path for configured providers.

The Web and CLI pipeline entry points pass input into the application service instead of compiling requirements themselves. Existing projects without new input keep their current graph. Applying a draft remains idempotent and CAS-backed, and the preparation event records the draft, provider metadata, revision, diagnostics, and created counts.

## Data flow

```text
text / TXT / Markdown / DOCX / PDF
        ↓
InputPreparationService
        ↓
RequirementsUseCaseService.create_draft → apply_draft
        ↓
ModelGraph: Requirement + Use Case + Scenario + Activity + evidence
        ↓
five-stage generation OR 23-task pipeline
        ↓
Traceability / SysML / deliverables
```

## Compatibility and failure behavior

- No local or remote model is started implicitly.
- A configured OpenAI-compatible adapter may perform the structured intake call; the offline runtime uses explicit `degraded`/`RULE` provenance.
- Stage-only test runtimes without `supports_requirements_intake` retain `RequirementInputService` behavior so their existing stage contract is unchanged.
- Empty projects without text or documents still raise `InputRequired` before a Run is created.
- Repeated preparation for the same input is idempotent through the existing intake hash and CAS audit records.

## Verification

The acceptance path must cover: ingested TXT/DOCX/PDF-compatible source regions, direct pipeline execution without standalone draft/apply calls, typed Use Case/Operational Scenario/Activity entities, 23 completed tasks under the offline runtime, complete traceability, SysML round-trip, and a clean isolated full test suite.
