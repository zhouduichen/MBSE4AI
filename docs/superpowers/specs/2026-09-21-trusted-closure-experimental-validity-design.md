# MBSE4AI v0.3: Trusted Closure & Experimental Validity

## Status

Approved implementation target for the current v0.3 workstream.

## Problem

The current ModelGraph workbench can generate, trace, and review engineering
facts, but several trust boundaries are not yet system-wide invariants. Empty
requirement sets can satisfy ratio-based gates, generic patches can carry
lifecycle metadata, long-running workers can continue after losing a run
lease, and benchmark scores can be assembled without exercising the same
verifier/repair path as production.

## Goals

1. Closure is a strict semantic decision: at least one in-scope
   Accepted/Locked Requirement exists and every such requirement has a complete
   R→F→L→P→Verification→Validation trace. Candidates, placeholders, human
   review flags, unresolved issues, and incomplete execution evidence fail.
2. Entity lifecycle transitions are explicit and authority-checked:
   CANDIDATE→VALIDATED→ACCEPTED→LOCKED. LLM/runtime output can only create
   candidates; verifier code can validate; user or explicit policy can accept;
   only the user can unlock a locked entity. Generic task patches cannot write
   status or producer metadata.
3. Task execution follows Generate→Compile→Validate→Structured Feedback→Revise
   and re-validation. Only a fully validated patch may reach CAS.
4. Run leases are exclusive and checked around external work, repair, and CAS.
   A failed claim terminates work, and finally blocks release leases.
5. Every legacy task has an explicit least-privilege contract: input/output
   kinds, predicates, fields, scope, operation budget, precondition, and
   postcondition.
6. Benchmark tracks execute real graph mutation, gate evaluation, fault
   detection, repair, recovery, and deterministic regression through one
   external evaluator.

## Non-goals

This workstream does not expand CAD vendor coverage, high-fidelity MDO, or
domain-specific model packs. Those integrations remain bounded by the
capability matrix and are evaluated only where they pass through the same
ModelGraph trust boundaries.

## Design

### Trusted closure

Introduce a single closure evaluator used by `P-Gate`, `Global-Gate`,
`VerticalCoverage`, and `ClosureService`. It returns explicit failure reasons
for empty scope, invalid lifecycle state, missing stage links, missing evidence
or execution results, placeholders, human-review flags, and unresolved issues.
Ratios for an empty set are diagnostic only and never determine a pass.

The closure scope is the set of Requirement entities that are Accepted or
Locked and are not rejected/deprecated. A closure result is persisted only
after the evaluator and all phase gates pass.

### Lifecycle and review authority

Add a domain transition policy and transition command that records actor,
authority, previous/next status, provenance, reason, revision, and impact
invalidation. Patch validation rejects status/producer writes unless the
patch is a ReviewService or verifier transition with an explicit authority
token. Locked entities are immutable to model-generation tasks and can only be
unlocked by a user command.

### Verifier-grounded retry

Make validation feedback a typed record with `code`, affected entity IDs,
expected/actual values, failing relation, evidence gap, and retry count. The
executor compiles and validates each generated response before returning it.
The workflow records each attempt and sends structured feedback into the next
request. Max-attempt exhaustion routes to repair or human review; it never
commits an unvalidated patch.

### Lease safety

Extend the repository run API with owner-checked heartbeat, release, and
assert-lease operations. Model generation acquires a unique lease, terminates
immediately when claim fails, checks ownership before/after model, batch,
repair, and CAS operations, and releases in a `finally` block. Repository CAS
accepts the run lease as an additional precondition for run-owned patches.

### Task contracts

Replace implicit `None` predicate expansion with explicit policies in the task
catalog. Add precondition/postcondition identifiers to `TaskSpec` and evaluate
them in the executor. The four core trace tasks have narrowly scoped relation
policies matching their declared trace rule.

### Benchmark validity

Normalize every track output to a ModelGraph and evaluate it with the same
closure, gate, lifecycle, consistency, and determinism evaluator. Implement
real A/B/C/D/E tracks and a fault-injection path that mutates a copy, observes
verifier localization, repairs only the affected trace, and checks that
unrelated graph content is unchanged.

## Delivery sequence

1. Trusted closure and lifecycle authority, including negative tests.
2. Lease ownership and verifier-grounded retry, including two-worker and
   expired-lease tests.
3. Explicit task contracts and benchmark track/evaluator parity.
4. Full local suite, architecture checks, deterministic benchmark, then remote
   or offline acceptance evidence.

## Acceptance evidence

The implementation must include executable tests for every hard acceptance
case in the v0.3 request, including empty/partial closure, lifecycle bypass,
locked mutation, lease races, stale CAS, structured retry, precise repair, and
same-input graph-hash determinism. A green legacy suite alone is not
considered sufficient.
