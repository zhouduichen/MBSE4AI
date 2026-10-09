# Dependency-Driven Logical Architecture Design

## Context

The default vertical runtime already creates logical components and a
separate architecture synthesis report, but its selected partition is mostly
one function per logical component. It only co-locates functions when an
explicit partition or shared-state field is already present. Functional flow
objects also do not carry typed source/target function evidence, so the
logical model cannot explain its coupling or interface boundaries from the
functional model.

## Goals

- Preserve typed functional-flow endpoints in the ModelGraph.
- Use explicit function dependencies, dependency ids, and shared-state
  evidence to form transitive logical clusters.
- Use functional-flow endpoints to annotate cross-component exchange and
  interface evidence without collapsing unrelated requirements.
- Record partition basis, dependency evidence, cross-component flows, and
  alternatives directly on logical components.
- Keep existing independent multi-requirement behavior and traceability.
- Keep the implementation deterministic and provider-independent; no local
  model is started or called.

## Non-goals

- No automatic selection of a physical vendor or measured feasibility claim.
- No new graph database, optimizer, or benchmark campaign.
- No clustering based only on the default shared task/result flow; that flow
  is interaction evidence, not proof that all functions share one boundary.

## Design

### Functional-flow evidence

The deterministic functional stage writes `source_function_ids` and
`target_function_ids` into its canonical flow payload. The source is the
first function and the remaining functions are targets, with the single
function case represented as a self-flow. Existing flow relations remain
unchanged for compatibility.

### Dependency-aware partitioning

The logical stage builds connected groups from explicit partition keys,
shared-state keys, and function payload dependency references that resolve to
known function ids or names. Connected dependency references are clustered
transitively. Functions without such evidence remain separate. This keeps
default independent requirements separate while allowing an LLM or imported
model to express an intentional logical boundary.

### Logical evidence payload

Each logical component records resolved dependency ids, shared state,
functional-flow ids, cross-component flow ids, and a partition rationale. The
component's coupling is `high` when a functional flow crosses its boundary;
otherwise the existing controlled/high distinction is retained. The payload
also records bounded alternative partition strategies so the Controller and
Workbench can expose a trade-study starting point.

## Acceptance criteria

1. Generated functional flows contain resolvable typed endpoint ids.
2. Explicit dependency evidence clusters functions into one logical group
   transitively.
3. A default three-requirement input still yields three logical and physical
   paths and reports cross-component flow evidence.
4. Logical payloads expose partition and alternative evidence without
   inventing implementation facts.
5. Full tests and architecture gates pass.

