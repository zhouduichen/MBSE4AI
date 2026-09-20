# P 阶段按 Logical 作用域窄批次设计

**目标：** 让 `vertical.physical` 在 L 阶段完成按 Requirement 切片后，逐个消费当前 Logical/Function 作用域并形成可追溯的物理候选。

## 设计

- 支持批处理的 Provider 默认每个 P 请求只包含一个 Requirement；该 Requirement 的 `available_current.logical_component_ids`、Function 和约束邻居作为唯一物理作用域。
- P Prompt 要求 `physical_block.payload.logical_id` 或 `source_logical_ids`、`source_function_ids`、`source_requirement_ids`、`impact_chain` 只引用当前切片的 canonical ID，并形成 `LogicalComponent→allocatedTo→PhysicalBlock`。
- 允许不同切片选择同一物理资源（共享实现），因此合并器只去重相同实体/关系，不强制一 Logical 对一 Physical。
- 复用现有 Proposal Compiler、typed relation inference、单一 CAS Patch 和物理可行性 payload；不改物理规则、V&V 状态机或 CAD 服务。

## 验收

1. 三条 Requirement 的 P 结构化运行产生三个 singleton 请求。
2. 每个请求只携带当前 Logical/Function 作用域，不能跨批次引用逻辑组件。
3. 合并结果为每个当前 Logical 保留 `allocatedTo`，并继续通过 V&V 完成端到端追溯。
4. 本地全量测试和 2.1/2.2、3.1–3.3 产品验收继续通过；不启动本机模型。
