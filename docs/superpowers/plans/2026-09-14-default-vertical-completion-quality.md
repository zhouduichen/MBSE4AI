# Default Vertical Completion Quality Plan

## 1. Add deterministic stage completion reporting

- Extend the completion module with a pure evaluator for a
  `VerticalStageSpec`.
- Reuse the existing 23-task semantic predicates and emit ordered checks and
  stable issue codes.
- Add focused methodology tests for a passing stage and a missing functional
  relation/payload.

## 2. Integrate reports into product generation

- Add additive completion fields to `StageResult` and serialization.
- Evaluate the current graph after every stage patch.
- Make missing kinds or internal completion failures produce `needs_review`
  and bounded warnings while preserving candidate patches.
- Verify normal generation and targeted reanalysis expose the report.

## 3. Close deterministic vertical runtime gaps

- Add the five semantic markers identified during the audit.
- Keep measurement and human-review states explicit; do not manufacture
  evidence.
- Add assertions that the offline generated graph passes every internal task.

## 4. Verify and publish

- Run focused tests first, then the full repository gates.
- Review the diff for accidental local-model access and unrelated changes.
- Commit and push the design and implementation to the current GitHub branch.

