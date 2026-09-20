# L 阶段按 Function 窄批次设计

**目标：** 让 `vertical.logical` 消费 F 阶段结果时按单个 Requirement 的 Function 作用域生成可追溯的逻辑架构切片。

## 范围

- Logical 请求默认每批只包含一个 Requirement，并保留该 Requirement 当前可见的 Function、FunctionalFlow 和上游 System。
- Prompt 明确要求生成 `logical_component`、`interface`、`state`，并使用 typed payload 连接当前 Function。
- 保持现有 Proposal Compiler、关系推断和单一 CAS 合并边界；不改 UI、状态机、SysML 导出或远程实验。

## 追溯契约

每个 L 切片必须能够形成：

```text
Requirement → satisfiedBy → Function → allocatedTo → LogicalComponent
                                             ├─ connectedTo → Interface
                                             └─ decomposes → State
```

`logical_component.payload.function_id`、`interface.payload.connected_component_ids` 和 `state.payload.owner_id` 只能引用当前上下文中的 canonical ID 或本 Proposal 的 local_ref。跨批次 Function/Requirement 不得被新对象或关系引用。

## 验收

1. 三条 Requirement 的 Logical 结构化运行产生三个 singleton L 请求。
2. 每个请求的上下文只暴露当前 Requirement 及其 Function 追溯邻居。
3. 合并图保留每个 Function→LogicalComponent 分配，以及 Interface/State 的 typed 归属关系。
4. 现有本地测试和端到端 SysML round-trip 继续通过；不启动本机模型。
