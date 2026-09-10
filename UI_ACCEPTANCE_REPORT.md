# PR08.1 Browser Acceptance & UI Hardening Report

## Result

**PASS — browser review chain completed at desktop viewport.**

The acceptance project is `pr08-browser-acceptance`. The visible browser flow loaded `campus_delivery_robot.json` from the Analysis upload control, then the deterministic acceptance fixture was enriched with RFLP, V&V, safety, behavior, and evidence facts so every review surface had meaningful content. The browser itself performed the review navigation and commands; no live LLM run is claimed here.

- Browser surface: Codex in-app browser
- Viewport: 1280 × 720 for normal screenshots
- Acceptance project: `workspaces/pr08-browser-acceptance`
- PR08.1 baseline: `9010b70 docs(review): record PR08 acceptance report`
- Acceptance revisions observed: r1 fixture upload, r2 fixture enrichment, r3 Edit, r4 Accept, r5 Lock, r6 Reject
- Screenshot artifacts: [`docs/superpowers/artifacts/pr08-1-ui/`](docs/superpowers/artifacts/pr08-1-ui/)

## Route-by-route acceptance

| Page | Result | Browser observation | Evidence |
| --- | --- | --- | --- |
| Documents | PASS | Read-only `inputs/` index shows `campus_delivery_robot.json` and links to Analysis. | [`00-documents.jpg`](docs/superpowers/artifacts/pr08-1-ui/00-documents.jpg) |
| Analysis | PASS | JSON fixture upload is accepted; input state becomes `已有输入`; lifecycle and model/gate summary render. | [`01-analysis-final.jpg`](docs/superpowers/artifacts/pr08-1-ui/01-analysis-final.jpg) |
| Requirements | PASS | Three requirements remain visible with full text, source/evidence counts, RFLP status, and review controls. | [`02-requirements-before-review.jpg`](docs/superpowers/artifacts/pr08-1-ui/02-requirements-before-review.jpg), [`15-requirements-final.jpg`](docs/superpowers/artifacts/pr08-1-ui/15-requirements-final.jpg) |
| Traceability | PASS | Matrix distinguishes `INVALID_PREDICATE`, `BLOCKED`, and `REJECTED`; coverage remains visible per row. | [`09-traceability.jpg`](docs/superpowers/artifacts/pr08-1-ui/09-traceability.jpg) |
| RFLP | PASS | Focused SVG renders the selected Requirement → Function → Logical → Physical path and preserves invalid trace evidence. | [`10-rflp.jpg`](docs/superpowers/artifacts/pr08-1-ui/10-rflp.jpg) |
| Assurance | PASS | O-Gate is visibly `BLOCKED` for `missing_use_case`; F-Gate, P-Gate, and Global-Gate render; V&V, Hazard, and FMEA records are present. | [`11-assurance.jpg`](docs/superpowers/artifacts/pr08-1-ui/11-assurance.jpg) |
| History | PASS | Six revisions and the review audit trail render in the immutable ledger. | [`16-history-final.jpg`](docs/superpowers/artifacts/pr08-1-ui/16-history-final.jpg) |

## Interaction acceptance

### Requirement review actions

The long safety requirement was opened in detail and edited through the new `编辑需求正文` control. After refresh, its status was `candidate` and the edited text was retained. The same requirement was then accepted and refreshed to `accepted`, locked and refreshed to `locked`, and its locked editor state was visibly replaced by the unlock guidance.

- Before edit and evidence: [`03-requirement-detail-before-edit.jpg`](docs/superpowers/artifacts/pr08-1-ui/03-requirement-detail-before-edit.jpg)
- After edit refresh: [`04-requirement-detail-after-edit.jpg`](docs/superpowers/artifacts/pr08-1-ui/04-requirement-detail-after-edit.jpg)
- Accepted: [`05-requirement-detail-accepted.jpg`](docs/superpowers/artifacts/pr08-1-ui/05-requirement-detail-accepted.jpg)
- Locked: [`06-requirement-detail-locked.jpg`](docs/superpowers/artifacts/pr08-1-ui/06-requirement-detail-locked.jpg)

An accepted maintenance requirement was rejected from its detail page and refreshed to `rejected`. The accepted detail page now exposes both Reject and Lock, matching the guarded backend transition contract.

- Rejected: [`08-requirement-detail-after-reject.jpg`](docs/superpowers/artifacts/pr08-1-ui/08-requirement-detail-after-reject.jpg)

### Re-analyze semantics

Re-analyze creates an auditable request only. The browser visibly reports:

`已创建重新分析请求，尚未执行 · 状态：Pending Execution`

The response carries `status=requested`, `execution_status=pending_execution`, and the explicit lifecycle vocabulary `requested → pending_execution → running → completed / failed / cancelled`. No asynchronous LLM execution is implied.

- Pending request feedback: [`07-reanalysis-pending-execution.jpg`](docs/superpowers/artifacts/pr08-1-ui/07-reanalysis-pending-execution.jpg)

### Revision Diff

The browser opened the Edit revision diff and showed one updated entity with the edited statement and `user_modified` payload. It also opened the later Reject revision diff, which preserved the rejected entity as an auditable change.

- Edit diff: [`17-revision-diff-edit.jpg`](docs/superpowers/artifacts/pr08-1-ui/17-revision-diff-edit.jpg)
- Reject diff: [`13-revision-diff.jpg`](docs/superpowers/artifacts/pr08-1-ui/13-revision-diff.jpg)

## Edge-state checks

- Empty intake: project `111` Analysis renders `等待输入`; the complete-run action is disabled until an input is supplied. [`14-empty-state.jpg`](docs/superpowers/artifacts/pr08-1-ui/14-empty-state.jpg)
- Missing trace: the long candidate requirement renders `BLOCKED` with zero function/logical/physical/verification coverage.
- Invalid predicate: the complete requirement path remains visible while the matrix marks the extra invalid `derivedFrom` edge as `INVALID_PREDICATE`.
- Gate failure: Assurance O-Gate renders `✗ BLOCKED` with `missing_use_case` while other gate results remain independently visible.
- Long text: the requirement table and detail page wrap the full safety statement without losing the review controls.
- Evidence: the requirement detail shows `evidence-acceptance-req3`, claim, excerpt, and source locator.
- Refresh persistence: Edit, Accept, Lock, and Reject were each followed by a browser reload and state assertion.

## Hardening changes included

- Uploaded JSON fixtures now use the existing deterministic `seed_fixture` path, and Analysis advertises `.json` support.
- Added the read-only Documents page and project navigation entry.
- Added guarded requirement statement editing to the detail page.
- Added explicit Re-analyze request/execution state semantics and non-ambiguous UI feedback.
- Exposed Reject for accepted requirements in the detail page.

## Verification

- Focused application and web tests: passed
- Full web test package: passed
- Full suite: passed (exit 0)
- Ruff: passed
- Compileall: passed
- Import boundary checks: 5 kept, 0 broken
- Architecture metrics: unchanged from baseline (`adapter_to_application_edges=0`, `module_cycles=0`, `web_facade_methods=0`)

Unrelated benchmark working-tree changes remain outside this PR08.1 acceptance work and must not be staged.

## Known limitation

PR08.1 deliberately does not connect the newly created Re-analyze request to asynchronous WorkflowRunner execution. It only makes the current behavior explicit and auditable. That execution integration belongs to a later scoped change and is not represented as a browser PASS here.
