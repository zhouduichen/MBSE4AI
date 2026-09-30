# M1/M2 需求捕获与用例建模纵向切片设计

**日期：** 2026-09-17  
**范围：** 功能点 1.1、1.2  
**前置能力：** 现有文档导入、证据存储、ModelGraph、远程 OpenAI-compatible LLM、RFLP/V&V 生成链

## 1. 背景与目标

当前系统已经能够把自然语言或文档片段送入 R→F→L→P→V&V 主链，并保存结构化 ModelGraph、追溯关系和 SysML 子集。但需求输入仍主要是“按句切分 + 有限正则约束提取”，用例、运行场景和活动虽然存在于元模型，却没有一个面向需求分析的专用提取与交互闭环。

本阶段交付一条可以被用户实际操作和验收的业务纵向切片：

```text
Word/PDF/Markdown/TXT
  → 文档来源区域与证据
  → LLM 需求语义抽取
  → 实体、属性、显式/隐含约束候选
  → MBSE 需求与初始追溯关系
  → 用例/运行场景/活动框架
  → 人工接受、编辑、驳回
  → 可继续进入现有 RFLP 与 SysML 子集导出
```

目标不是新增一个自由聊天机器人，而是让每一项机器提议都落到现有的有类型、有来源、有状态、可修订 ModelGraph 中。

## 2. 本阶段验收边界

### 2.1 必须完成

1. 导入现有支持的 Word/PDF/Markdown/TXT 后，按文档区域保留来源、页码/定位和证据引用。
2. 对选定文档或文本运行一次“需求与用例提取”，输出结构化中间结果：
   - 系统、利益相关方、任务/场景、资源/对象等实体候选；
   - 每个实体的名称、类型、别名或属性；
   - 需求 statement、层级、义务词、需求类型、验证方法；
   - 显式数值约束和 LLM 推断的隐含约束，区分来源、置信度、原文证据和假设；
   - 需求与实体、场景之间的初始追溯关系；
   - Use Case、Operational Scenario、Activity 及其顺序/分支框架。
3. 提取结果以候选状态写入 ModelGraph，使用现有 Patch/Repository 机制，重复运行不产生重复活动实体或关系。
4. Web 页面展示抽取批次、原文证据、来源类型、置信度、假设和待澄清项；用户可以接受、编辑或驳回候选。
5. 用户接受或编辑后，现有需求台账、场景/行为视图、追溯矩阵和 RFLP 生成入口能读取这些对象。
6. 对一次固定中文验收文档，在远程 vLLM 可用时产生至少 3 条需求、1 个 Use Case、1 个 Operational Scenario、1 个 Activity，且每个候选均能追溯到文档区域或明确标为推断。

### 2.2 明确不在本阶段完成

- 总体布局草图生成、历史方案库检索和多学科仿真/优化（2.1、2.2）。
- 商业 CAD 驱动、三维几何内核、二维工程图、PMI/GD&T、尺寸避让（3.1、3.2）。
- DFM/DFA 规则执行和 CAD 风险高亮（3.3）。
- OCR 基础模型、商业仿真器、商业 CAD 内核或新的微服务基础设施。
- 以测试数量、重复运行次数或 LLM 原始文本长度作为本阶段交付指标。

## 3. 方案选择

### 方案 A：仅扩大现有 `RequirementInputService` 的正则规则

实现成本最低，但只能处理少量显式指标，无法可靠识别实体、隐含约束、场景和活动顺序，无法满足 1.1/1.2。

### 方案 B：LLM 直接写 ModelGraph

表面上代码最少，但会绕过中间契约和确定性校验，容易生成重复实体、无来源关系和非法字段，也难以支持局部重跑和人机编辑。

### 方案 C：LLM 结构化提取 + 确定性归一化/编译（采用）

LLM 只产生版本化的 `IntakeDraft`，负责语义候选、隐含约束和行为框架；确定性编译器负责 schema 校验、单位归一化、ID 稳定、显式值覆盖、关系合法性、证据绑定和幂等写入。它最大程度复用当前 ModelGraph 和远程模型适配器，同时让后续布局和 CAD 阶段可以消费同一条追溯链。

## 4. 数据契约

### 4.1 `IntakeDraft`

新增一个应用层 DTO，不能直接等同于 `ModelGraph`：

```json
{
  "schema_version": "requirements-use-case-draft.v1",
  "source_document_ids": ["doc-..."],
  "system_context": {"name": "...", "mission": "..."},
  "entities": [
    {
      "local_ref": "actor_operator",
      "kind": "stakeholder",
      "name": "操作员",
      "attributes": {"role": "..."},
      "source_refs": ["region-..."],
      "confidence": 0.91
    }
  ],
  "requirements": [
    {
      "local_ref": "req_response_time",
      "statement": "系统应在 2 秒内完成告警响应",
      "level": "system",
      "type": "performance",
      "obligation": "系统应",
      "verification_method": "test",
      "constraints": [
        {
          "field": "latency_ms",
          "operator": "max",
          "value": 2000,
          "unit": "ms",
          "source": "explicit",
          "source_refs": ["region-..."]
        },
        {
          "field": "availability",
          "operator": "min",
          "value": 0.99,
          "unit": "ratio",
          "source": "llm_inferred",
          "confidence": 0.52,
          "assumption": "连续运行任务要求高可用"
        }
      ],
      "source_refs": ["region-..."],
      "confidence": 0.87
    }
  ],
  "use_cases": [
    {
      "local_ref": "uc_monitor",
      "name": "执行区域监视",
      "goal": "...",
      "primary_actor_refs": ["actor_operator"],
      "preconditions": ["..."],
      "postconditions": ["..."],
      "scenario_refs": ["scenario_monitor"],
      "source_refs": ["region-..."]
    }
  ],
  "scenarios": [
    {
      "local_ref": "scenario_monitor",
      "kind": "operational_scenario",
      "name": "发现目标并上报",
      "steps": [
        {"order": 1, "actor_ref": "actor_operator", "action": "下达监视任务"},
        {"order": 2, "actor_ref": "system", "action": "采集并处理数据"}
      ],
      "branches": [{"condition": "数据不可用", "target_step": 1, "action": "报告异常"}],
      "source_refs": ["region-..."]
    }
  ],
  "clarifications": [
    {"question": "响应时间是平均值还是最大值？", "related_refs": ["req_response_time"], "severity": "medium"}
  ],
  "diagnostics": []
}
```

字段规则：

- `source_refs` 必须引用已保存的文档区域或输入证据；没有原文依据的内容只能标记为 `llm_inferred`，并保留假设和置信度。
- `explicit` 由现有确定性解析器从原文约束中得到，优先级高于 `derived`、`llm_inferred` 和默认值；LLM 不得覆盖显式数值。
- `attributes` 允许领域无关 JSON 标量/数组，但编译为模型属性前必须经过长度、类型和敏感字段白名单检查。
- `local_ref` 只在一个 draft 内解析，不作为持久化 ID；持久化 ID 由实体类型、规范化名称、来源和项目生成。
- LLM 输出未知 `kind`、关系或约束字段时进入 `diagnostics`，不静默写入图。

### 4.2 ModelGraph 映射

复用当前实体类型：`SYSTEM`、`STAKEHOLDER`、`CONCERN`、`SCENARIO_HYPOTHESIS`、`USE_CASE`、`OPERATIONAL_SCENARIO`、`ACTIVITY`、`REQUIREMENT`。本阶段不新增平行的场景数据库。

建议 payload 最小字段：

- 需求：`statement`、`level`、`type`、`obligation`、`verification_method`、`constraints`、`constraint_provenance`、`inferred_constraints`、`requires_human_review`。
- 用例：`goal`、`primary_actor_ids`、`preconditions`、`postconditions`、`scenario_ids`、`requires_human_review`。
- 运行场景：`steps`、`branches`、`diagram_kind: "activity_sequence"`、`requires_human_review`。
- 活动：`order`、`actor_id`、`action`、`guard`、`next_activity_ids`、`scenario_id`。

关系使用现有 `DERIVED_FROM`、`DECOMPOSES`、`PARTICIPATES_IN`、`OCCURS_IN`、`REFINES`、`DESCRIBED_BY`、`SATISFIED_BY` 等谓词。若某条关系不能通过当前端点规则验证，编译器记录诊断并跳过该关系，不改变其他合法候选的写入。

### 4.3 状态与修订

- LLM 新产出全部是 `CANDIDATE`，producer 为 `LLM`；确定性约束和单位补全可以写入同一候选的 payload，但不擅自升为 `ACCEPTED`。
- 人工接受/编辑/驳回沿用现有 review patch，不新增第二套审批状态机。
- 一个 draft 对应一个可审计的 patch；重复提交相同文档、同一模型 profile 和同一输入 revision 时，使用 draft hash 保证幂等。
- 新文档修订只补充来源关系，不覆盖用户已经编辑或锁定的实体；冲突显示为待复核项。

## 5. 服务与执行流程

新增 `RequirementsUseCaseService`（名称可在实现阶段按现有命名微调），提供：

1. `create_draft(project_id, text=None, document_ids=(), profile_id=None)`：读取来源区域和当前图快照，构造远程 LLM 请求，解析 `IntakeDraft`，返回未写入草稿。
2. `apply_draft(project_id, draft)`：执行 schema/来源/显式约束/关系/幂等校验，经单个 Patch 写入候选实体和关系，记录 draft hash 与审计事件。
3. `review_draft(project_id, draft_id, action)`：把接受、编辑、驳回映射到现有 review 操作；编辑仍需经过 ModelGraph 的受限 Patch。
4. `build_behavior_projection(project_id)`：复用/扩展现有 behavior projection，输出用例、场景步骤、分支和追溯状态，供 Web 和后续 F 阶段使用。

执行顺序：

```text
读取文档区域/证据
  → 构造带 region id 的上下文
  → 远程 LLM 返回 IntakeDraft JSON
  → JSON schema + 语义白名单校验
  → 确定性约束提取与优先级合并
  → local_ref 解析、稳定 ID 和关系编译
  → 单 Patch 写入候选
  → 生成行为/追溯投影
```

LLM 请求必须通过现有 `GenerativeModelPort`/profile 配置，默认只允许远程 profile；本机模型配置在本阶段不启用，也不为了测试在开发机启动模型。可以通过 SSH 隧道访问 Jiayu-intern 的 gpu1 vLLM；测试夹具仍保留，保证离线单元测试不依赖网络。

## 6. Web 交互

在现有需求分析页面增加一个“需求与用例提取”入口：

- 选择已导入文档或粘贴文本，显示来源区域数量和当前图修订。
- 启动后显示 draft 状态、模型 profile、耗时和诊断；不把原始 prompt 当作用户模型数据。
- 用三组卡片展示需求、用例/场景、实体/约束；每项显示来源、置信度、`explicit`/`llm_inferred`、假设和待澄清问题。
- 支持单项或批量接受、驳回；编辑后明确标记 `user_modified`，再次分析不得覆盖。
- 接受后提供“进入行为模型”和“进入 RFLP 分析”链接；行为图首版使用确定性 SVG/HTML 结构，不要求商业 SysML 工具。
- 缺少来源、schema 错误、远程 LLM 不可用时显示可行动诊断，不伪造成功；若已有规则需求则保留并允许人工继续。

## 7. 测试与验收证据

首轮只建立覆盖本阶段业务结果的测试，不进行多轮稳定性扩张：

- 单元测试：draft schema、来源引用、单位归一化、显式约束覆盖 LLM 推断、稳定 ID、local_ref 解析、活动顺序/分支、幂等 patch。
- 契约测试：远程 profile 请求和结构化 JSON 解析；使用 fake model 验证离线路径，不调用本机模型。
- Web/API 测试：导入文档 → 创建 draft → 展示来源 → 接受/编辑 → 行为投影/追溯矩阵。
- 一条固定中文 Word/PDF 验收 fixture：验证至少 3 个需求、1 个用例、1 个运行场景、1 个活动和来源链；不要求每个字段都被 LLM 识别，未识别部分必须进入诊断。
- 回归测试：当前 RFLP/V&V、SysML 导出/导入、review 锁定、现有远程 LLM 配置保持通过。

验收指标优先看：

```text
文档 → 结构化需求/行为 → 人工确认 → RFLP → SysML
是否走通、是否可追溯、是否可再编辑
```

## 8. 后续阶段接口

本阶段为 M3/M4 保留 `Requirement` 约束、任务场景、活动步骤和来源证据的稳定消费接口；为 M5/M6/M7 保留设计意图和澄清记录的统一来源。布局、仿真和 CAD 不应把自己的临时对象反写成需求或行为实体；它们需要通过 `DERIVED_FROM`/`SATISFIED_BY` 和工件证据接入同一 ModelGraph。

## 9. 完成定义

本设计对应的 M1/M2 子项目只有在以下事实同时成立时才算完成：

1. 一份真实 Word/PDF 文档能够生成并保存结构化需求和行为候选。
2. 每个候选能指向文档区域或明确记录推断来源。
3. 显式约束不会被 LLM 建议覆盖，隐含约束会标记为待复核。
4. 人工接受、编辑、驳回能在现有 ModelGraph 修订体系中生效。
5. 需求、用例、场景和活动能够进入现有追溯矩阵及下一阶段 RFLP 输入。
6. 远程 LLM 测试通过，开发机没有启动本地模型。

