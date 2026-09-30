# ModelGraph Workbench Design

## Goal

让用户在 AI 生成完整 ModelGraph 后，能够在同一个 Web 工作台中查看并继续审查 Functional、Logical、Physical 和 V&V 实体，而不需要理解内部 Task、Patch 或 Repository 实现。

## Scope

本增量只补齐产品工作台的可见性和通用实体审查入口：

- 复用现有 `ModelGraph`、projection、ReviewService 和 CAS API；
- 在现有 MBSE 模型页按工程层展示真实实体和关系计数；
- 对非 Requirement 实体提供 Edit、Accept、Reject、Lock、Unlock 和定向 Re-analyze 操作；
- 编辑仍通过现有 Review API 生成新 Revision，并保持实体 ID 不变；
- 不新增数据库、不改变 23-task 流程、不改变 SysML exchange 格式。

## User-facing structure

模型页保留当前需求追溯链，并增加五个可审查分区；Requirements 继续沿用现有独立工作台：

1. System Definition：System、Stakeholder、Concern、Lifecycle 和 Scenario；
2. Functional：Function、FunctionalFlow、FunctionalScenario；
3. Logical：LogicalComponent、Interface、State；
4. Physical：PhysicalBlock；
5. V&V：VerificationCase、ValidationCase、Hazard、FailureMode。

每个分区只显示当前 ModelGraph 中的实体，不生成页面侧的推断数据。实体卡片显示类型、名称、状态、来源/证据数量、关系数量和 payload；用户操作后刷新真实 revision 与状态。

## Data flow

```text
ModelGraph
  ↓
build_model_workbench_view()
  ↓
model.html 分层实体卡片
  ↓
现有 Review API
  ↓
ReviewService → Patch → ModelRepository.append_patch
  ↓
新 Revision / audit / downstream re-analysis
```

投影层只负责分组和显示数据。它不直接写 ModelGraph，也不复制 Review 状态机。前端编辑时提交完整 payload JSON 和可选名称，后端继续执行锁定保护、CAS revision 校验及用户 producer 标记。

## Error handling

- 无实体的层显示空状态，不显示虚构的候选对象；
- JSON payload 无法解析或不是对象时，在页面显示错误，不发起写操作；
- Revision 过期、锁定实体或非法状态转换沿用现有 HTTP 错误响应；
- 操作成功后重新读取页面，确保页面显示的是最新 ModelGraph，而不是客户端乐观状态。

## Acceptance

- 生成后的模型页同时出现 Functional、Logical、Physical、Verification、Validation 分区；
- 每个分区的实体来自真实 ModelGraph，数量与 API 一致；
- 编辑 Function 或 PhysicalBlock 后，实体 ID 保持不变、revision 增加、producer 变为 user、payload 保留用户修改标记；
- 接受/锁定和锁定后编辑失败均能通过现有 API 完成并可见；
- 页面不暴露 Patch/CAS/TaskSpec 等内部术语作为用户操作要求；
- 全量测试、架构检查和 import-linter 通过。
