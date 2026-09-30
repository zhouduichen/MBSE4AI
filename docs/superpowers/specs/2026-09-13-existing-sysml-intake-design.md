# Existing SysML Intake Design

## Context

The product goal accepts existing models and historical engineering assets as
inputs. AI4MBSE already has a deterministic SysML v2 subset importer, but it
is only reachable through a raw-body API call. The Web workbench therefore
cannot perform the intended flow of importing a model and then continuing
generation or review.

## Goal

Allow a user to upload an existing `.sysml` file from the Web workbench and
import it into the current project ModelGraph. The imported graph must remain
editable, traceable, and available to the existing generation and delivery
flows.

## Design

Add a multipart endpoint:

```text
POST /projects/{project_id}/sysml/import/upload
```

The endpoint accepts a multipart field named `file`, decodes UTF-8, and
delegates to the same `sysml_to_graph` and CAS append path as the existing raw
body endpoint. It returns the import revision, entity count, and relation
count. Existing IDs are rejected before any write, so an upload cannot
silently overwrite the current project.

The Analysis intake panel adds a second file input for “已有 SysML 模型”. It
posts the file to the upload endpoint and displays the normal intake result;
successful import reloads the page so the current revision and model counts
are visible. The generic document input keeps its existing parser and does not
pretend SysML is ordinary prose.

The endpoint is intentionally limited to the repository’s emitted SysML v2
subset. Invalid package shape, invalid metadata, unsupported enum values,
duplicate IDs, relation conflicts, and invalid UTF-8 use the existing error
mapping. No new persistence table or model state is introduced.

## Acceptance

- An uploaded SysML file creates the same entity and relation IDs in the
  target project.
- A second upload with conflicting IDs is rejected without changing the
  revision.
- The imported model can be edited through the existing CAS endpoint and can
  be exported in the unified engineering deliverable ZIP.
- The Analysis UI exposes the upload control and the endpoint result without
  exposing TaskSpec, Patch, CAS, or validator internals.

