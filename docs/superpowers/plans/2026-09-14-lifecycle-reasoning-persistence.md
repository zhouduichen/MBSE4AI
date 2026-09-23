# 23-task Logical/Physical 推理载荷接入计划

## 目标

让完整 23-task 生命周期与五阶段生成入口共享同一套 ModelGraph 推理事实。`logical_analysis` 必须在 LogicalComponent 中保存分区依据、候选架构和评价证据；`physical_candidates` 必须在 PhysicalBlock 中保存约束传播、测量缺口、冲突、可行性和回流选项。

## 范围与边界

- 复用现有 `synthesize_architecture`、`logical_reasoning_payload` 和 `physical_reasoning_payload`。
- 只在现有任务 Patch 中增加持久化 payload，不增加实体类型、表、状态机或新的模型调用。
- 通过共享的纯 Patch enrichment 在 `TaskGraphBuilder` 和 Structured LLM `WorkflowRunner` 提交前计算推理，再由原有 Workflow/CAS 提交。
- 不伪造 SWaP-C 测量、可行性结论或用户决策；未知值继续是 `needs_measurement`。
- 配置 StructuredModelRuntime 的 23-task LLM 路径不改变，新增字段由既有 schema/compiler/validator 边界管理。

## 实施步骤

### 1. Logical 推理

**文件：** `src/rflp_lite/methodology/architecture_persistence.py`、`src/rflp_lite/runtime/lifecycle_rule.py`

- 在 Logical 任务完成当前 Function→Logical allocation 后构造预览图。
- 对每个当前 LogicalComponent 生成 bounded `architecture_reasoning`，包含功能、功能流、依赖/共享状态/时序/安全依据及候选分区评价。
- 保持锁定或 `user_modified` 实体不可自动覆盖，保持既有 canonical ID。

### 2. Physical 推理

**文件：** `src/rflp_lite/methodology/architecture_persistence.py`、`src/rflp_lite/runtime/lifecycle_rule.py`

- 在 Physical candidate 任务完成 Logical→Physical allocation 后构造预览图。
- 对每个 PhysicalBlock 生成 `feasibility_reasoning`，复用当前约束作用域和 Architecture Synthesis 的状态、冲突、缺失测量字段与 resolution options。
- 保持源需求、约束 provenance、未知测量和 CAS 边界不变。

### 3. Structured LLM 路径

**文件：** `src/rflp_lite/methodology/workflow.py`

- 在结构化 LLM Patch 进入语义校验和 CAS 前复用同一 enrichment。
- 保留 LLM 已提供的非空推理字段，只补确定性缺失字段；不增加 23-task 调用次数。

### 4. 验收

**文件：** `tests/runtime/test_lifecycle_rule_runtime.py`、`tests/e2e/test_legacy_pipeline.py`

- 对完整 23-task 离线生命周期断言 Logical/Physical 载荷存在且引用 canonical IDs。
- 对结构化 LLM 23-task 生命周期断言同样的推理载荷被写入并进入交付包。
- 对显式功耗/续航约束断言 Physical reasoning 保留约束、状态为 `needs_measurement`，不产生虚假测量。
- 继续运行现有全量测试与静态质量门禁。

## 完成标准

- 完整 23-task 产物和五阶段产物在 Logical/Physical 推理字段上语义一致。
- 新增验收及全量检查通过。
- 提交已推送 GitHub，工作树干净。
