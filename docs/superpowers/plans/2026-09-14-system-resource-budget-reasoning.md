# 系统级资源预算推理实施计划

> 本计划基于 `docs/superpowers/specs/2026-09-14-system-resource-budget-reasoning-design.md`。实现坚持 ModelGraph 为唯一事实源，先写失败测试，再实现确定性分析。

## 1. 建立预算分析数据契约

文件：

- `src/rflp_lite/methodology/architecture_synthesis.py`
- `src/rflp_lite/methodology/architecture_reasoning.py`
- `src/rflp_lite/methodology/tasks.py`
- `tests/methodology/test_architecture_synthesis.py`
- `tests/methodology/test_architecture_reasoning.py`

任务：

1. 在 synthesis 模块加入 `PhysicalBudgetAnalysis`，包含需求 ID、全部物理 ID、字段汇总、传播约束、缺口、冲突、状态、评分和 resolution options，并提供稳定的 `as_dict()`。
2. 为 `ArchitectureSynthesis` 增加默认空的 `system_budgets`，不破坏现有 positional construction 和现有输出字段。
3. 为 `PhysicalFeasibilityRow` 增加默认空的 `system_budgets`，并在 row 字典和 `physical_reasoning_payload()` 中以 JSON-compatible 形式输出。
4. 更新 physical reasoning 的结构化输出 schema，允许 `system_budgets` 数组；保持外层 `additionalProperties=False`。
5. 先添加契约测试：空预算的旧图保持既有 row 断言；系统预算对象可以 JSON 序列化；新的 reasoning payload 能被 output contract 接受。

验证命令：

```bash
pytest -q tests/methodology/test_architecture_synthesis.py tests/methodology/test_architecture_reasoning.py
```

预期：新增测试在实现前失败，完成实现后全部通过。

## 2. 实现需求作用域与系统预算计算

文件：

- `src/rflp_lite/methodology/architecture_synthesis.py`
- `tests/methodology/test_architecture_synthesis.py`

任务：

1. 从 Requirement payload 读取 `constraint_scope`；按显式 scope、`level=technical`、默认 system 的优先级选择 component/system。
2. 复用现有 R→F→L→P 与 direct Requirement→Physical 解析，稳定去重并按 ID 排序参与候选。
3. 只对 `mass_kg`、`power_w`、`memory_mb`、`bandwidth_mbps`、`cost`、`endurance_h` 求和；复用 `_number` 和 `is_unknown_measurement`。
4. 对每个需求的每个聚合约束构造字段 totals、value count、missing fields 和结构化 conflicts；已知超限优先于测量状态。
5. 生成系统预算 resolution options，影响实体包含需求与全部相关物理候选。
6. 将预算分析挂入 synthesis，并将同一预算映射到相关 rows 的 `system_budgets`，保持 row 的单候选 status/conflicts 不被改变。
7. 添加双物理候选超功耗、未知测量、technical 不聚合和显式 scope 覆盖测试。

验证命令：

```bash
pytest -q tests/methodology/test_architecture_synthesis.py
```

预期：双候选 `80+30` 对 `max=100` 产生 value `110.0` 和 `infeasible`；未知候选产生 `needs_measurement`；technical 需求不产生系统预算。

## 3. 接入 Methodology 与 Controller

文件：

- `src/rflp_lite/methodology/engine.py`
- `src/rflp_lite/methodology/controller.py`
- `tests/methodology/test_engine.py`
- `tests/methodology/test_controller.py`

任务：

1. 把既有 physical finding 的冲突变量明确为 candidate conflicts，新增 candidate/budget 分项指标。
2. 从 `architecture.system_budgets` 生成 `physical_budget_conflict` finding；entity IDs 包含需求和全部物理候选；根据 canonical trace scope 生成 impact paths。
3. 增加 `physical_budget_analysis` 与 `physical_budget_matrix`，并让 overall physical feasibility 按候选冲突、预算冲突、测量缺口统一决策。
4. 将预算 resolution options 合并进 `physical_resolution_options` 或等价的统一 trade-study metric，保证现有候选 options 行为不变。
5. Controller 将预算冲突路由到 trade study，并允许从相关预算 options 生成带完整影响范围的 action。
6. 添加 engine 与 controller 测试，验证 finding、metrics、路径、优先级和 re-entry options。

验证命令：

```bash
pytest -q tests/methodology/test_engine.py tests/methodology/test_controller.py
```

预期：预算冲突为 error、物理阶段、trade-study action；预算测量缺口不被误报为冲突。

## 4. 统一 V&V 工具和持久化出口

文件：

- `src/rflp_lite/application/engineering_tools.py`
- `src/rflp_lite/methodology/architecture_persistence.py`
- `tests/application/test_engineering_tools.py`
- `tests/runtime/test_lifecycle_rule_runtime.py`
- `tests/runtime/test_vertical_rule_runtime.py`

任务：

1. 让 `ModelConstraintCheckTool` 读取与当前 case 需求相交的 system budgets，并把预算 evidence 放入 metadata、excerpt 和 claim/outcome。
2. 保证 `failed` 只由已证实候选/预算冲突触发；未知预算和未知候选字段返回 `inconclusive`。
3. 验证 architecture persistence 对 offline 和 structured patch 的 post-CAS enrichment 会把受影响 PhysicalBlock 的系统预算 reasoning 一并写入，同时不覆盖已有人工或 LLM reasoning。
4. 扩充工具和 lifecycle 测试，验证同一 graph 上 Methodology 与工具返回同一预算事实。

验证命令：

```bash
pytest -q tests/application/test_engineering_tools.py tests/runtime/test_lifecycle_rule_runtime.py tests/runtime/test_vertical_rule_runtime.py
```

## 5. 端到端交付物、Workbench 与 SysML 回归

文件：

- `src/rflp_lite/application/deliverables.py`
- `src/rflp_lite/interface/web/templates/analysis.html`
- `src/rflp_lite/interface/web/resource_pages.py`
- `tests/application/test_deliverables.py`
- `tests/application/test_sysml_v2.py`
- `tests/e2e/test_vertical_model_generation.py`

任务：

1. 检查统一 engineering result / architecture report 是否已经透传 `architecture_synthesis.physical.budget_analyses`；仅在必要处增加明确的预算摘要，不复制计算逻辑。
2. 在分析页面和交付物中显示系统预算状态、合计值、约束和全部物理候选；没有预算时保持旧展示。
3. 验证 SysML v2 export/import 保留 `feasibility_reasoning.system_budgets`，并且重新读取后仍能关联到原 Requirement 和全部 PhysicalBlock。
4. 新增一个最小纵向测试，覆盖两个物理候选从约束输入到 Methodology、V&V tool、交付物和 reasoning round-trip 的链路。

验证命令：

```bash
pytest -q tests/application/test_deliverables.py tests/application/test_sysml_v2.py tests/e2e/test_vertical_model_generation.py
```

## 6. 文档、质量门禁和提交

文件：

- `docs/superpowers/specs/2026-09-14-system-resource-budget-reasoning-design.md`
- `docs/superpowers/plans/2026-09-14-system-resource-budget-reasoning.md`
- `README.md` 或现有方法论状态文档中与物理可行性输出直接相关的说明（仅在事实已实现时更新）

任务：

1. 用 `rg` 检查实现和文档中不存在未决占位词，复核新增字段的命名和 backward compatibility。
2. 运行全量测试、compileall、Ruff、import-linter 和仓库既有架构指标命令；遇到已有失败时记录准确失败边界，不扩大修复范围。
3. 检查 `git diff --check`、`git status`，确认未调用本机模型、未改动无关用户文件。
4. 将规格、计划、代码和测试提交为一个清晰 commit，推送当前 `codex/web-audit-2026-08-18` 分支到 GitHub，并验证本地与 origin 同步。

预期最终验收：系统级资源预算是统一 architecture synthesis 事实，R→F→L→P 的完整作用域可被分析、控制、验证工具和交付物共同消费；既有 per-block 行为与全部回归门禁保持通过。
