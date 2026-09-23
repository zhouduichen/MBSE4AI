# 完整结构化 LLM 纵向验收设计

**日期：** 2026-09-14  
**状态：** 已实现并通过离线验收
**范围：** TaskProposal 编译、五阶段结构化 LLM 验收、Controller 冲突迭代验收

## 背景

AI4MBSE 的五阶段入口已经能够把结构化 LLM 输出写入同一份 ModelGraph，也已经具备确定性 Methodology、Traceability、Review、SysML 子集和 Controller 入口。但现有结构化夹具主要验证调用顺序和局部缺口，尚未证明一份 LLM Proposal 可以一次性形成完整的 F/L/P/V&V 语义模型。

当前编译器还有一个具体的语义断点：`local_ref` 会被解析为 Relation 的 canonical endpoint，但不会解析 payload 中的 ID 字段。例如同一 Proposal 新建 Function 和 FunctionalFlow 时，LLM 可以合法地写 `source_function_ids=["function"]`，Compiler 却会把字符串 `function` 原样保存。这样 ModelGraph 的关系边可能正确，payload 作用域却不是 canonical ID，后续架构综合、V&V scope 和 SysML 往返都会得到不一致的模型。

## 目标

1. 在 Compiler 内把已知的 Proposal-local entity reference 物化为 canonical entity ID；已有上下文 ID 保持不变。
2. 对结构化 payload 中的图引用字段执行同一套解析和未知引用拒绝，避免产生孤立或半真追溯字段。
3. 用完整结构化夹具覆盖 Requirements、Functional、Logical、Physical、V&V 五阶段，证明一次产品运行能够形成完整 R→F→L→P→V&V ModelGraph。
4. 验证完整模型可以导出并重新读入 SysML v2 子集，实体/关系/payload ID 保持一致并可继续编辑。
5. 在完整模型上注入物理约束冲突，验证 Controller 先给出 Trade Study，不直接修改；用户选择后只重分析 Physical→V&V，并保留 before/after 追溯和影响链。

## 非目标

- 不调用或启动本机模型，不运行 Ollama，不进行真实 Provider 稳定性或重复实验。
- 不新增实体类型、数据库表、第二份模型真源或绕过 CAS 的写入路径。
- 不让 Compiler 根据名称猜测实体关系；只解析 Proposal-local ref 和当前 Context 中已经存在的 canonical ID。
- 不让 Controller 自动选择 Trade Study 方案；缺证据、锁定冲突和工程权衡仍暂停等待用户。
- 不把执行证据、测量值或供应商型号由夹具伪造为事实。

## 设计

### 1. Typed payload reference materialization

`compile_task_proposal` 在创建 AddEntity 之前先为本 Proposal 的每个 `local_ref` 生成 canonical ID 映射。随后对每个实体 payload 和 UpdateEntity 的 payload patch 调用同一个 `_materialize_payload_references`：

```text
context entity IDs + proposal local_ref → canonical ID map
                                      ↓
known graph-reference payload fields
                                      ↓
resolve local refs / retain canonical IDs
                                      ↓
unknown graph refs → ContractViolation
                                      ↓
AddEntity / UpdateEntity → Patch → CAS
```

只处理明确的图引用字段，不对自由文本或约束 provenance 做启发式替换。字段集合包括：

- F：`source_function_ids`、`target_function_ids`、`function_ids`、`functional_behavior_ids`、`functional_flow_ids`；
- L：`dependencies`、`dependency_ids`、`depends_on`、`depends_on_ids`、`source_function_ids`、`connected_component_ids`、`owner_id`、`shared_state_ids`；
- P：`logical_id`、`source_logical_ids`、`source_function_ids`、`source_requirement_ids`、`physical_candidate_ids`；
- V&V / 风险：`requirement_ids`、`scenario_ids`、`activity_ids`、`function_ids`、`logical_component_ids`、`physical_ids`；
- 影响与来源：`source_context_ids`、`impact_entity_ids`，以及 `impact_chain` 内的上述 ID 字段。

`evidence_ids`、`execution_evidence_ids` 和外部 `source_ids` 不被当作 Proposal-local 图实体处理；它们保留为证据/来源标识，并由现有证据边界管理。列表去重保持输入顺序，映射不会修改实体 ID 生成所依赖的名称、来源和生命周期元数据。

### 2. 完整结构化五阶段夹具

新增 `CompleteVerticalModel` 测试夹具，遵守与真实远程模型相同的 `GenerationRequest → TaskProposal JSON → StructuredModelRuntime → Compiler → Validator → CAS` 路径。夹具按当前上下文的 canonical IDs 形成最小但完整的模型：

- Requirements：System、Stakeholder、Concern、Lifecycle、Scenario、Activity，并将输入 Requirement 回接到 Concern；
- Functional：Function、FunctionalFlow、FunctionalScenario，并更新 Requirement 的 `functional_behavior_ids`；
- Logical：LogicalComponent、Interface、State，使用功能/流/状态的 canonical IDs，形成 `allocatedTo`、`exchangesWith`、`connectedTo` 和 `decomposes`；
- Physical：PhysicalBlock，传播 Requirement constraints，写入 feasibility、trade study、impact chain 和 Logical→Physical allocation；
- V&V：VerificationCase、ValidationCase、Hazard、FailureMode，写入完整计划字段、RFLP scope、`cross_analysis_status=checked` 和风险缓解关系。

夹具不提供 execution evidence，不把计划生成误报为测试已执行；所有新对象通过现有语义校验后才进入 `validated`。

### 3. Controller 冲突迭代

完整结构化运行结束后，测试通过 Review/CAS 编辑一个物理候选的 `power_w`，并在 Requirement 中保留 `max_power_w`。Methodology Engine 必须形成 `physical_constraint_conflict` 及 R→F→L→P 影响实体，Controller 返回 `trade_study` 选项且 `iterate_controller` 不自动变更 revision。

测试选择一个已有的物理替代方案，调用现有 `execute_controller_action`。验收只允许 `physical` 和 `verification_validation` 进入 reanalysis，Controller decision 要进入后续 ContextBundle；新候选保留 constraint provenance，锁定实体不被覆盖，before/after traceability 和 audit 完整可读。

### 4. 交付与回读

测试从最终 ModelGraph 生成完整交付包，并对 `model.sysml` 调用已有 `sysml_to_graph`。回读结果必须保持：

- 所有非弃用实体的 canonical ID、kind、status 和 payload 中的图引用；
- 所有 Relation 的 source/predicate/target；
- 同一 revision-bound snapshot 可继续通过 Review/Edit 产生新 CAS revision。

## 失败处理

- Proposal-local payload ref 映射失败或未知图 ID：在 Patch 创建前返回 `ContractViolation`，不写 Revision。
- 任一阶段结构化输出不完整：保留现有候选、completion issue 和 Controller action；阶段不得被标记为完整。
- 物理约束未知：保持 `needs_measurement`；只有实际值违反显式边界才进入 Trade Study。
- Controller 遇到 Trade Study 或锁定/人工修改冲突：返回 `awaiting_decision`，不自动写图。
- SysML 回读冲突：沿现有整次导入拒绝规则处理，不部分导入。

## 验收

1. Compiler 单元测试证明新建实体 payload 的 local refs 被替换为 canonical IDs，未知引用在 CAS 前拒绝。
2. 完整结构化运行五个阶段各至少一次；若所有阶段首轮完成，不触发反馈重试，所有 StageResult 为 `completed` 且无 completion issue。
3. 至少一条 Requirement 具有完整 `R→F→L→P→Verification/Validation` 路径，V&V payload scope 与共享 resolver 一致。
4. SysML 导出/导入保持实体、关系和 payload graph IDs；编辑后 revision 增长且原始 ID 保持。
5. 物理冲突先暂停在 Trade Study，选择后只重跑 Physical→V&V，并产生替代候选、影响链和 before/after traceability。
6. 全量测试、compileall、Ruff、架构指标、import-linter 和 `git diff --check` 通过。
