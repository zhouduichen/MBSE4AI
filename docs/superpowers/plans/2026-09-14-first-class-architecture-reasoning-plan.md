# First-Class Logical/Physical Architecture Reasoning Implementation Plan

> **For implementation:** Required sub-skill: use `superpowers:executing-plans` to execute this plan task-by-task.

## Goal

把现有的 Logical / Physical 规则推理提升为 ModelGraph 中的一等模型事实，使产品能稳定展示“为什么这样分解、如何权衡候选架构、物理约束是否可行、冲突如何回到上游”，并保持 R→F→L→P→V&V、SysML 往返和可编辑性。

## Architecture and constraints

- 不新增实体类型或数据库迁移；新增内容作为 `LogicalComponent.payload.architecture_reasoning` 和 `PhysicalBlock.payload.feasibility_reasoning` 的可选字段。
- `ArchitectureSynthesis` 是纯读模型分析；`VerticalRuleRuntime` 通过现有 `Patch` / CAS 写入；Methodology、Controller、Workbench、SysML 只读取 ModelGraph。
- 未知物性字段只能得到 `needs_measurement`；明确违反 `max_*` / `min_*` 的候选为 `infeasible`。
- 保留现有 payload 字段和旧 fixture 的兼容性；不启动、探测或调用本机模型。

## Task 1: Add the typed reasoning payload contract

**Files:** create `src/rflp_lite/methodology/architecture_reasoning.py` and `tests/methodology/test_architecture_reasoning.py`; modify `src/rflp_lite/methodology/tasks.py`.

1. Define `logical_reasoning_payload(...)` and `physical_reasoning_payload(...)` as JSON-compatible contract builders. They must copy candidate alternatives, basis evidence, selected/recommended alternative, feasibility status, propagated constraints, conflicts, and resolution options without exposing mutable internal objects.
2. Reject malformed IDs/statuses at this boundary with the project’s existing contract exception; keep empty evidence explicit as `[]` rather than omitting it.
3. Extend the logical-component and physical-block structured-output schemas with optional object properties named `architecture_reasoning` and `feasibility_reasoning`; do not make them required so old providers/fixtures remain valid.
4. Unit-test JSON compatibility, candidate copying, `needs_measurement` versus `infeasible`, and preservation of resolution-option decision metadata.

## Task 2: Persist real Logical reasoning during vertical generation

**Files:** modify `src/rflp_lite/runtime/rule_based.py`, `src/rflp_lite/resources/prompts/vertical/logical.v1.md`, and `tests/runtime/test_vertical_rule_runtime.py`.

1. In `VerticalRuleRuntime._logical`, build the pre-commit analysis graph from the request context and generated functions/flows. Extract dependency pairs, shared-state IDs, functional-flow IDs, timing constraints, and safety-isolation evidence from the generated function payloads and relations.
2. Call `synthesize_architecture` before committing the logical patch and pass its result through `logical_reasoning_payload`. Store the selected controller variant when it exists; otherwise record `needs_review` and the recommended candidate.
3. Put the same reasoning in every generated logical component while retaining existing responsibility, partition, cohesion/coupling, interface, and decision fields. Keep the patch atomic and compatible with the existing builder/CAS path.
4. Update the vertical logical prompt to require the same evidence and alternative-partition fields when a structured provider is used.
5. Test multi-function dependency partitioning, shared-state cuts, timing/safety evidence, alternative candidates, and the selected variant in the persisted payload.

## Task 3: Persist Physical feasibility and trade reasoning

**Files:** modify `src/rflp_lite/runtime/rule_based.py`, `src/rflp_lite/resources/prompts/vertical/physical.v1.md`, and `tests/runtime/test_vertical_rule_runtime.py`.

1. In `VerticalRuleRuntime._physical`, create the temporary post-generation graph from builder operations, then call `synthesize_architecture` so physical rows include actual requirement/logical/function traceability and propagated constraints.
2. Add `feasibility_reasoning` to every physical candidate, including status, score, missing fields, conflicts, and actionable resolution options. Preserve unknown values as measurement gaps and preserve controller-created alternatives.
3. Update the physical prompt and structured contract wording to require constraint provenance, feasibility status, and resolution options.
4. Test a feasible candidate, a max-power conflict, an unknown measurement, alternative physical candidates, and requirement→logical→physical IDs in the persisted payload.

## Task 4: Prove the product vertical slice and round trip

**Files:** modify `tests/e2e/test_vertical_model_generation.py`, `tests/application/test_model_generation.py`, and `tests/application/test_sysml_v2.py` only where needed; inspect `src/rflp_lite/application/projections/common.py` and `src/rflp_lite/application/sysml_v2.py` and avoid changes if generic payload handling already suffices; update `docs/DEVELOPMENT_STATUS.md` and `docs/CURRENT_ARCHITECTURE.md` to record the delivered payload contract.

1. Add one offline end-to-end test that generates a multi-function model through R→F→L→P→V&V and asserts complete traceability plus both reasoning payloads.
2. Assert Controller analysis exposes a trade-study/re-entry action from physical conflict and that a revised run changes the revision and records impact without deleting the old graph version.
3. Assert Workbench entity cards expose the new payloads, SysML export/import preserves them, and an imported Function/Logical/Physical edit remains editable and yields an impact plan.
4. Keep the test deterministic and rule-runtime based; do not use a local or remote LLM for the offline acceptance gate.

## Task 5: Run gates, commit, and push

Run from `/Users/huangjiahao/Downloads/AI4MBSE`:

```bash
pytest -q
python -m compileall -q src
ruff check src tests
.venv/bin/lint-imports
```

Then run the smallest representative vertical test command covering the new reasoning tests and the end-to-end model-generation tests. Inspect `git diff`, `git status`, and the final commit contents. Commit with a focused message such as `feat: persist architecture reasoning in modelgraph`, push the current branch to `origin`, and verify the pushed commit with `git log origin/codex/web-audit-2026-08-18 -1`.

## Acceptance criteria

- A natural-language/fixture-driven vertical run produces R→F→L→P→V&V plus complete traceability.
- Logical components contain basis evidence, alternatives, and selection state; physical blocks contain propagated constraints, feasibility state, conflicts/gaps, and resolution options.
- Controller revision actions, Workbench cards, SysML round trip, and editability all preserve and consume those fields.
- All offline gates pass and no local model process or endpoint is started or called.
