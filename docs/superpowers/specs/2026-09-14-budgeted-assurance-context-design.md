# Budgeted Assurance Trace Context Design

**状态：** 已确认，进入实施

## 背景

五阶段纵向生成已经把 Requirements、Functional、Logical、Physical 和 V&V
写入同一份 ModelGraph。Assurance 阶段为了保证作用域一致，目前直接把所有相关实体和关系放入
`ContextBundle`，没有使用当前 Runtime 的上下文预算。小输入可以完成，需求、文档证据或架构变体
增多后则可能超过远程模型的上下文窗口，导致 V&V 阶段无法可靠地产生结构化结果，进而破坏完整
`R→F→L→P→V&V` 链。

## 目标与边界

本次改动只解决 Assurance 输入选择问题：

1. V&V 上下文必须服从 `ContextBuilder` 已计算出的可用上下文预算。
2. 在预算内优先保留每条活动 Requirement 的完整下游作用域：Requirement、Function、
   LogicalComponent、PhysicalBlock，以及作用域匹配的 VerificationCase/ValidationCase。
3. 在仍有预算时加入 Activity、FunctionalScenario、Hazard、FailureMode 和相关 Evidence
   端点，帮助 LLM 生成可执行的验证、确认和风险覆盖。
4. 选择顺序、截断结果和关系集合必须确定性；关系不能引用未选中的实体。
5. 预算不足时不能静默声称完整：在 `methodology_guidance` 中保留已选/省略的 canonical ID，
   让模型只补可证明的内容，未覆盖项继续进入 Review/Methodology findings。

不改变 EntityKind、TaskSpec、PatchPolicy、Run 状态、V&V 九字段契约，也不把多个 Requirement
拆成额外的 LLM 调用。SysML、ModelGraph 和交付物格式保持不变。

## 设计

`ContextBuilder.build()` 继续统一计算：

```text
total Runtime context window
  - output reserve
  - prompt reserve
  = available entity/relation context budget
```

当任务为 `verification_validation` 或 `global_cross_analysis` 时，调用预算化的
`_assurance_trace_context(graph, planner, token_budget)`，不再直接返回整张图。

选择算法固定为以下顺序：

1. 选取所有 active Requirement，按 canonical ID 排序；使用
   `requirement_trace_scope` 取得每条需求的 Function、LogicalComponent 和 PhysicalBlock
   作用域，并优先选取该作用域内的 ready 实体。
2. 为每条需求选取作用域匹配的 VerificationCase 和 ValidationCase；已有多个用例时按
   canonical ID 排序，直到预算允许。每条需求的 ID 和作用域摘要始终进入 guidance。
3. 在剩余预算内优先加入与已选作用域相连的 Activity、FunctionalScenario、Hazard、FailureMode
   和 Evidence；预算仍有余量时再加入其他同类支撑实体，避免小图因缺少显式引用而丢失运行语境。
   同一层内按“相连优先、kind、ID”排序。
4. 只保留两端都已选中的关系，并按关系 ID 排序。

每次加入实体都用现有 `TokenEstimator` 估算完整实体 payload；超出预算的实体跳过而不是截断
JSON。`PlannedContext.token_estimate` 不得超过传入预算。`PlannedContext.layers` 增加稳定的
`ASSURANCE_TRACE` 和预算截断记录，用于诊断但不写入 ModelGraph。

如果预算小到无法保留完整作用域，至少保留所有 Requirement 和可放入的 canonical 下游 ID
摘要；`methodology_guidance.context_selection` 明确列出 `selected_entity_ids`、
`omitted_entity_ids` 和 `omitted_requirement_ids`。Structured Runtime 收到该 guidance
后不得把省略实体当作已验证事实。正常的 `needs_review`、Controller 和定向重分析流程继续
处理缺口。

## 数据流

```text
Runtime Profile context_window
        ↓
ContextBuilder available budget
        ↓
budgeted assurance trace selection
        ↓
ContextBundle entities / relations + selection guidance
        ↓
StructuredModelRuntime
        ↓
TaskProposal → Compiler → Validator → CAS
```

该选择器是纯函数式 ModelGraph 读取逻辑，不调用模型、不写仓库、不改变当前 revision。

## 验收标准

- Assurance 上下文在受限窗口下的估算值不超过可用预算。
- 多需求模型中每条需求优先保留其 RFLP 作用域和已有匹配 V&V 用例；不产生跨需求关系。
- 预算不足时省略 ID 可解释、可复现，并在 guidance 中可见；不把省略内容统计为完成。
- 小图的现有 V&V 结构化生成、SysML 往返、Controller 和离线 Runtime 行为不回归。
- 全量测试、架构指标、Import Linter 和 `git diff --check` 通过。

## 测试策略

- ContextBuilder 单元测试：验证预算、优先级、active 过滤、关系端点闭合和截断 guidance。
- Application/E2E 测试：用多个需求和受限 Profile context window 运行结构化五阶段链，检查每次
  Assurance 请求的估算和每条需求的作用域摘要。
- 回归测试：运行现有全量离线质量门禁；不启动本机或远程模型。
