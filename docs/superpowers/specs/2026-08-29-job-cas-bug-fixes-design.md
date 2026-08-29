# RFLP-Lite Job 与并发一致性 Bug 修复设计

## 目标

修复架构审计中确认的 Job 并发、租约恢复、LLM 异常闭环、Workbench CAS、Retry 合法性和 Job 元数据持久化问题，确保同一逻辑任务最多由一个有效 Worker 执行，旧 Worker 不能覆盖新状态，并让所有主要 Workbench 写入路径遵守乐观并发控制。

## 范围

- durable Job 的原子认领、租约所有权更新、启动恢复和并发 Retry。
- enrichment Worker 的异常归一化和 Workbench 终态同步。
- Job 运行元数据的持久化与读取兼容性。
- WebFacade、需求分析、项目分析、基线、验证、测试及 CLI 的 CAS 写入。
- Retry 的 Job 类型、状态和 runner 返回值校验。
- 针对每个已复现问题的回归测试。

不包含新的业务能力、外部队列、跨机器调度器或 UI 重构。

## 设计

### 1. Job 原子认领和租约

在 `JobRepositoryPort` 与 SQLite adapter 中增加条件认领能力。认领必须在一个 SQLite 写事务中完成，并以 `status = 'queued'` 为条件；只有认领成功的调用方才能启动 Worker。已有 active idempotency Job 可被检查，但不能重复启动。

Worker 获得固定 `lease_id` 后，JobService 在 Worker 线程上下文中自动把后续状态更新转换为带 lease 条件的更新。条件为 Job 仍为 `running` 且 lease 与 Worker 相同。心跳继续使用现有 lease 校验。启动恢复将过期 running Job 标为 `interrupted`，旧 Worker 后续更新全部被拒绝。

Retry 使用同样的原子条件迁移，只允许 `failed`、`degraded`、`interrupted`，并在认领时递增 attempt、生成新 lease。竞争失败的一方返回明确的不可重试错误，不执行 runner。

### 2. Job 元数据

通过版本化迁移为 `jobs` 增加 JSON metadata 列，保存现有调用方写入但当前被丢弃的字段：`retryable`、`active_block`、`batch_index`、`batch_count`、`source_total`、`source_attempted`、`source_analyzed`、`block_durations_ms`、`superseded_by_content_revision`、`model`、`analysis_mode`、`pack_ids` 和 `pack_hashes`。读取时将 metadata 展平到兼容的 Job record，未知字段保留在 metadata 中而不影响旧记录。

### 3. Enrichment 错误闭环

分块执行捕获所有普通运行时异常，并将其转换为可重试的 block failure/degraded 诊断；不吞掉进程级 `KeyboardInterrupt`/`SystemExit`。Worker 外层对无法进入分块循环的普通异常执行 best-effort aggregate finalization，把 Workbench 的 `auto_analysis.status` 设为 `degraded` 或 `failed`，再让 durable Job 进入相同终态。旧 lease 或 CAS 失效时不再写入旧 Workbench。

Retry 入口先验证 Job kind 为 `requirements.enrichment`，状态属于允许集合，且目标 Block 不是已成功状态。runner 返回非 object 时按 Job contract 失败处理。

### 4. Workbench CAS

所有由已读取 state 推导出的保存操作，使用读取时携带的 `revision` 与 `content_revision` 作为 expected values；不再在 stale state 准备完成后重新读取“最新快照”作为 CAS 基准。Coordinator 仍在同一事务中读取 current、执行 mutation 并提交条件写入。

需求初始保存、WebFacade 的基线/项目验证/项目测试、项目分析 use case、需求 scope/migration 写入以及 CLI 的 Workbench 写入均补齐 expected revision。并发冲突向上抛出既有 `ConcurrentModificationError`，不覆盖胜出的 state。

## 测试策略

- 两个并发相同幂等 key 只执行一次 runner。
- 旧 lease 在启动恢复后不能把 `interrupted` 改回 `running/succeeded`。
- 两个并发 Retry 只允许一个 runner，attempt 只递增一次。
- 普通模型异常最终同时收敛 Job 与 Workbench 状态。
- terminal 或错误 kind 的 Retry 被拒绝。
- Job metadata 更新后可完整读取。
- Retry 的非 dict 返回值进入失败路径。
- WebFacade stale state 在并发写入后被 CAS 拒绝。
- 全量现有测试、架构检查、Ruff、Pyright、构建和完整验证脚本继续通过。

## 兼容性与迁移

保留现有 `JobService.submit/submit_async/update/heartbeat/retry` 公共方法名称；新增 repository 能力使用可选协议方法或兼容实现，既有测试 doubles 不需要实现不相关字段。SQLite migration 必须可从当前 schema 3 升级，旧 Job 的 metadata 默认为空对象。现有 API 的 `completed` 映射保持不变。

