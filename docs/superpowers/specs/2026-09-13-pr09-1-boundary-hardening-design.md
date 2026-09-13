# PR09.1 Boundary Hardening Design

## Goal

修复 PR09 复核发现的两个 P1 边界问题：让增量 `payload` 更新按最终合并状态进行 schema 校验，并让 Workflow 中的并发、invariant、契约和未知执行异常默认 fail-closed。

## Scope

本次只修改 ProposalCompiler 与 WorkflowRunner 的执行边界，并为这两个边界补充回归测试。P2 架构 contract 覆盖、retry 指标重命名、raw response 配置化和仓库整理不在本次范围内。

## Current Problems

1. `compile_task_proposal()` 对 `UpdateEntity.field_patch["payload"]` 直接校验局部 patch，但领域层随后会把它 merge 到现有 payload。合法的局部更新因此可能被错误拒绝。
2. `WorkflowRunner._run_phase()` 的 catch-all 将所有未分类异常写成 `DEGRADED` 并继续执行后续 task。这会吞掉 `WorkflowInvariantError`、`ConcurrentModificationError`、意外 `ContractViolation` 和未知程序错误，破坏 fail-closed 语义。

## Design

### 1. Incremental payload validation

在 ProposalCompiler 更新分支中：

```python
payload_patch = _mapping(item.field_patch["payload"], "updates.field_patch.payload")
merged_payload = {**dict(entity.payload), **payload_patch}
_validate_entity_payload(entity.kind, merged_payload, request)
```

编译出的 `UpdateEntity` 仍保存原始 `payload_patch`，不把完整 merged payload 改写成替换操作。这样校验与 `domain.model.apply_patch()` 的实际 merge 语义一致，同时保留 Patch 的最小增量和确定性。

测试使用一个具有多个 required 字段的 payload schema：

- 仅更新其中一个字段且最终 merged payload 完整时，编译成功并保留增量字段；
- 更新字段导致最终 merged payload 不满足 schema 时，抛出 `ContractViolation`，且不产生 Patch。

### 2. Fail-closed Workflow exception routing

在 `_run_phase()` 的 task execution try/except 中保留已分类的 structural/compiler/transport response route，并将异常路由明确化：

| 异常 | task 状态 | run 行为 | 后续 task |
| --- | --- | --- | --- |
| `ConcurrentModificationError` | `FAILED` | 记录 concurrency failure | `BLOCKED` |
| `WorkflowInvariantError` | `FAILED` | 记录 invariant failure | `BLOCKED` |
| `ContractViolation` | `FAILED` | 记录 contract failure | `BLOCKED` |
| 其它 `Exception` | `FAILED` | 记录 `internal_error` | `BLOCKED` |

所有 fail-closed 路由都不得写入 committable patch；异常发生后立即调用 `_block_pending_steps()`，更新 run 为 `DEGRADED`（保持现有 RunSummary/API 兼容），并返回当前 phase 的 failure stage。未知异常的诊断包含 task id、异常类型和消息，不包含完整模型响应。

现有已知 semantic response（`TaskExecutionResponse` 为 `DEGRADED` 且无 structural/compiler/transport failure stage）继续走 completion/semantic 处理，不因本次 catch-all 收紧而误分类。由于 `ConcurrentModificationError` 不属于 `ContractViolation`，它必须在 catch 顺序中单独位于通用异常之前。

### 3. Regression tests

新增或扩展以下测试：

- `test_partial_payload_update_validates_merged_payload`
- `test_partial_payload_update_rejects_invalid_final_payload`
- Workflow invariant violation produces `FAILED` task and blocks remaining tasks;
- concurrent modification produces `FAILED` task and blocks remaining tasks;
- unknown exception produces `FAILED` task and blocks remaining tasks;
- an invalid/non-completed response patch still never reaches repository append.

测试通过 fake runtime 和最小 SQLite repository 验证状态台账与 revision，确保失败边界不仅体现在返回值，也体现在持久化的 step 状态、blocked diagnostics 和仓库 revision 不变性上。

## Verification

实现后按以下顺序验证：

1. 定向 ProposalCompiler 与 Workflow 测试；
2. 完整 `pytest`；
3. `ruff check`；
4. `python -m compileall src tests`；
5. `lint-imports` 与现有 architecture metrics。

不重新执行 20×3 conformance probe，也不在本轮修改 ProposalCompiler/TaskProposal 协议、Prompt、模型配置或 benchmark fixture。

## Acceptance Criteria

- 局部 payload 更新依据 merged final state 校验，合法增量不再被 required 字段误拒绝；
- merged final state 无效时在 Patch 创建前拒绝；
- CAS、Workflow invariant、ContractViolation 和未知异常均不会继续执行后续 task；
- fail-closed task 为 `FAILED`，其后待执行 task 为 `BLOCKED`；
- 失败路径不产生 repository mutation；
- PR09 既有测试和架构检查保持通过。
