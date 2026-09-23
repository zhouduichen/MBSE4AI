# First-Class Logical/Physical Architecture Reasoning Design

**Date:** 2026-09-14

**Status:** Approved for implementation

## Goal

把现有 Logical/Physical 方法论分析从“报告中计算出的临时候选”收敛为可追溯、可导出、可重新读取并可继续编辑的 ModelGraph 语义，同时保持现有 `Requirement → Function → LogicalComponent → PhysicalBlock → V&V` 纵向链不变。

## Context and problem

当前仓库已经具备三类能力：

- `architecture_synthesis.py` 根据 Function 依赖、共享状态、功能流、当前分配和物理约束计算 Logical 候选与 Physical 可行性行；
- `VerticalRuleRuntime` 生成可编辑的 LogicalComponent、PhysicalBlock、接口、状态和 V&V；
- `SystemsEngineeringController` 能根据冲突或分区问题给出 Trade Study 选项，并将选中的逻辑/物理变体写回图。

但这三类结果的语义还没有完全统一：候选比较主要存在于 Methodology 报告，节点 payload 只保存了部分依据，导出后的 SysML 与下一次分析只能间接重建这些信息。这样会让用户看到“有候选和评分”，却不能把这次架构推理作为模型的一部分继续审查。

## Scope

本子项目只处理 Logical/Physical 架构推理闭环：

1. 为现有 LogicalComponent 和 PhysicalBlock 定义统一的结构化推理 payload；
2. 让离线纵向 Runtime 和结构化 LLM 输出都能保存该契约；
3. 让 MethodologyEngine、Controller、Workbench 和 SysML round-trip 读取同一份字段；
4. 让 Trade Study 选择记录当前决策、影响链和旧架构版本；
5. 用一条多 Function、多约束的端到端测试验证推理、冲突、选择、导出和编辑。

## Non-goals

- 不新增 `ArchitectureCandidate`、`TradeStudy` 等实体类型，不做数据库迁移；
- 不改变 ModelGraph、Patch、CAS、Status 或 V&V 的基础协议；
- 不把 LLM 稳定性实验扩展为多轮大规模 benchmark；
- 不在本机启动模型。结构化 LLM 验证只使用已有 scripted model 或明确配置的远程 OpenAI-compatible endpoint；
- 不重做 Web 页面视觉，只补充已有 Model/Analysis 资源对结构化字段的读取（如果现有通用 payload 展示已经满足，则不添加重复 UI）。

## Architecture decision

### 1. ModelGraph remains the only truth

`ArchitectureSynthesis` 继续保持纯函数和只读职责。它从当前 ModelGraph 计算候选，不直接修改仓库。生成阶段在完成 Logical/Physical typed output 后，将规范化的推理结果作为同一 ModelGraph 中现有节点的 payload 更新写入；所有写入仍通过经过 Validator 的 Patch 和 CAS 完成。

不把 MethodologyReport 或 ControllerPlan 当成第二份模型。它们只是读取节点 payload 和图关系后形成的投影。

### 2. Logical reasoning payload

每个活动 `LogicalComponent` 保存 `architecture_reasoning`：

```json
{
  "basis": {
    "function_ids": ["function-..."],
    "functional_flow_ids": ["functional_flow-..."],
    "dependency_pairs": [["function-...", "function-..."]],
    "shared_state": ["task_state"],
    "timing_constraints": ["..."]
  },
  "alternatives": [
    {
      "alternative": "dependency_cluster_search",
      "partitions": [["function-..."], ["function-..."]],
      "score": 82.5,
      "cohesion": 1.0,
      "coupling": 0.0,
      "cross_component_exchange_count": 0,
      "shared_state_cut_count": 0,
      "dependency_cut_count": 0,
      "rationale": "..."
    }
  ],
  "recommended_alternative": "dependency_cluster_search",
  "selected_alternative": "",
  "selection_status": "needs_review"
}
```

`alternatives` 必须保留候选的 canonical Function IDs；不得只保存名称。`selected_alternative` 只有在用户或 Controller 明确选择后才填写；普通离线生成只能标记 `needs_review` 或 `generated`，不能把推荐方案伪装成用户已接受。

每个组件的 payload 还保留现有局部字段（`partition_basis`、`dependencies`、`shared_state`、`cohesion`、`coupling`、`architecture_rationale`），以兼容现有导出和调用方。局部字段与 `architecture_reasoning` 由同一规范化函数生成，避免两套评分口径。

### 3. Physical reasoning payload

每个活动 `PhysicalBlock` 保存 `feasibility_reasoning`，其字段与 `PhysicalFeasibilityRow` 一一对应：

```json
{
  "requirement_ids": ["requirement-..."],
  "logical_ids": ["logical_component-..."],
  "function_ids": ["function-..."],
  "propagated_constraints": {"max_power_w": 50},
  "missing_fields": ["mass_kg", "latency_ms"],
  "conflicts": [],
  "status": "needs_measurement",
  "score": 75.0,
  "resolution_options": []
}
```

已有的 `propagated_constraints`、`propagated_constraint_provenance`、`feasibility`、`alternatives`、`trade_study`、`impact_chain` 和 `resolution_options` 继续保留。规范化结果必须区分：

- `infeasible`：已知实测值违反明确约束；
- `needs_measurement`：缺少 SWaP-C、可靠性、热或续航测量；
- `feasible`：所有必需字段和约束检查都已有充分数据。

未知值不得生成冲突，冲突不得由缺失值推断。

### 4. Data flow and decision semantics

```text
ModelGraph
  → ArchitectureSynthesis（纯计算）
  → Logical/Physical stage typed Patch
  → architecture_reasoning / feasibility_reasoning payload
  → MethodologyEngine + Controller + Workbench + SysML
  → 用户选择 Trade Study
  → versioned variant Patch + architecture_decision
  → 受影响阶段定向重分析
```

首次生成时只形成候选和推荐，不自动接受架构。Controller 仍然是决策编排器：

- 逻辑分区问题生成 Logical Trade Study；
- 已知物理冲突生成 Physical Trade Study；
- 用户选择后写入 `architecture_decision`，保存 action、option、source revision 和影响实体；
- 未锁定、未人工修改的旧节点可以版本化弃用；锁定或人工修改节点不得覆盖；
- 变体必须继续保留 RFLP 和 V&V 影响链，不能只改变名称。

### 5. Compatibility boundary

新字段使用普通 JSON-compatible payload，现有 EntityKind、RelationPredicate、SysML 子集和 JSON 导出无需新增语法。旧图缺少新字段时由规范化读取函数返回空候选或从现有字段重建，不得因为历史模型缺字段而导入失败。

## Validation and acceptance

### Unit-level

- 共享状态和显式依赖把相关 Function 聚合到同一 dependency-cluster candidate；只有功能流而没有依赖证据时保持独立并报告跨组件交互；
- Logical payload 的 candidate partition、score、cohesion、coupling 和 basis 使用 canonical IDs；
- Physical constraint check 对已知功耗冲突返回 `infeasible`，对缺少测量返回 `needs_measurement`，两者不混淆；
- 旧 payload 没有新字段时仍可读取并生成兼容的空/降级 reasoning projection。

### End-to-end

使用至少两个功能、一个共享状态和一个 `max_power_w` 需求：

1. 生成完成后，Graph 中存在 R→F→L→P→V&V 完整追溯；
2. LogicalComponent payload 中存在可比较候选及其 canonical Function IDs；
3. PhysicalBlock payload 中存在传播约束、可行性状态、冲突/测量缺口和回流选项；
4. 用户选择一个 Logical 或 Physical Trade Study 选项后，revision 增长，决策与影响实体保留，旧版本按锁定/人工修改规则处理；
5. ModelGraph 导出到 SysML 再导回后，新 reasoning payload、架构决策、关系和稳定 ID 不丢失；
6. 用户可以继续编辑 Function/Logical/Physical，并得到绑定新 revision 的影响计划；
7. `pytest -q`、`compileall`、`ruff`、架构指标、import-linter 和 `git diff --check` 全部通过。

## Future extension

当这个契约在离线 Runtime 和 scripted structured model 上稳定后，再把 Controller 的“候选生成/权衡解释”交给远程 LLM，并用 Bare LLM、Prompt-only 和 Harness 三轨比较。该扩展不属于本子项目，也不影响离线验收。
