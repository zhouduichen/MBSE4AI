# 需求分析与总体概念设计验收收口设计

**日期：** 2026-09-01  
**范围：** 外协供应商功能点 1.1、1.2、2.1、2.2  
**明确不包含：** 3.1 自然语言 CAD、3.2 二维/三维 PMI 与 GD&T、3.3 DFM/DFA

## 1. 背景与结论

当前项目已经具备可执行的文档解析、需求结构化、MBSE 用例辅助、总体布局候选、多学科低阶评估和 Pareto 优化链路，但仍有两个验收问题：

1. 需求正式 gold 使用固定 `region-gold-*` 标识，实际导入使用内容相关 `region-*` 标识，导致功能检查通过而 precision/recall 为零；现有 gold 只列出两条期望需求，也不是完整语料标注，无法有效计算 precision。
2. 总体概念设计的软件链路可运行，但二维 SVG 的交付层级、候选差异证据和评估器正式批准依据还不够明确。仅凭配置中的布尔字段不能把低阶解析器升级为正式工程证据。

本次整改不扩大现有交互流程，也不宣称完成 CAD 或高保真 CAE。目标是让 1.x 形成可信的正式验收闭环，让 2.x 的概念级成果和 development-only 边界在数据、页面、导出和验收报告中保持一致，并为客户批准的外部 CFD、FEA 或 ROM 评估器留下稳定接口。

## 2. 设计原则

### 2.1 身份与证据分离

动态生成的来源区域 ID 是一次导入中的追溯证据，不是 gold 样本的跨运行身份。需求 gold 使用人工维护的稳定 `key` 和原文锚点配对；实际 `source_region_id` 只用于证明该输出确实能追溯到本次导入文档。

### 2.2 完整 gold 才计算 precision

正式验收 gold 必须声明 `corpus_mode: complete`，覆盖测试文档中全部预期需求。额外抽取项进入 precision 分母，漏抽项进入 recall 分母。部分样本只能用于 smoke 或回归定位，不得形成正式通过结论。

### 2.3 正式门槛只能更严，不能被配置削弱

代码继续保存最低门槛：需求 precision/recall 不低于 0.90、详情 micro-F1 不低于 0.85、来源完整率为 100%。gold 可以声明更高门槛，运行时取代码门槛与 gold 门槛的较大值。

### 2.4 概念成果不冒充详细设计

2.1 生成物统一标记为 `conceptual_2d_svg`，明确是参数化顶视/侧视总体布局草图，不是三维 CAD、工程图或制造模型。2.2 内置气动、结构、重量重心解析器继续标记 `development_only`。

### 2.5 正式评估依赖可验证证据

评估器只有在实现身份、适用域、验证数据集、误差指标和人工批准信息全部与当前执行一致时，才能生成 `formal` 证据。缺失、过期或不匹配均降级为 `development`，不能通过正式门禁。

## 3. 总体数据流

```text
Word / PDF
  → DocumentArtifact / DocumentRegion
  → StructuredRequirement / Attribute / Constraint
  → Gold v3 source-anchor pairing
  → Requirement precision / recall / detail F1 / provenance
  → Accepted requirements
  → Canonical flow
  → Use Case / Activity / Sequence
  → MBSE consistency / coverage / edit-CAS acceptance

IndicatorEnvelope
  → Historical scheme retrieval
  → 3–5 feasible and diverse candidates
  → LayoutArtifactManifest(conceptual_2d_svg)
  → DisciplineAdapter × Candidate
  → EvaluationApprovalEvidence validation
  → Development or formal evidence
  → Pareto optimization and trace export
```

## 4. 功能点 1.1：正式需求验收

### 4.1 Gold v3 契约

新增完整 gold 文件，结构如下：

```json
{
  "version": 3,
  "corpus_mode": "complete",
  "details_mode": "complete",
  "thresholds": {
    "requirement_precision": 0.9,
    "requirement_recall": 0.9,
    "detail_micro_f1": 0.85,
    "provenance_complete": 100
  },
  "requirements": [
    {
      "key": "REQ-1.1-DOCUMENT-IMPORT",
      "statement": "导入作战纲要、技战术指标文档（Word/PDF），利用NLP自动提取实体、属性及隐含约束",
      "accepted_statements": [],
      "source_anchor": "支持导入作战纲要、技战术指标文档（Word/PDF）",
      "details": []
    }
  ],
  "mbse_expectations": {
    "requirement_coverage": 1.0,
    "trace_complete": 1.0,
    "canonical_flow_consistent": true,
    "edit_cas_verified": true
  }
}
```

约束如下：

- `version` 必须为 `3`；旧 v1/v2 仍可读取，但只允许输出兼容诊断，不得正式通过。
- `corpus_mode` 必须为 `complete` 才计算正式状态。
- `details_mode` 必须为 `complete`；测试文档中出现的显式数值、范围、单位和禁止性约束必须在对应需求的 `details` 中标注。
- `key`、规范化后的 `source_anchor` 在文件内必须唯一。
- `statement` 是首选规范语句；`accepted_statements` 只用于记录经评审认可的等价表达，不能是空白或相互重复。
- `source_anchor` 必须能在测试文档的一个且仅一个来源区域中定位。
- `details` 可包含属性和显式约束；只要 gold 提供详情，就必须计算 detail micro-F1。

### 4.2 需求配对算法

配对按以下确定性步骤执行：

1. 将实际需求的 `source_region_id` 解析为本次导入的来源文本；不存在的 ID 记为 provenance 失败。
2. 对空白、全半角标点和句末标点做规范化，不改写专业词、数值、单位和逻辑运算符。
3. 用 `source_anchor` 在实际来源文本中做唯一包含匹配；零个或多个区域匹配均不建立配对，并写入诊断。
4. 在同一来源中，对实际 statement 与 gold 的 `statement + accepted_statements` 做一对一匹配。规范化后完全相等直接通过；包含关系只有在较短文本长度达到较长文本的 80% 时才通过。
5. 多个候选同时满足时，按文本相似度、gold key、实际稳定 ID 排序并执行一对一分配。未分配实际项计为误报，未分配 gold 项计为漏报。

来源相同但需求内容错误不能通过；来源 ID 改变但来源文本和需求内容相同仍能通过。

### 4.3 详情和来源指标

需求匹配成功后再比较属性和约束。详情身份由以下规范化元组构成：

```text
attribute:  (requirement_key, name, value, unit, minimum, maximum)
constraint: (requirement_key, constraint_type, expression, explicitness)
```

属性和约束分别统计 TP、FP、FN，汇总为 micro precision/recall/F1。所有实际需求、属性和约束必须引用存在的来源区域，来源完整率必须为 100%。

### 4.4 验收报告

报告保留现有 `status`、`smoke_status`、`formal_status` 字段，并增加：

- `gold_contract_status`：`valid`、`legacy_only` 或 `invalid`；
- `effective_thresholds`：代码最低门槛与 gold 门槛合并后的结果；
- `requirement_matches`：gold key、实际 ID、来源区域 ID、匹配方式和分数；
- `detail_metrics`：属性与约束的 micro 指标；
- `provenance_diagnostics`：缺失、未知或歧义来源；
- `formal_failures`：逐项列出未达到的门槛。

顶层 `formal_status` 只有在 gold 契约有效、需求指标达标、详情指标达标、来源完整且第 5 节 MBSE 指标全部达标时才为 `passed`；任一子门禁失败都必须保留自己的失败原因。

## 5. 功能点 1.2：MBSE 用例辅助验收

### 5.1 Canonical flow 身份

每个 Use Case、Activity 和 Sequence Message 保存 `canonical_flow_id` 与 `canonical_flow_hash`。三个投影必须来自同一个已审核场景流；渲染器继续只读取保存的语义对象，不触发新的 LLM 调用。

### 5.2 正式指标

新增 `evaluate_mbse_acceptance()`，计算：

- `requirement_coverage`：已接受需求中，被 Use Case、Activity 和 Sequence 任一投影追溯覆盖的比例；
- `cross_view_consistency`：三个投影引用同一 canonical flow 的比例；
- `trace_complete`：MBSE 对象引用已知需求且 trace link 端点均存在的比例；
- `projection_complete`：已审核场景是否同时具有 Use Case、Activity 和 Sequence 投影；
- `edit_cas_verified`：结构化编辑、旧 revision 冲突和定向失效是否均按契约工作。

正式样例要求上述覆盖与完整性均为 100%。

### 5.3 编辑验收

验收脚本在内存副本上选择一条消息执行 `update-fields`：

1. 使用当前 revision 修改消息名称或 guard；
2. 验证 revision 发生变化、目标及关联投影被标记为 stale；
3. 验证无关模型不被标记为 stale；
4. 使用旧 revision 再次提交，必须得到 revision conflict；
5. 不保存这次验收编辑，不污染客户工作台。

## 6. 功能点 2.1：总体布局证据完善

### 6.1 LayoutArtifactManifest

为每个候选生成独立清单，不改变现有 `LayoutCandidate` 的兼容字段：

```text
candidate_id
representation_kind = conceptual_2d_svg
views = [top, side]
unit_system
reference_scheme_ids
similarity_matches
parameter_differences
hard_constraint_margins
minimum_pairwise_distance
generator_id / generator_version / seed
input_hash / svg_hash / manifest_hash
```

清单进入 JSON 导出、API 和现有概念设计页面。页面固定显示“参数化二维概念布局，不是三维 CAD”提示。

### 6.2 候选差异和追溯

现有 `candidate_distance()` 和领域包 `generation.minimum_distance` 成为正式验收项。任意两个候选距离低于门槛即失败。每个候选必须至少引用一个历史方案或明确记录无参考方案诊断；相似检索的特征差异、缺失特征和数据来源必须随候选导出。

### 6.3 2.1 验收门禁

- 候选数量在领域包声明的 3～5 范围内；
- 所有 hard constraint 通过；
- 任意候选对满足最小差异；
- 相同输入和 seed 的候选及 SVG 哈希相同；
- 每个候选具有完整 LayoutArtifactManifest 和来源追溯；
- representation kind 必须为 `conceptual_2d_svg`。

## 7. 功能点 2.2：多学科评估治理

### 7.1 保留现有端口

继续使用 `DisciplineAdapter.evaluate(candidate, profile) -> DisciplineEvaluation`。本轮不添加未经客户选择的 CFD/FEA 产品适配器，也不允许执行任意命令或脚本。后续真实求解器通过相同端口注册。

### 7.2 评估器批准证据

批准档案从简单布尔值扩展为以下必填证据：

```text
adapter_id
adapter_version
implementation_hash
source_kind
validity_domain
validation_dataset_id
validation_dataset_version
validation_dataset_hash
error_metrics
acceptance_limits
approved_for_formal
approved_by
approved_at
basis
```

`error_metrics` 与 `acceptance_limits` 必须具有同名数值指标，并满足声明方向；适用域必须覆盖当前候选输入。`implementation_hash` 必须与运行时注册适配器的声明哈希一致。

### 7.3 证据状态

单学科评估仅在以下条件全部成立时标记 `formal`：

- 执行状态为 succeeded 或可信缓存命中；
- adapter ID、版本和实现哈希与批准档案一致；
- 当前输入位于批准适用域；
- 验证数据集身份和哈希非空；
- 所有误差指标满足批准限制；
- 批准人、批准时间和依据非空；
- `approved_for_formal` 为 true。

否则保持 `development`，并输出明确的降级原因。一个候选的三个学科全部为 formal 才能获得 formal candidate status；全部 Pareto 输入候选都满足后，优化运行才能正式通过。

### 7.4 局部失败和缓存

继续以 `Candidate × Discipline` 为隔离单位。一个评估器失败、超时、越出适用域或批准过期，不影响其他学科完成。缓存键增加 adapter implementation hash、批准档案 hash 和 validity-domain hash，避免旧结果在实现或批准状态变化后被误用。

## 8. 页面、API 与兼容性

现有导航和 POST/303 交互保持不变，只增加信息：

- 需求验收页面/API 展示 gold 版本、正式失败原因、需求和详情指标；
- MBSE 页面展示 canonical flow 一致性和 trace 覆盖；
- 概念设计页面/API 展示表示类型、方案差异、约束裕度和评估证据状态；
- 原有 JSON 字段保留，新字段均为增量字段；
- v1/v2 gold 可读取并产生诊断，但 `formal_status` 固定为 `not_evaluated` 或 `failed`，不会误报通过；
- 内置评估器的现有 development profile 继续有效，正式状态仍为 `development_only`。

## 9. 错误处理与审计

- Gold 缺字段、重复 key、重复 source anchor 或非完整语料时，正式验收失败并报告契约错误，smoke 检查仍可运行。
- 来源锚点无法定位或定位到多个区域时不猜测匹配。
- MBSE 引用未知需求、未知 flow 或过期 revision 时拒绝正式通过。
- Layout manifest 与 SVG、候选参数或生成器哈希不一致时拒绝导出为已验证成果。
- 评估器批准不匹配时降级证据，不中断其他学科。
- Gold、领域包、评估器档案、验证数据集、输入和输出的版本与哈希进入报告和审计事件。

## 10. 测试与验收

### 10.1 单元测试

- 来源 ID 改变但来源锚点和需求内容一致时匹配；
- 同一来源中的错误需求内容不匹配；
- 多抽和漏抽分别降低 precision 与 recall；
- 属性/约束详情 micro-F1 正确；
- MBSE 三视图 flow identity 和定向失效正确；
- Layout manifest 哈希、约束裕度和候选差异正确；
- 批准档案的版本、哈希、适用域、误差和人工批准字段逐项门禁。

### 10.2 契约与集成测试

- Gold v3 严格 schema；
- DOCX 表格和 PDF/OCR 来源锚点可重复定位；
- 现有 Web/API/CLI 返回字段兼容；
- concept run 的缓存、失败隔离和 Pareto 追溯保持有效；
- 内置评估器不能通过 formal gate；注入完整批准证据的测试适配器可以通过。

### 10.3 可执行验收

1. `rflp acceptance --gold <gold-v3.json>` 必须在完整样例上正式通过；修改需求、删除需求或添加错误需求后必须失败。
2. MBSE 验收必须证明 coverage、cross-view consistency、trace、edit CAS 和 targeted stale。
3. `rflp concept acceptance` 必须继续通过软件检查，内置 profile 返回 `development_only`。
4. 只有使用测试中具备完整批准证据的确定性适配器时，2.2 formal status 才能为 passed。
5. 全量 pytest、compileall、Import Linter 和 schema 检查全部通过。

## 11. 交付边界

本次完成后可宣称：

- 1.1、1.2 具备可复现、可解释、不会因动态来源 ID 误判的正式验收闭环；
- 2.1 具备有约束、有差异、有来源证据的参数化二维概念布局候选；
- 2.2 具备多学科批量评估、优化反馈和严格正式证据门禁。

仍不可宣称：

- 已完成三维总体 CAD 布局；
- 内置低阶模型等同正式 CFD、FEA 或客户批准 ROM；
- 已实现 3.1、3.2、3.3。
