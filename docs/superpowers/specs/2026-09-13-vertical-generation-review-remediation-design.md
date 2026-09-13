# 纵向模型生成评审修正设计

## 目标

修正 `ModelGenerationService` 的语义验收和追溯口径，并让五阶段产品入口保留完整的 MBSE operational reasoning 与架构决策信息。

修正后的主链路仍为：

```text
自然语言 / 文档 → Requirements → Functional → Logical → Physical → V&V
               → ModelGraph → SysML v2 subset
```

其中五个阶段是用户体验抽象；每个阶段携带内部方法论步骤和结构化决策记录，不把 Operational Analysis 简化成三个实体，也不把 Logical/Physical 简化成一对一映射。

## 1. 语义失败的处理

`schema`、`identity`、`reference`、`patch_policy` 失败仍然拒绝 Patch，不写入 ModelGraph。

`semantic_invalid` 是可修复的模型质量问题：

1. 使用不包含 `semantic` 的验证器集合，重新确认其余结构、引用和写权限均通过；
2. 以 `EntityStatus.CANDIDATE` 保存 Patch 中的 LLM 新实体，绝不提升为 `VALIDATED`；
3. 阶段状态为 `needs_review`，写入 `semantic_invalid` Issue 和可读诊断；
4. 允许后续阶段继续生成，但候选实体不能进入完成追溯统计；
5. 语义通过的 LLM 实体才提升为 `VALIDATED`。

这样既保留了可编辑的中间结果，也不会把语义失败计入产品成功率。

## 2. 追溯指标

`TraceabilitySummary` 同时提供以下指标：

- `rflp_complete_count` / `rflp_partial_count` / `rflp_missing_count`：Requirement → Function → Logical → Physical；
- `verification_complete_count`：RFLP 路径存在且有有效 `verifiedBy`；
- `validation_complete_count`：RFLP 路径存在且有有效 `validatedBy`；
- `end_to_end_complete_count`：RFLP、Verification、Validation 三者同时存在；
- 对旧 API 保留 `complete_count`、`partial_count`、`missing_count`，但它们映射到端到端口径。

候选、拒绝和废弃的下游对象不计入相应链段；用户输入的 Requirement 可以作为根节点，但语义失败的 LLM 输出不可以作为有效链段。`paths` 输出同时包含 verification 和 validation 两个末端，缺失项通过路径长度和分项计数表达。

## 3. 五阶段与内部方法论步骤

每个 `VerticalStageSpec` 增加只读 `reasoning_tasks`，映射现有 23-task 方法论到产品阶段：

- Requirements：system definition、stakeholder、lifecycle、scenario、use case、operational scenario、activity、requirement derivation；
- Functional：function identification、decomposition、interaction、functional scenario、functional requirement；
- Logical：logical analysis、interface/sequence/state、dependency clustering、architecture evaluation；
- Physical：physical candidates、allocation tradeoff、technical requirement、constraint propagation、feasibility selection；
- V&V：FMEA/STPA、verification/validation、reverse feasibility、global cross analysis。

Requirements 阶段的最低存在集合扩展为 `SYSTEM`、`STAKEHOLDER`、`LIFECYCLE_STAGE`、`SCENARIO_HYPOTHESIS`、`USE_CASE`、`OPERATIONAL_SCENARIO`、`ACTIVITY` 和 `REQUIREMENT`。阶段输出缺少这些 operational 类型时，阶段仍可保留候选结果，但必须是 `needs_review`，不能伪装成完整 Requirements 阶段。

LLM 的 Proposal 增加 bounded `decision_records`，每条只记录“步骤、结论、依据引用”，不要求或保存隐藏思维链。Logical 输出至少支持依赖、共享状态、时序、隔离、内聚/耦合和分区依据；Physical 输出至少支持质量、功耗、算力、内存、时延、带宽、成本、热、可靠性、可用性、SWaP-C、约束、可行性和候选选择理由。

## 4. 结果和编辑语义

阶段结果返回 `status`、分项计数、`decision_records`、assumptions、open questions 和 diagnostics。整体状态规则为：

- 所有阶段无语义问题、存在端到端完整路径：`completed`；
- 有候选、缺失 operational 类型、语义 Issue 或部分追溯：`completed_with_warnings`；
- 结构、引用、策略、编译或运行失败：`failed`。

候选仍可通过现有 ModelGraph 编辑和 Review/Edit/Lock 入口处理；接受后重新计算追溯，不修改历史运行结果。

## 5. 验收

新增测试必须证明：

1. semantic_invalid 不再产生 VALIDATED LLM 实体，并写入 Issue；
2. 结构化 LLM 五阶段调用仍然完整；
3. Requirements 阶段覆盖 operational 最低集合；
4. 只存在 Verification 或只存在 Validation 时，端到端计数为 0；
5. SysML 往返和人工编辑回归不受影响；
6. 全量测试、compileall、架构预算和 import-linter 通过。
