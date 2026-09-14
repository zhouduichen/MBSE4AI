# 逐需求纵向覆盖闭环设计

## 目标

让 AI4MBSE 对多条输入需求逐条建立并检查 `Requirement → Function → Logical → Physical → Verification/Validation` 链路。阶段反馈不能只说明“当前阶段有一个 Function 或一个 Physical”，而必须告诉 LLM 哪些 canonical Requirement 仍缺少哪一条关系，以及下一次尝试应补齐什么。

本轮服务于最终产品目标：用户输入自然语言、文档或既有模型后，Harness 负责持续推动每一条需求形成可编辑、可追溯、可校核的 MBSE 模型。它不新增 LLM Provider、不启动本地模型、不改变 ModelGraph schema，也不把完成度改成实体数量指标。

## 当前缺口

`MethodologyEngine` 已经计算 `functional_requirement_coverage`、`logical_allocation_coverage` 和 `physical_allocation_coverage` 等比例，但 `evaluate_vertical_stage` 的阶段检查仍主要是全局布尔条件。多需求的 LLM 输出如果只覆盖其中一条需求，反馈中缺少具体的 Requirement ID 和断点，下一轮模型无法稳定地只修复缺失链路。

## 设计

### 1. 纯函数式 Coverage Resolver

在 `src/rflp_lite/methodology/vertical_coverage.py` 增加只读 resolver。它从当前 `ModelGraph` 的 active 实体和 typed predicates 计算每条需求的覆盖情况，不写库、不调用 LLM。每行至少保留：

- `requirement_id`；
- 适用的阶段；
- 每一跳实际 target IDs；
- 缺失的关系/阶段标签；
- 最长可用路径。

覆盖语义固定如下：

- Functional：非 technical Requirement 必须通过 `satisfiedBy` 到至少一个 Function；
- Logical：上述 Function 必须通过 `allocatedTo` 到至少一个 LogicalComponent；
- Physical：上述 LogicalComponent 必须通过 `allocatedTo`/`realizedBy` 到至少一个 PhysicalBlock；technical Requirement 允许通过自身 `satisfiedBy` 直接连接 PhysicalBlock；
- Assurance：每个 active Requirement 必须同时通过 `verifiedBy` 和 `validatedBy` 连接正确类型的 Case，并检查 Case 的 RFLP scope；
- rejected/deprecated target 不计入覆盖，locked/accepted/validated/candidate 的 active 节点可作为生成阶段的事实输入。

同一需求有多个 Function 或架构候选时，只要存在一条合法完整路径即算该跳覆盖；resolver 仍返回全部 typed targets，供 UI 和 LLM 选择与审查。

### 2. 阶段完成检查和反馈

`evaluate_vertical_stage` 对 Functional、Logical、Physical、Verification/Validation 增加一个 `requirement_coverage:<stage>` 检查。检查内容包括 `passed`、`requirement_count`、`covered_count`、`missing_requirement_ids` 和 `gaps`。失败时追加稳定 issue code `completion_requirement_coverage:<stage>`，原有细粒度 reasoning checks 保持不删除，以兼容既有任务台账。

`MethodologyEngine.context_guidance` 将同一 resolver 的有界结果放入 `methodology_guidance.requirement_coverage`，最多携带 24 条缺口和每条的 canonical IDs/缺失标签。这样首轮和反馈轮都能看到相同的、由当前 revision 计算出的断点，而不是依赖自由文本诊断。

### 3. Prompt 约束

五阶段 Prompt 增加统一指令：优先修复 `stage_completion.requirement_coverage.missing_requirement_ids`，复用已有 canonical IDs，只补缺失的实体/关系；如果某条需求因证据或人工锚点不能闭合，保留 `open_questions`，不得把不完整链路伪装成完成。该指令不允许 LLM 改写 coverage 结果，也不扩大 PatchPolicy。

### 4. 用户可见结果

阶段结果继续保留现有状态、warnings 和 completion checks；新增检查内容通过现有 `as_dict()` 自动进入 API/Web 响应。追溯矩阵继续显示每条需求的独立覆盖，方法论报告的 aggregate metrics 保持兼容。无需向用户暴露内部 23-task 调度细节。

## 流程

```text
当前 ModelGraph
      ↓
逐需求 Coverage Resolver
      ↓
阶段检查 + 缺口 Requirement IDs
      ↓
methodology_guidance 注入结构化 LLM
      ↓
同阶段最多一次反馈重试
      ↓
重新计算 coverage / Traceability / Controller
```

## 不变约束

- ModelGraph 仍是唯一真源，resolver 只读；所有 LLM 变更仍经过 Structured Runtime、Compiler、Validator、PatchPolicy 和 CAS。
- 不新增本地模型调用，不启动 Ollama，不访问本机模型端口；远程 OpenAI-compatible Runtime 的选择和配置保持不变。
- 不把 `candidate`、未执行 V&V 计划或未知物理测量提升为完整事实。
- 不因多需求而把 LLM 调用拆成每条需求一次；保持阶段级调用和最多一次同阶段反馈。
- 既有单需求、文档输入、SysML 往返、Controller 迭代和离线 RuleRuntime 行为保持兼容。

## 验收

1. 三条需求中只有两条有 Function 时，Functional completion 明确失败并列出缺失 Requirement ID。
2. 只有一条需求缺少 Logical/Physical/V&V 时，各对应阶段列出准确断点，不以其他需求的覆盖替代它。
3. 结构化 Runtime 的反馈轮收到与当前 revision 匹配的逐需求缺口，并可只补缺失链路后使阶段通过。
4. 完整多需求离线生成仍保持每条需求独立的完整 RFLP/V&V 追溯，现有 SysML、交付包和全量测试继续通过。
