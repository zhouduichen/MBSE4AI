# LLM 纵向阶段反馈闭环设计

**日期：** 2026-09-14  
**状态：** 执行中  
**范围：** 五阶段 ModelGenerationService 的结构化 LLM 生成路径

## 背景

当前五阶段入口可以把一次输入送入 Requirements、Functional、Logical、Physical 和 V&V，但每个阶段只调用一次 Runtime。阶段完成检查得到的 completion_issue_codes 只会进入下一阶段的 methodology_guidance；如果 LLM 在 Functional 阶段漏掉一条需求的功能分配，系统会继续调用 Logical/Physical，直到最终交付包才暴露缺口。

这使方法论检查更像事后验收，而不是当前阶段的工程反馈回路。目标是让结构化 LLM 在同一阶段看到确定性检查结果后有一次修正机会，优先闭合真实 R→F→L→P→V&V 纵向链。

## 目标与非目标

目标：

1. 每个纵向阶段支持“首次生成 → 写入并检查 → 有缺口时同阶段反馈再生成”的最多两次尝试。
2. 第二次调用读取首次 Patch 写入后的最新 ModelGraph，以及 Methodology Engine 重新计算的阶段检查和推荐动作。
3. 保持 canonical entity ID、CAS Revision、锁定/人工修改保护、结构化 Compiler/Validator 和审计台账不变。
4. 阶段缺口仍未解决时明确返回 needs_review 和原有 issue codes，不把重试成功率当成完成度。
5. 离线 RuleRuntime 不因该功能增加无意义的重复执行；只有结构化生成路径执行反馈回合。

非目标：

- 不调用或启动本机模型，也不做真实 Provider 稳定性实验。
- 不引入新的实体类型、持久化表或第二份模型真源。
- 不自动选择 Trade Study 方案，不覆盖 LOCKED 或 user_modified 实体。
- 不把所有 Methodology warning 都变成重试条件；仅当前阶段缺失类型、阶段语义检查失败或结构化语义无效触发反馈。

## 设计

### 阶段执行器

ModelGenerationService._execute_stage 以 max_attempts=2 包住现有单次执行逻辑：

    attempt 1
      build context from current graph
      StructuredModelRuntime → Compiler → Validator → CAS Patch
      reload graph → missing kinds + evaluate_vertical_stage
           │
           ├─ no stage issue → finish stage
           └─ issue → attempt 2
                 build context from patched graph
                 methodology_guidance contains current issue codes
                 StructuredModelRuntime → Compiler → Validator → CAS Patch
                 reload graph → final StageResult

第二次尝试仍通过同一 TaskExecutor 和同一 TaskSpec，不绕过结构化输出、引用校验、PatchPolicy 或 CAS。第二次上下文由最新图构建，因此 LLM 可以通过 updates 复用现有 ID，或只补缺失对象。上下文中的 methodology_guidance.stage_completion 是确定性反馈来源，不把自由文本诊断直接当成事实。

### Runtime 判定

反馈回合只对结构化生成 Runtime 开启。运行时选择由组合根已有的 RuntimeSelection.mode 表示：configured 或显式注入的结构化测试 Runtime 允许反馈；offline 的 RuleRuntime 保持单次、可复现行为。此切分不依赖 Provider 名称，不会触发本地模型探测。

### 台账与结果

每次尝试更新同一个阶段 Step 的 attempt，最终 Step 保留最后一次的 input/output/context hash；每次实际 CAS Patch 仍保留独立 Patch 和 Revision。StageResult 增加 attempts，审计事件记录最终状态和尝试次数。若首次已写入候选但第二次仍失败，候选和 Issue 保留在图中，阶段状态为 needs_review，后续结果按既有规则提供但最终交付包必须带出缺口。

### 失败边界

- Runtime/Transport/Compiler 等已有失败分类仍沿用当前失败路径；TaskExecutor 自身的结构化重试不与阶段反馈次数混淆。
- semantic_invalid 仍按当前逻辑以 candidate 写入并登记 Issue，然后允许一次同阶段反馈；第二次仍无效则不升级为 validated。
- 反馈回合不能修复锁定或人工修改对象；如果缺口由这些对象造成，结果保留 needs_review 并交给 Controller/用户。

## 测试验收

新增确定性结构化 Runtime fixture：第一次 Functional proposal 缺失 functional_behavior_ids，第二次依据最新上下文写入该字段。验收要求：

- 两次调用使用同一 stage task，第二次上下文 Revision 大于第一次；
- 同一 Function/Requirement 保持 canonical ID，没有重复 active entity；
- 最终 Functional completion 通过，后续 Logical/Physical/V&V 仍各调用一次；
- 失败 fixture 两次都不完整时，StageResult 为 needs_review，并保留 completion issue code；
- RuleRuntime 离线生成仍保持每阶段一次调用和原有完整追溯；
- 全量测试、compileall、Ruff、架构指标、import-linter 和 diff check 通过。

