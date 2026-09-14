# 系统级资源预算推理设计

## 背景

当前 Methodology 已经能够对每个 `PhysicalBlock` 检查约束传播，并把单候选的缺失测量、冲突、评分和重新进入选项写入 `feasibility_reasoning`。这对候选筛选有用，但不能回答完整的系统工程问题：一个系统需求可能约束的是整个系统的功耗、质量、成本或带宽，而不是某一个物理候选。多个 PhysicalBlock 各自满足 `max_power_w=100`，合计却可能是 `80+30=110 W`。

本设计把系统预算检查加入现有确定性架构综合结果，使同一份 ModelGraph 事实同时服务于 Methodology、Controller、V&V 工具、Workbench、交付物和 SysML 投影。它不新增 LLM 调用，不新增 ModelGraph 实体或状态，也不改变既有单候选检查的语义。

## 目标

1. 在 R→F→L→P 链已经存在时，按需求作用域对相关 PhysicalBlock 的数值资源做系统级汇总。
2. 明确区分单候选冲突、系统预算冲突和测量缺口。
3. 保留完整影响链：需求、功能、逻辑组件、全部受影响物理候选。
4. 让 Controller 在预算冲突时产生可执行的 trade study / 重新进入选项。
5. 让 `model.constraint_check` 与 Methodology 读取同一份系统预算事实。
6. 让已有的架构推理持久化、交付物和 SysML round-trip 自然携带该证据。

## 非目标

- 不让 LLM 负责求和、比较或判断预算是否超限。
- 不把所有物理属性都默认相加；仅处理显式支持的数值资源字段。
- 不改变已有 `PhysicalFeasibilityRow.status` 的单候选含义。
- 不引入新的数据库表、ModelGraph EntityKind、CAS 状态或后台作业。
- 不以系统预算分析替代后续真实试验、仿真、CAD 或供应商数据。

## 预算作用域规则

约束来源仍然是 Requirement payload 根级字段以及 `constraints` / `limits` 下的 `max_*` 和 `min_*` 数值字段。作用域按以下优先级解析：

1. `constraint_scope=component`：强制按单个 PhysicalBlock 检查；这是技术需求或候选局部约束的显式覆盖。
2. `constraint_scope=system`：强制把需求 R→F→L→P 作用域内的物理候选合计检查。
3. 未声明作用域且 `level=technical`：按单个 PhysicalBlock 检查。
4. 未声明作用域且不是 technical（包括 system/stakeholder 需求）：按系统级汇总检查。

系统级汇总只纳入该 Requirement 的完整追溯作用域内的 PhysicalBlock。直接 `Requirement SATISFIED_BY PhysicalBlock` 的候选也纳入；没有任何物理候选时不生成预算冲突，只保留现有追溯/分配缺口。若一个需求作用域只有一个物理候选，仍生成系统预算分析，以便统一展示和后续扩展。

第一版只对 `_PHYSICAL_FIELDS` 中具有工程资源预算语义的字段求和：`mass_kg`、`power_w`、`memory_mb`、`bandwidth_mbps`、`cost` 和 `endurance_h`。`compute`、`latency_ms`、`thermal`、`reliability`、`availability` 保留单候选检查，除非后续定义明确的系统聚合语义。

## 数据契约

在 `architecture_synthesis.py` 中新增不可变的 `PhysicalBudgetAnalysis`：

- `requirement_id: str`
- `physical_ids: tuple[str, ...]`
- `fields: Mapping[str, object]`：每个已知可聚合字段的 `total`、`value_count` 和约束列表（每项包含 `operator`、`limit`）
- `propagated_constraints: Mapping[str, object]`
- `missing_fields: tuple[str, ...]`：格式为资源字段名，表示至少一个参与候选没有可用数值
- `conflicts: tuple[Mapping[str, object], ...]`
- `status: str`：只允许 `feasible`、`infeasible`、`needs_measurement`
- `score: float`
- `resolution_options: tuple[Mapping[str, object], ...]`

每个 conflict 至少包含：

```json
{
  "requirement_id": "requirement-id",
  "physical_ids": ["physical-a", "physical-b"],
  "field": "power_w",
  "operator": "max",
  "limit": 100.0,
  "value": 110.0,
  "scope": "system"
}
```

`ArchitectureSynthesis` 新增 `system_budgets: tuple[PhysicalBudgetAnalysis, ...] = ()`，并在 `as_dict()` 的 `physical` 区段中输出 `budget_analyses`。旧字段和旧 row 输出保持不变。

为了让受影响 PhysicalBlock 的持久化解释不丢失系统级事实，`PhysicalFeasibilityRow` 新增可选的 `system_budgets` 映射序列，默认为空；`physical_reasoning_payload()` 在有该事实时输出 `system_budgets`。每项包含 `requirement_id`、`physical_ids`、`status`、`fields`、`missing_fields`、`conflicts`、`resolution_options`。单候选 `status`、`conflicts` 和 `score` 仍然只代表该 PhysicalBlock。

## 状态与评分

对每个需求和资源字段：

- 所有参与 PhysicalBlock 都有可解析数值时，按字段求和并执行 max/min 比较。
- 有至少一个参与候选缺数值且已知部分没有证实超限时，预算状态为 `needs_measurement`，不能因为未知而推断冲突。
- 已知合计违反约束时，预算状态为 `infeasible`，即使其它字段还有测量缺口也保留冲突。
- 没有预算约束或没有参与候选时，不生成该预算分析。

预算评分为 `100 - 35 * conflict_count - 5 * missing_field_count`，下限为 0，与既有 row 的可解释评分规则一致。解析出的 `fields` 保留每个合计值及参与数量，方便用户理解“为什么超限”。

系统预算 resolution options 复用既有物理重新进入语义，但 `impact_entity_ids` 必须包含 Requirement 和全部 `physical_ids`；选项至少覆盖降低资源需求、替换/重新分配候选、调整系统预算三类路径。Controller 只把预算冲突路由到 trade study，不自动修改需求或物理候选。

## 数据流与集成边界

`synthesize_architecture(graph)` 先构造既有 per-block rows，再基于同一个 index、关系和约束解析器构造 `system_budgets`，并把预算事实映射回参与的 rows。这样离线 RuleRuntime、Structured WorkflowRunner 的 architecture persistence 和任何只读分析入口都使用相同算法。

`MethodologyEngine._analyze_physical` 使用 `architecture.system_budgets`：

- 既有 `physical_constraint_conflict` 只统计单候选冲突。
- 系统预算冲突生成 `physical_budget_conflict`，finding 的 `entity_ids` 为需求加全部物理候选，`impact_paths` 为每条完整 R→F→L→P 路径。
- `physical_conflict_count` 保持向后兼容并表示两类已证实冲突总数；新增 `physical_candidate_conflict_count` 与 `physical_budget_conflict_count` 消除歧义。
- 新增 `physical_budget_analysis` 和 `physical_budget_matrix` metrics；`physical_feasibility` 在任一类冲突时为 `infeasible`，否则在任一类测量缺口时为 `needs_measurement`。
- physical trade study 同时暴露 budget resolution options。

Controller 将 `physical_budget_conflict` 与 `physical_constraint_conflict` 使用同一 trade-study action，但预算 finding 的所有物理 ID 都必须保留在 action 的影响范围中。

`ModelConstraintCheckTool` 在筛选需求相关 rows 后，同时筛选相关 `system_budgets`。若预算有冲突，结果为 `failed`；若预算有测量缺口且没有冲突，结果为 `inconclusive`；否则与既有 row 规则一致。metadata 和 excerpt 同时包含 rows 与 `budget_analyses`，并继续通过现有 V&V evidence boundary 输出。

Workbench、deliverables 和 SysML v2 不新增专用存储结构：它们从统一 methodology / architecture synthesis payload 读取 `budget_analyses`，物理 block 的 `feasibility_reasoning.system_budgets` 通过现有持久化和 round-trip 机制保存。新的 payload 字段加入 physical reasoning contract 的白名单。

## 验收标准

1. 两个物理候选 `power_w=80` 和 `power_w=30`，同一 system Requirement `max_power_w=100`，只要都在该需求的 R→F→L→P 作用域内，就产生一个 `infeasible` 系统预算分析，value 为 110，包含两个物理 ID，并产生 `physical_budget_conflict`。
2. 同一场景把任一 `power_w` 改为 `待测量`，且已知合计未超限时，预算为 `needs_measurement`，不产生预算冲突 finding。
3. `level=technical` 的 `max_power_w` 不做跨 PhysicalBlock 求和；每个候选继续独立检查。
4. `constraint_scope=system` 和 `constraint_scope=component` 分别能覆盖默认规则。
5. Controller 对预算冲突产生带全部物理 ID 和 trade options 的 action。
6. `model.constraint_check` 对预算冲突返回 `failed`，对预算测量缺口返回 `inconclusive`。
7. 既有单候选测试、既有 lifecycle reasoning、structured schema、deliverables、SysML round-trip 和全量质量门禁继续通过。

## 风险与控制

- 物理候选重复分配可能导致重复计数；实现按稳定的实体 ID 去重，每个需求作用域内每个 PhysicalBlock 只计一次。
- 单位转换不是当前 ModelGraph 的职责；第一版要求同一字段使用同一单位，并在 `fields` 中只报告原始数值和数量。
- 需求继承/派生可能带来重复约束；同一 Requirement 的同一字段/operator 使用现有约束去重规则，预算分析按需求 ID 独立呈现。
- 系统级 finding 可能影响 UI 展示量；沿用现有 bounded guidance，仅限制展示条数，不截断底层交付和持久化证据。
