# Product Flow Orchestration Design

## Goal

Provide one application-level entry point that carries a project from document or natural-language requirements through the existing five-stage R→F→L→P→V&V model generation, optional requirement-driven concept design, optional natural-language CAD planning, and one revision-bound engineering deliverable package.

This slice closes the product handoff between already implemented services. It does not replace their review gates, invent engineering evidence, or start a local/remote model implicitly.

## Scope and non-goals

In scope:

- accept `requirement_text` and/or previously ingested `document_ids`;
- run `ModelGenerationService.generate` as the canonical R→F→L→P→V&V step;
- optionally call `ConceptDesignProjectService.run_from_requirements` and expose its 3–5 candidates, evaluations, and optimizer feedback;
- optionally call `CadWorkflowService.create_intent` and `create_plan`, preserving clarification and approval states;
- return a single JSON-safe result with all stage, concept, CAD, and deliverable status;
- keep the exact ModelGraph revision and snapshot hash attached to the result;
- expose the flow through the application service, composition root, and one resource API route;
- add offline TestClient/application/e2e acceptance tests using `VerticalRuleRuntime` and preview CAD.

Out of scope:

- automatically accepting a concept candidate or approving/executing a CAD plan;
- automatically fabricating a concept envelope when required parameters are missing;
- automatically fabricating CAD dimensions, material, or evidence;
- starting a local model, SSH tunnel, remote model, server, FreeCAD, or simulation process;
- changing the existing RFLP, concept, CAD, SysML, or V&V data contracts;
- making the new route a second generation implementation.

## API contract

Add `EngineeringProductFlowService.run`:

```python
def run(
    self,
    project_id: str,
    *,
    requirement_text: str | None = None,
    document_ids: tuple[str, ...] = (),
    include_concept: bool = False,
    optimize_concept: bool = True,
    cad_intent_text: str | None = None,
) -> ProductFlowResult:
    ...
```

`ProductFlowResult` is immutable and JSON-safe through `as_dict()`. It contains:

- `status`: `completed`, `needs_input`, `needs_clarification`, or `needs_approval`;
- `generation`: the existing `GenerateModelResult.as_dict()`;
- `concept`: `{status, missing_parameters, run}` or `{status: "not_requested"}`;
- `cad`: `{status, draft, plan}` or `{status: "not_requested"}`;
- `deliverable`: `{revision, snapshot_hash, format, artifact_names}`;
- `revision` and `snapshot_hash` copied from the final ModelGraph.

The service runs generation first. If generation is not complete enough to continue, it returns the generation result and a deliverable snapshot without invoking downstream services. If concept input is incomplete, it returns `needs_input` with the advisor payload. If CAD clarification is open, it returns `needs_clarification` with the draft. If a CAD plan is ready but not approved, it returns `needs_approval`; no CAD execution occurs.

## Data flow

```text
requirement_text/document_ids
        ↓
ModelGenerationService.generate
        ↓
ModelGraph + traceability + methodology + controller
        ├── ConceptDesignProjectService.run_from_requirements (optional)
        └── CadWorkflowService.create_intent → create_plan (optional)
        ↓
EngineeringDeliverableService.build
        ↓
ProductFlowResult with one revision/snapshot binding
```

Concept and CAD records remain in their existing audit stores. The orchestration result is a read-only projection and does not create a competing source of truth. A concept run does not become a physical model until the existing `apply_candidate` action is called. A CAD plan does not become a model until the existing approve → execute → review → apply sequence is called.

## Failure and provenance rules

- Empty input follows the existing `InputRequired` contract.
- Concept `InputRequired` is converted into `needs_input` only when concept was explicitly requested; its details are returned unchanged.
- CAD clarification is represented by the existing draft status and questions.
- Any unexpected domain/service error remains an API error; it is not converted into a successful flow.
- The result never reports a downstream artifact as accepted when it is only a candidate, preview, or pending approval.
- The deliverable is rebuilt after each flow and carries the graph's current revision and snapshot hash. No export call mutates the graph.

## Composition and HTTP boundary

`V2Services.product_flow(project_id)` constructs the service from the existing generation, concept, CAD, and deliverable services. The resource API adds:

```text
POST /projects/{project_id}/engineering-flow
```

The JSON request accepts `requirement_text`, `document_ids`, `include_concept`, `optimize_concept`, and `cad_intent_text`. The response is the `ProductFlowResult` dictionary. The route uses the selected request profile for generation/CAD exactly as the existing services do; omitted profile selection remains offline rule/preview behavior.

## Verification strategy

- application tests prove status transitions for a complete RFLP-only flow, missing concept input, CAD clarification, and CAD plan awaiting approval;
- document e2e coverage uses an already ingested document and proves source evidence, complete traceability, and the unified deliverable binding;
- API TestClient coverage proves the new route returns JSON without starting a server;
- existing full-suite, architecture-budget, Ruff, import-boundary, SysML round-trip, V&V, concept, and CAD tests remain green;
- all Python commands use an isolated `RFLP_CONFIG_DIR` and `AI4MBSE_CAD_BACKEND=preview`.
