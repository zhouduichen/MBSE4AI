# Executable V&V Plan Design

## 目标

把现有 `VerificationCase` 和 `ValidationCase` 从只有方法与通过准则的粗粒度记录，提升为可执行、可审查、可追溯的 V&V 计划。该改动补齐目标链中的最后一段：

```text
Requirement
  -> Verification Objective
  -> Method
  -> Test Condition
  -> Stimulus
  -> Procedure
  -> Expected Result
  -> Acceptance Criteria
  -> Execution Evidence
```

Verification 和 Validation 继续保持为两个独立的用例类型；计划字段完整不表示测试或演示已经通过。

## 当前缺口

当前模型只稳定表达 `method`、`precondition`、`input`、`procedure`、`expected_result` 和 `pass_criteria`。`precondition` 同时承担环境、配置和边界条件，`input` 同时承担测试数据和触发动作，导致：

- LLM 没有明确的字段契约来生成可执行测试条件和刺激；
- Methodology Engine 无法区分“计划不完整”和“执行证据缺失”之外的具体执行准备缺口；
- V&V 工作台和 `vv-plan` 交付物无法展示实际要执行的条件与动作；
- Assurance 投影错误地把 `evidence_ids` 当成执行证据，破坏了输入资料证据与测试结果证据的语义分离。

## 设计

### 1. 统一计划字段

每个新生成的 `VerificationCase` 和 `ValidationCase` 都应提供以下非空字符串字段：

| 字段 | 语义 |
| --- | --- |
| `method` | test、analysis、inspection、demonstration 等验证/确认方法 |
| `verification_objective` | 本用例证明或确认的工程目标 |
| `precondition` | 执行前系统、用户和设施所需的初始状态 |
| `test_condition` | 可控的环境、配置、工况、边界和约束条件 |
| `input` | 测试或演示使用的数据、对象或任务 |
| `stimulus` | 施加给系统的事件、操作或输入序列 |
| `procedure` | 可重复执行的步骤 |
| `expected_result` | 可观察的期望行为或结果 |
| `pass_criteria` | 判定满足需求的明确准则 |

`evidence_ids` 仅引用输入资料或设计依据；`execution_evidence_ids` 仅引用实际测试/演示结果；两者不能互相替代。没有执行证据时，运行时保留 `execution_evidence_ids=[]`，并将 `evidence_required=true`、未决问题写入 `open_questions`。

旧模型或人工导入的用例可以继续被读取，但缺少上述字段时必须被 Methodology Engine 和交付物标为 `INCOMPLETE`，不能被静默当成完整计划。

### 2. 生成与校核路径

- V&V vertical prompt 要求 LLM 对两类用例生成完整计划字段，并保留风险分支、RFLP 作用域和证据语义。
- 结构化 Proposal Schema 对字段进行类型和非空校核；语义校核对新增字段执行同样的必填检查。失败的 LLM 输出沿现有候选/需要评审路径处理，不绕过 CAS、Review 或状态机。
- 离线 `VerticalRuleRuntime` 和兼容的生命周期规则运行时提供确定性的完整字段，使离线端到端验收仍能证明产品链路，而不需要本地模型。
- Methodology Engine 的 `assurance` 分析、覆盖指标和 findings 使用同一字段集合，缺字段与执行证据缺失分别报告。

### 3. 产品投影与交付物

Assurance 页面在 V&V 矩阵中展示测试条件和刺激；详细计划字段保持面向工程用户可读，TaskSpec、Patch、CAS 等内部实现继续隐藏。`vv-plan.json` 保留原有稳定字段并增加上述计划字段，`vv-plan.md` 增加 Condition 和 Stimulus 列。

`plan_status=PASS` 只表示计划字段齐全；`execution_status` 仍由真实执行记录驱动。修正 Assurance 投影后，`execution_evidence_ids` 必须来自同名 payload 字段，而不能回退到 `evidence_ids`。

## 范围边界

- 不新增独立的 `VerificationPlan` 实体，不改变 `ModelGraph` 的唯一真源定位。
- 不实现本机模型调用，不启动 Ollama，也不增加新的模型供应商。
- 不把 V&V 计划生成伪装成执行，不自动制造执行证据。
- 不重做已有的 RFLP trace resolver、CAS、Review 或 SysML 导出协议。

## 验收标准

1. 新生成的 verification/validation case 都包含九个完整计划字段，并能通过结构化 Schema 和语义校核。
2. 缺少 `test_condition` 或 `stimulus` 的用例会产生 `*_case_incomplete` finding，并在 `vv-plan` 中列出缺字段。
3. 离线垂直生成后，每个需求都有独立的 VerificationCase 和 ValidationCase，字段完整，RFLP 作用域与执行证据语义保持正确。
4. Assurance 页面和 `vv-plan.md` 能看到 test condition、stimulus；计划完整但无执行证据时仍显示待执行。
5. 来源证据不会被计为执行证据；真实 V&V 执行路径和既有失败反馈行为不改变。
6. 全量离线测试、编译、Ruff、Import Linter 和 `git diff --check` 通过；验证过程中不运行本机模型。
