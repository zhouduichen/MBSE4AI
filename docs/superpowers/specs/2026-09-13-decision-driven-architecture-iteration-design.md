# 决策驱动的架构迭代设计

**状态：** 已确认设计，进入实施计划

## 背景

AI4MBSE 当前已经能够对 ModelGraph 做物理约束冲突分析，Controller 也能把冲突路由为 Trade Study，并在用户选择方案后调用受影响的下游阶段。但离线 Vertical Runtime 在重跑时主要按原实体名称幂等处理，选择方案不会实质改变 Logical/Physical 候选。因此当前链路更接近“记录了决定并重新执行”，还没有形成“决定驱动局部重设计”的产品闭环。

本轮只补这个纵向缺口，不重新建设 Run、CAS、Prompt、Compiler 或新的状态机。

## 目标与边界

用户在 Controller 中确认架构 Trade Study 选项后，系统必须：

1. 将选择作为结构化决策传给受影响的 Vertical Stage；
2. 在离线 Runtime 中依据决策生成可区分、可追溯的 Logical 或 Physical 架构变体；
3. 保留旧候选作为历史/比较依据，除非已有锁定实体使其不可变；
4. 在新候选中保存决策来源、选项和触发 revision，并继续传播 Requirement 约束；
5. 重新计算 Traceability、Methodology 和 Controller，明确仍未解决的冲突或测量缺口；
6. 不因为选择了“降低功耗”“增加资源预算”等方案而臆造数值、修改用户需求或宣称可行。

本轮不做供应商选型、仿真、自动修改 Requirement 数值、自动替用户确认需求，也不引入新的 EntityKind。决策以现有审计事件、ContextBundle 和架构变体 payload 保存。

## 现有入口与决策契约

保留现有入口：

```text
GET  /projects/{project_id}/controller
POST /projects/{project_id}/controller/execute
             {action_id, option_id, expected_revision}
```

Controller 已产生如下决定对象并传入 `ModelGenerationService.reanalyze`：

```json
{
  "action_id": "controller-action-…",
  "option_id": "trade-option-…",
  "option": "one_component_per_function",
  "task_id": "architecture_evaluation",
  "target_entity_id": "logical_component-…",
  "revision": 12
}
```

Vertical Runtime 只消费 `option`、`option_id`、`action_id`、`task_id` 和 `revision` 这些标量字段；缺少或不认识的选项时继续使用已有生成逻辑，不阻塞正常重分析。

## Logical 迭代

Logical Stage 从 `ContextBundle.controller_decisions` 读取最近一次决定：

- `one_component_per_function`：每个 active Function 形成独立 Logical Component；
- `shared_coordinator`：所有 active Function 进入一个共享协调 Logical Component，并明确 `coupling=high`、需要评审的架构依据；
- `current_dependency_partition`：沿用当前依赖、共享状态和时序规则；
- 未知选项：沿用当前规则并在 decision record 中保留“未应用”诊断。

应用架构选择时，当前未锁定的 Logical Component 可以被 `Deprecate`，随后生成带变体后缀的新组件；旧实体、稳定 ID 和历史关系仍留在 ModelGraph 中。锁定组件不得被自动弃用，系统改为并存生成变体并在 payload 中标记 `blocked_by_locked_entity`。

新 Logical Component 的 payload 增加：

```json
{
  "architecture_variant": "one_component_per_function",
  "architecture_decision": {
    "action_id": "…",
    "option_id": "…",
    "option": "one_component_per_function",
    "task_id": "architecture_evaluation",
    "source_revision": 12
  }
}
```

原有 `responsibility`、`partition_basis`、`dependencies`、`shared_state`、`timing_constraints`、`safety_isolation`、`cohesion`、`coupling` 和 `architecture_rationale` 继续必填。架构选择只改变分区和解释，不填充没有证据的性能数值。

## Physical 迭代

Physical Stage 对物理 Trade Study 选项生成候选变体：

- `更换物理候选或计算架构`：为当前 active Logical Component 生成独立的替代 Physical Block，标记 `candidate_variant=alternative`；
- `降低计算或功耗需求`：保留现有 Physical 候选，记录该决策并增加需要重新评估的 `open_questions`，不降低 `power_w`；
- `调整需求约束或资源预算`、`增加电池质量或资源预算`：只记录待用户/利益相关者确认的决策，不修改 Requirement 或物理测量值。

Physical 变体继续携带 `source_requirement_ids`、`propagated_constraints` 和 `propagated_constraint_provenance`。旧物理候选不因 Trade Study 自动变为满足约束；如果已有实测值仍违反边界，Methodology 继续报告 `physical_constraint_conflict`。

## 数据流与一致性

```text
Methodology finding
      ↓
Controller Trade Study options
      ↓ user selects option_id
controller.trade_study.decided audit
      ↓
ContextBundle.controller_decisions
      ↓
Logical / Physical Vertical Runtime
      ↓
variant Patch through existing CAS and patch policy
      ↓
Traceability + Methodology + Controller re-analysis
```

变体 Patch 仍通过现有 `TaskSpec` writable kinds、锁定保护、expected revision 和 Repository CAS。Decision payload 只保存有限标量，不能借此绕过 Review 或直接更新用户实体。每次局部重设计都使用已有独立 `vertical_reanalysis` Run，并在结果中返回 `controller_decision`、变体实体和新的 findings。

## 验收标准

1. Logical 共享状态冲突选择 `one_component_per_function` 后，未锁定旧组件被弃用，并产生每 Function 一个带决策 provenance 的新 Logical Component；Traceability 仍能找到 active R→F→L→P→V&V 路径。
2. 选择 `shared_coordinator` 后，产生单一共享协调组件，Methodology 明确报告高耦合需要评审，而不是错误地报告完全通过。
3. Physical 冲突选择替代候选后，产生带 `candidate_variant` 和 `architecture_decision` 的新 Physical Block，约束和来源 ID 不丢失；旧违反候选仍可追溯，未测量/冲突状态不被隐藏。
4. 锁定的旧架构实体不会被弃用或覆盖，结果明确标识并存变体或锁定阻塞。
5. 选择未知或缺失的 option 时保持兼容行为，不产生异常或无来源实体。
6. API、应用服务、Rule Runtime、Methodology、SysML/交付包和全量测试保持通过。

## 测试策略

- Controller/Application：验证已有决定对象进入 reanalysis 的 ContextBundle，并记录决定审计；
- Rule Runtime：验证三种 Logical 分区选择、Physical 替代候选和未知选项回退；
- E2E/API：从生成、编辑触发冲突、读取 Trade Study、选择 option 到局部重分析，检查变体、追溯和 findings；
- 安全回归：锁定实体、CAS revision、旧候选保留、约束传播和架构预算继续通过。
