# P 阶段按 Logical 作用域窄批次 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** 把 `vertical.physical` 接到独立 Logical 切片，保留完整 Function→Logical→Physical→V&V 追溯。

**Architecture:** 复用 `StructuredModelRuntime` 的批次拆分、上下文投影、Proposal Compiler 和 CAS 合并。新增 P 专用 batch size 与 prompt 约束，默认值为 1；不同批次仍可通过相同 canonical PhysicalBlock 表达共享资源。

**Tech Stack:** Python 3.11+, existing structured runtime, pytest, Ruff.

## Global Constraints

- 不启动本机模型；只用结构化夹具和现有 preview CAD 门禁。
- 不改 ModelGraph、CAS、V&V 状态机或 CAD 规则。
- 任一 P 批次失败时不提交部分 P Patch。

---

### Task 1: P singleton batching and prompt scope

**Files:**
- Modify: `src/rflp_lite/runtime/structured_model.py`
- Modify: `src/rflp_lite/adapters/openai_compatible_model.py`
- Modify: `src/rflp_lite/resources/prompts/vertical/physical.v1.md`
- Test: `tests/runtime/test_task_execution.py`
- Test: `tests/runtime/test_task_specific_prompts.py`
- Test: `tests/adapters/test_openai_compatible_model.py`

- [ ] Add `vertical_physical_batch_size`, select it for `vertical.physical`, and emit P batch metadata even for one batch.
- [ ] Add P-specific instruction requiring `logical_id`/`source_logical_ids` and `allocatedTo` to stay in the current scope.
- [ ] Assert five-input P produces five singleton requests and prompt includes the current Requirement.

### Task 2: Three-requirement product trace

**Files:**
- Modify: `tests/application/test_model_generation.py`
- Modify: `docs/DEVELOPMENT_STATUS.md`

- [ ] Record physical worklists in the three-requirement structured fixture.
- [ ] Assert each Logical slice reaches a Physical allocation and V&V remains complete.
- [ ] Record the P milestone without claiming remote Provider success.

### Task 3: Gate and delivery

- [ ] Run focused vertical tests and `tests/e2e/test_local_product_acceptance.py`.
- [ ] Run full local pytest, Ruff, compileall and architecture metrics.
- [ ] Commit only P implementation/docs/tests, preserve pre-existing remote benchmark artifacts, and push the branch.
