# 离线需求隐含约束候选设计

## 背景

1.1 的结构化 LLM 契约已经支持 `llm_inferred` 约束、假设、置信度和来源引用。但默认离线入口的 fallback 只提取带数字和单位的显式约束；“支持人工接管”“故障后安全运行”“持续运行”等语义被保留在 statement 中，却没有进入可追溯的 MBSE 约束候选。

这会让没有模型时的产品链和配置模型时的产品链产生不同的需求语义，也无法在离线验收中证明隐含约束被识别。本切片补充透明的确定性语义推断，不替代远程 LLM，也不自动批准工程约束。

## 目标

1. 从有限、可审计的安全语义词表中生成结构化 `derived` 约束候选。
2. 每条候选保留 `field`、`operator`、数值化标记、单位、低置信度、假设和来源区域。
3. 显式数值约束继续优先；规则推断不得覆盖显式约束。
4. 候选进入现有 `inferred_constraints` 和需求审查路径，保留 `requires_human_review`。
5. 需求草稿页面明确显示发现了隐含约束以及“需人工确认”的状态。
6. 主 R→F→L→P→V&V 链能够读取这些结构化约束，并继续保留未知约束的 `needs_measurement`/审查语义。

## 非目标

- 不启动本地或远程模型，不增加 Provider、状态机或新的数据库。
- 不声称离线规则等同于 NLP/LLM 的开放域推理。
- 不把安全、可靠性或持续运行语义自动提升为批准需求或正式验证通过。
- 不推断任意数值，例如不从“实时”擅自猜测 100 ms。

## 方案

### 方案 A：有限语义规则 → `derived` 候选（采用）

在现有文本约束模块增加版本化规则表。每条规则只在明确短语出现时触发，并产生布尔型数值约束（`value=1`, `unit=boolean`, `operator=eq`），同时记录假设和低置信度。规则输出与显式抽取进入同一个 merge 函数，显式约束优先。

首批规则：

| 语义短语 | canonical field | 推断含义 |
|---|---|---|
| 人工接管/人工干预/手动接管 | `human_override` | 系统需要提供人工接管路径 |
| 故障安全/失效安全/故障后安全 | `fail_safe_behavior` | 故障状态需要进入安全处置路径 |
| 容错/冗余/故障隔离 | `fault_tolerance` | 需要显式容错或隔离机制 |
| 持续运行/连续运行/全天候 | `continuous_operation` | 运行场景包含连续运行约束 |
| 可追溯/留痕/审计 | `audit_trail` | 需要保留可审计记录 |

这些候选来源为 `derived`，不是 `llm_inferred`；这样输出准确表达“由本地规则推导”的事实。远程 LLM 输出继续使用它自己的 `llm_inferred` 标记。

### 方案 B：把每个语义映射成硬编码实体字段

实现简单，但会绕过已有 constraint schema，后续 F/L/P 无法统一消费，也不能保存假设和来源。不采用。

### 方案 C：无模型时调用外部分类器

会引入新的运行依赖、模型来源和部署不确定性，偏离当前离线产品路径。不采用。

## 数据流与门禁

```text
原始文本/文档区域
  → 显式数值约束 + 有限语义规则
  → constraints[] (explicit / derived)
  → explicit-wins merge
  → Requirement.payload.constraints / inferred_constraints
  → RFLP 约束传播与 Methodology findings
  → 人工 Review / V&V 计划
```

规则输出带 `source_refs`；没有文档区域时为空，但仍保留原始 statement 和假设。需求、实体和约束仍以 `CANDIDATE`/`requires_human_review=true` 进入 ModelGraph。`derived` 约束不能批量自动批准。

## 验收

- “系统应支持人工接管并在故障后安全运行”产生至少两个 `derived` 约束，均有假设和低置信度。
- 含显式功耗/时延等数值和隐含语义的句子同时保留两类约束，显式值不被覆盖。
- 应用草稿后 Requirement 保存 `inferred_constraints`，RFLP/物理可行性分析仍能读取并对未知字段保持待测量或审查状态。
- Web 需求草稿页面显示隐含约束数量和需人工确认提示。
- 既有结构化 LLM、文档来源、行为模型、RFLP、SysML 和全量离线验证保持通过。
