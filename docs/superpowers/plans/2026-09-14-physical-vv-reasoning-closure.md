# Physical-to-V&V Reasoning Closure Plan

## 1. Encode physical impact evidence

- Extend physical feasibility rows with logical/function scope and bounded
  resolution options.
- Copy the resolved scope and decision options into the deterministic physical
  payload.

## 2. Carry the scope into assurance

- Resolve each requirement's downstream RFLP scope in the vertical V&V
  runtime.
- Add scope, constraint fields, execution-evidence status, and open questions
  to both verification and validation plans.

## 3. Verify and publish

- Add focused methodology/runtime/e2e assertions for the conflict and normal
  paths.
- Run pytest, compileall, Ruff, architecture metrics, and import-linter.
- Review the diff for local-model access, update product status docs, commit,
  and push to the current GitHub branch.
