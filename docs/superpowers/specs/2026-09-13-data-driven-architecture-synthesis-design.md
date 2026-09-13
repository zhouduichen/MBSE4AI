# Data-Driven Architecture Synthesis Design

## Context

当前多需求输入已经能形成多条 Requirement 和 Function，但离线纵向 Runtime 在 Logical 阶段始终创建一个固定的“配送协同逻辑架构”，Physical 阶段也始终创建一个固定的“配送协同执行平台”。这会让多条职责看起来已经有 RFLP 链，却没有真实的功能分区、实现分配或需求约束传播。

## Goal

让可复现的 F→L→P fallback 依据当前 ModelGraph 内容生成架构，而不是依赖固定领域名称：

- Functional 中的每个活动 Function 都进入一个可解释的逻辑分区；
- 明确共享 `logical_partition`/`partition_key` 或 `shared_state` 的 Function 可以形成同一分区；没有分区信号时默认按职责隔离；
- 每个 Logical Component 都有明确的承载 Function、分区依据、内聚/耦合信号和接口连接；
- 每个 Logical Component 至少有一个以其名称和职责命名的 Physical Block 候选；
- Function 关联的 Requirement 约束和来源 ID 传播到 Physical Block payload；
- 共享状态导致的高耦合仍进入现有 Methodology/Controller Trade Study，而不是被判定为无条件完成；
- 单需求场景保持现有的一个逻辑组件、一个物理候选和完整追溯行为。

## Alternatives

1. **推荐：基于图中显式信号的确定性分区。** 先消费 LLM 或规则 Runtime 已写入的 `logical_partition`、`partition_key`、`shared_state` 等字段；没有信号时按 Function 隔离。可复现、可审计，不凭名称猜测工程事实。
2. **始终一个组件。** 实现最简单，但继续掩盖多职责系统的分区和接口问题，与纵向产品目标不符。
3. **完全交给 LLM 生成分区。** 语义弹性最高，但离线验收不可复现，且无法保证每个 Function/Logical/Physical 关系都落图。

选择方案 1：LLM 负责提出语义候选，Harness 用图结构完成最低限度的可追溯架构落地，并让不确定的共享分区进入 Review。

## Architecture and data flow

```text
Requirement* → Function*
                  │
       partition_key / shared_state
                  ↓
       Logical Component* + Interface + State
                  ↓
       Physical Block* + propagated constraints
                  ↓
       Methodology: cohesion/coupling/feasibility
                  ↓
       Controller: trade study or evidence request
```

Logical grouping key的优先级为：`logical_partition`、`partition_key`、非空 `shared_state`，最后回退到 Function ID。分组顺序保持输入 Function 的稳定顺序；组件名称来自显式分区名或 Function 名称，不再使用固定领域名。单组多 Function 的组件标记为 `coupling=high`，促使 Methodology 报告分区评审；单 Function 组件标记为 `cohesion=high`、`coupling=controlled`。

Physical 阶段读取 Function→Logical、Requirement→Function 关系，为每个 Logical Component 创建一个候选实现。候选的 `source_requirement_ids` 和 `propagated_constraints` 只复制图中已有数据；未知数值仍保持 `needs_measurement`，不推断可行性。现有 `ALLOCATED_TO`、Traceability、CAS、Review 和 ZIP/SysML 投影继续使用这些实体。

## Safety and compatibility

- 只新增缺失的架构实体和关系；不更新、删除或覆盖锁定/用户修改实体；
- 架构实体 ID 由稳定 kind/name/source 信息生成，重复运行保持幂等；
- 关系必须经过现有端点和 PatchPolicy 校验；
- 单需求已有测试的状态、完整追溯和 `needs_measurement` 语义不变；
- LLM 提案仍由现有 Compiler/Validator 负责，fallback 的确定性逻辑不绕过结构化 Runtime。

## Testing and acceptance

- 单元测试验证显式 `partition_key`/共享状态分组以及无信号时的职责隔离；
- 多需求 E2E 验证三条 Function 生成三个 Logical Component、三个 Physical Block，且每条 Function 都有 L→P 分配；
- 验证 Physical payload 带有对应 Requirement IDs 和约束传播结果；
- 验证共享状态分区生成 `coupling=high` 并触发现有 `logical_partition_needs_review`；
- 单需求、自然语言/文档、多 SysML 输入、交付包和 23-task 兼容测试保持通过；
- 全量 pytest、verify_full、compileall、Ruff、Import Linter 和架构指标通过。
