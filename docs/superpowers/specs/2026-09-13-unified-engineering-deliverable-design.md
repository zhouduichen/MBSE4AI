# Unified Engineering Deliverable Design

## Context

AI4MBSE already maintains a typed `ModelGraph`, deterministic projections, a
SysML v2 subset exchange, and review/continuation actions. The current product
gap is that these capabilities are exposed as separate technical endpoints.
There is no single user-facing result that answers “what did the system
engineer produce?” and no stable contract that ties the model, its analyses,
and its reports to one revision.

This slice keeps the full product objective intact and makes the existing
vertical path observable as one engineering deliverable. It does not add a
new LLM provider, new persistence model, or new approval state machine.

## Goal

For one project revision, generate a deterministic, downloadable deliverable
package from the same `ModelGraph`, containing:

- SysML v2 subset exchange text;
- requirements inventory;
- RFLP architecture view;
- requirement traceability matrix;
- V&V plan and coverage status;
- architecture report with layer counts, allocations, gaps, and gate status;
- a manifest identifying the project, revision, snapshot hash, and every
  artifact.

The package must be readable by the existing UI and importable back through
the existing SysML endpoint without losing entity or relation identity.

## Product flow

```text
Project ModelGraph at revision N
             |
             v
EngineeringDeliverableService
             |
   +---------+----------+------------------+
   |                    |                  |
structured package   ZIP download      UI summary
   |                    |                  |
   +-----------> SysML export/import <----+
```

The UI presents a single “导出完整交付包” action from the model workbench.
The action reports the source revision and snapshot hash so the user can
recognize whether a package is stale after editing or continuing generation.

## Architecture

### Application service

Create `rflp_lite.application.deliverables` with a small service boundary:

```python
class EngineeringDeliverableService:
    def build(self, project_id: str) -> Mapping[str, object]: ...
    def export_zip(self, project_id: str) -> tuple[bytes, str]: ...
```

`build` loads exactly one graph revision and composes existing pure
projections (`build_requirements_view`, `build_rflp_view`,
`build_traceability_view`, and `build_assurance_view`) plus
`graph_to_sysml`. It also creates two deterministic report projections:
`vv_plan` and `architecture_report`. No report may invent a PASS/SATISFIED
claim: missing or incomplete evidence remains explicitly marked as a gap.

`export_zip` serializes the same package into a ZIP with UTF-8 JSON, Markdown,
and SysML files. It must use only the Python standard library. ZIP member
names, JSON key ordering, and report ordering are deterministic so identical
graph snapshots produce identical bytes apart from the ZIP timestamp; the
implementation sets a fixed member timestamp to make the full archive
deterministic too.

### Package contract

The JSON returned by `build` has this shape:

```json
{
  "format": "ai4mbse.engineering-deliverable.v1",
  "project_id": "…",
  "revision": 0,
  "snapshot_hash": "…",
  "artifacts": {
    "model": {"format": "model-json-v1", "content": {}},
    "sysml": {"format": "sysml-v2-subset", "content": "…"},
    "requirements": {"format": "requirements-view-v1", "content": {}},
    "rflp": {"format": "rflp-view-v1", "content": {}},
    "traceability": {"format": "traceability-view-v1", "content": {}},
    "vv_plan": {"format": "vv-plan-v1", "content": {}},
    "architecture_report": {"format": "architecture-report-v1", "content": {}}
  }
}
```

The package is a snapshot, not a second source of truth. `model` is the exact
graph serialization used for diagnostics; all other artifacts are projections
of that graph and carry the same revision/hash in their header. The ZIP uses
the following stable paths:

```text
manifest.json
model.json
model.sysml
requirements.json
rflp.json
traceability.json
vv-plan.json
vv-plan.md
architecture-report.json
architecture-report.md
```

### V&V plan

The V&V projection is requirement-centered. Each requirement has verification
and validation rows, method, pass criteria, case identifiers, and an explicit
status (`PASS`, `MISSING_VERIFICATION`, `MISSING_VALIDATION`, or
`INCOMPLETE`). It also includes coverage metrics from the existing assurance
projection. The Markdown form is a human-readable rendering of the same
structured rows; it is not independently authored data.

### Architecture report

The architecture projection summarizes entity counts for operational,
functional, logical, physical, and assurance kinds; valid/invalid trace edges;
allocation counts; requirement coverage; and gate summaries. It includes
open gaps and their entity IDs. It reports `PASS`, `DEGRADED`, or `BLOCKED`
from existing facts and never hides incomplete layers.

## Web API and UI

Add read-only endpoints:

```text
GET /projects/{project_id}/deliverables
GET /projects/{project_id}/deliverables/download
```

The first returns the structured package. The second returns an
`application/zip` response with a stable filename. Existing `/export` and
`/sysml/import` endpoints remain backward-compatible.

The model workbench gains a compact delivery panel showing revision/hash and
links to the structured package and ZIP download. It does not expose TaskSpec,
Patch, CAS, validator, or provider internals.

## Error handling

- A missing project or graph uses the existing API error mapping.
- A package can be generated for an incomplete graph; gaps are data in the
  report, not transport failures.
- Unsupported output formats continue to return the existing contract error.
- The package is generated from one loaded graph, so all artifacts share one
  revision and snapshot hash.

## Testing and acceptance

Add focused tests for:

1. complete and incomplete graphs produce the required artifact names and
   statuses;
2. all artifacts share revision/hash and report output is deterministic;
3. ZIP members contain the structured artifacts and SysML round-trips through
   the existing importer;
4. both Web endpoints expose the package and download media type;
5. the workbench exposes the delivery action and source revision.

The slice is accepted only when the focused tests, full test suite, Ruff,
Import Linter, `verify_full.py`, and a real 23-task run all pass. The broader
goal remains open after this slice until that run demonstrates the complete
R→F→L→P→V&V product behavior.

