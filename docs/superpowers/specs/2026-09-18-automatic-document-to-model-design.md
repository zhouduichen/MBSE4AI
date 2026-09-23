# Automatic Document-to-Model Generation Design

## Problem

The repository already contains two separate capabilities: document/requirement/use-case intake and the five-stage R→F→L→P→V&V generator. The default generation entry point currently connects documents to raw requirement splitting, so a Word/PDF input does not automatically pass through the structured requirement, constraint, use-case, scenario, and activity compiler.

The product goal requires one generation request to turn an input document or natural-language requirement into a reviewable, traceable MBSE ModelGraph and its SysML/engineering deliverables.

## Scope

When a generation request contains text, document IDs, or a project with ingested documents and no active requirement input has yet been compiled, the generation service will:

1. call the existing `RequirementsUseCaseService` with the configured structured model when one is explicitly selected;
2. otherwise use its existing deterministic degraded fallback;
3. validate and apply the resulting candidate draft through the existing CAS/ModelGraph compiler;
4. record the intake linkage in project audit events; and
5. continue through the existing five vertical stages.

The intake remains a candidate/reviewable result. This change does not auto-accept entities, bypass validation, or start a local/remote model implicitly. Existing projects with no new input continue to use their current graph as the generation seed, and the standalone intake API remains available for human review before application.

## Data flow

```text
text / imported DOCX / imported PDF
        ↓
RequirementsUseCaseService.create_draft
        ↓ schema + source/constraint normalization
RequirementsUseCaseService.apply_draft
        ↓ CAS patch: Requirement + UseCase + Scenario + Activity + trace links
ModelGenerationService five-stage generator
        ↓
ModelGraph → traceability / SysML v2 subset / engineering deliverables
```

The configured model is obtained only from the generation runtime already selected for the request. The offline path uses no model process and is explicitly marked degraded in the intake audit record.

## Compatibility and failure behavior

- A request with existing active Requirements does not re-import input implicitly; new explicit input is merged idempotently through the structured intake compiler.
- Draft and apply operations remain idempotent by input hash and draft ID.
- A malformed structured response follows the existing intake fallback path and is visible in diagnostics.
- CAS conflicts and invalid compiled relations remain errors; no partial graph write is accepted.
- The existing RFLP/V&V stages, SysML format, review gates, and optional remote FreeCAD adapter are unchanged.

## Verification

The local acceptance suite will prove that one text/document generation request creates Requirements, Use Case, Operational Scenario, Activity, complete R→F→L→P→V&V traceability, SysML round-trip/edit evidence, and the existing concept/detail-design deliverables. Additional adapter tests will prove DOCX region extraction and retain PDF parsing as an optional dependency boundary.
