# Methodology Engine v2：时序、安全与资源约束推理设计

## 状态

本设计服务于 MBSE4AI 的完整目标：用户给出自然语言、工程资料、历史模型或已有 SysML 后，系统持续生成并维护一份可追溯、可校核、可迭代的 Typed ModelGraph。它是下一条产品纵向能力切片，不改变 ModelGraph 是唯一真源，也不新增第二套运行状态机。

## 背景与缺口

现有 `architecture_synthesis` 已能从 Function 的显式依赖、共享状态、功能流和当前分配形成 Logical 候选，也能为 PhysicalBlock 传播 `max_*`/`min_*` 约束并报告冲突或测量缺口。但以下工程推理还没有成为统一的一等证据：

1. Logical 候选评分没有惩罚跨分区的时序协调成本，也没有识别违反显式安全隔离的分区。
2. `architecture_reasoning` 虽然保存时序文本，却不能说明这些约束怎样影响候选比较。
3. Methodology guidance 和 Architecture Report 看不到上述决策证据，因此结构化 LLM 只能读到结论，不能沿证据补全或重新分区。
4. Physical 约束的传播、缺失测量和冲突已有数据结构，但需要统一输出成“约束证据 → 候选状态 → 回流动作”的决策对象，避免报告与 Controller 各自解释。

## 设计目标

- 继续使用纯函数 `synthesize_architecture(graph)`，不调用 LLM、不写 Repository、不改变 CAS。
- 让显式 Function payload 成为时序/安全证据的输入；缺乏结构化端点时不猜测安全关系。
- 每个 Logical candidate 都能回答：哪些依赖、功能流、共享状态、时序约束和安全隔离支持或反对该分区；跨分区时序成本和安全隔离违反数是多少。
- LogicalComponent 持久化载荷必须能引用同一批 canonical Function/Flow/State ID，并完整复制候选比较结果。
- PhysicalBlock 的 `feasibility_reasoning` 必须继续区分 `feasible`、`infeasible` 和 `needs_measurement`，并同时携带冲突字段、缺失字段、约束来源、影响链和回流选项。
- `MethodologyReport.metrics`、`methodology_guidance`、Workbench payload 和 Architecture Report 使用同一序列化结果，不增加并行格式。
- 不把评分当成自动接受；有安全隔离违反或测量缺口时仍需 Review/Controller 决策。

## 非目标

- 不实现真实仿真、调度求解器、形式化安全证明或硬件功耗模型。
- 不新增 `dependsOn` 关系谓词；本切片兼容当前 payload 中的 `dependencies`、`shared_state`、`timing_constraints` 和结构化安全约束，避免破坏既有 ModelGraph/SysML 数据。
- 不启动或安装本机模型；真实 LLM 测试仍只使用显式配置的远程 Profile。
- 不进行 3-task/5-task/9-task 的重复稳定性实验；验收聚焦单次逻辑/物理候选推理、五阶段离线闭环和现有结构化回归。

## 输入语义

### 时序约束

Function payload 的 `timing_constraints` 接受字符串列表或对象列表。字符串只有在多个 Function 使用同一个非空值时才形成一组需要协调的 Function pair；对象可以使用 `function_ids` 或 `members` 指定端点，并可携带 `id`、`deadline_ms`、`latency_ms`、`order` 等证据字段。未能解析为当前 Function canonical ID 的项只作为原始 payload 保留，不参与评分。

### 安全隔离

Function payload 的 `safety_isolation` 或 `safety_constraints` 接受对象列表。对象必须显式包含至少两个当前 Function 的 `function_ids`/`members`，并且 `must_separate` 为真，才形成安全隔离 pair；对象的 `id`/`boundary`/`reason` 作为证据摘要。仅有自然语言字符串不推导 pair，避免把安全语义臆测成架构硬约束。

## Logical 候选契约

`LogicalArchitectureCandidate` 增加：

- `timing_constraint_count`：参与评估的时序约束组数；
- `timing_cut_count`：时序约束组被分到多个 partition 的数量；
- `safety_isolation_count`：参与评估的安全隔离 pair 数；
- `safety_violation_count`：必须隔离的 pair 被放在同一 partition 的数量；
- `constraint_violations`：稳定的结构化摘要，至少含 `kind`、`function_ids` 和 `message`。

候选 score 在原有 cohesion/balance 基础上扣除时序切分成本和安全违反成本；安全违反使用显著更高的惩罚，但候选仍保留供 Review 比较。`dependency_cluster_search` 仍只由依赖/共享状态连通分组，功能流只计算跨组件交换；时序约束用于候选评价，不会无证据地把功能合并。

`LogicalComponent.payload.architecture_reasoning` 的 `basis` 增加 `safety_isolation`，每个 alternative 原样包含上述计数和 `constraint_violations`。推荐结果仍只是 Methodology 的确定性建议，`selection_status` 由现有 Review/Controller 流程决定。

## Physical 决策契约

保持每个 PhysicalBlock 一行 `PhysicalFeasibilityRow`，并在其序列化结果中统一表达：

```text
Requirement canonical IDs
→ propagated_constraints + constraint_provenance
→ measured value / missing measurement fields
→ conflicts
→ feasible | infeasible | needs_measurement
→ score + resolution_options + impact chain
```

本切片只补齐缺失的决策证据字段和 guidance/report 暴露，不把未知值当成冲突，不伪造跨候选资源总量。若后续需要电池能量、热网络或系统级预算，将作为单独可验收切片扩展该契约。

## 运行与交互

1. Logical/Physical Vertical Runtime 用 `synthesize_architecture` 的同一结果生成/更新 payload。
2. `MethodologyEngine` 将时序/安全指标、候选违反和物理决策摘要放进 report。
3. `build_methodology_guidance` 有界地传递这些字段给下一次结构化 LLM 请求。
4. Controller 继续在明确冲突或需 Review 时暂停并提供 Trade Study；不自动接受候选。
5. Workbench 和 SysML 通过既有 payload 通道读取这些事实；不增加 UI 专用真源。

## 验收

- 一个包含共享时序组和显式安全隔离 pair 的 Function Graph 产生可比较的 Logical candidates；跨时序分区有 `timing_cut_count`，违反隔离有 `safety_violation_count` 和结构化 `constraint_violations`。
- 没有显式安全端点的自然语言字符串不会产生安全违反。
- 现有共享状态/功能流/功耗冲突/未知测量测试保持通过。
- 离线自然语言五阶段仍形成完整 R→F→L→P→V&V trace；Logical/Physical reasoning payload、Workbench 和 SysML round-trip 保持一致。
- 全量 pytest、compileall、ruff、import-linter 和 architecture metrics 通过；不产生本机模型调用。
