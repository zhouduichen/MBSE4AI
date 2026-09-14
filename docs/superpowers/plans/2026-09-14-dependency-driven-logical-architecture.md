# Dependency-Driven Logical Architecture Plan

## 1. Preserve functional evidence

- Add typed source/target function ids to the deterministic functional flow.
- Test the payload against the generated function ids.

## 2. Drive logical grouping from evidence

- Resolve explicit dependency references and cluster them transitively.
- Keep implicit default flows as cross-component interaction evidence rather
  than a reason to merge all independent functions.
- Add bounded partition rationale, flow ids, and alternatives to logical
  component payloads.

## 3. Verify and publish

- Add end-to-end tests for dependency clustering and independent paths.
- Run full pytest, compile, Ruff, architecture budget, Import Linter, and
  diff checks.
- Review the diff for local-model access and push the implementation.

