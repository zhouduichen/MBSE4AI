# 1.2 行为模型需求反查投影设计

## 目标

让需求分析阶段形成的 ModelGraph 关系可以在行为工作台、行为 API 和工程交付包中被直接回读：用户能够从 Use Case、Operational Scenario、Activity 和 Sequence Diagram 看见其来源需求，并通过稳定的实体 ID 回到通用模型工作台继续编辑。

本次只修复投影可见性，不改变 ModelGraph 的实体、关系谓词或写入路径。当前离线纵向生成已经写入 `Requirement -> UseCase/Activity/OperationalScenario` 的 `derivedFrom` 关系；缺口是行为投影只选择行为实体，导致这些关系在 `/behavior` 和 `behavior.json` 中不可见。

## 范围与不变项

### 范围内

- 行为投影的关系集合包含 Requirement 端点，但仍只把行为实体放入现有 `records` 分组。
- Use Case、Operational Scenario、Activity 和 sequence diagram 返回规范化的 `requirement_ids`。
- 行为页面显示 Use Case 和 Scenario 的关联需求 ID，保留现有编辑入口和确定性 Mermaid 投影。
- 增加 API、交付包和行为投影测试，证明需求关系不会只停留在 payload 中。

### 不变项

- 不新增关系谓词；继续使用现有 `derivedFrom`。
- 不改变关系存储结构、ModelGraph CAS、需求编译器或生成器的写入语义。
- 不启动任何服务器、SSH、FreeCAD 或 LLM；验证只使用 `VerticalRuleRuntime` 和测试客户端。
- 不把推断出的关系当作新的语义来源；关联需求只从已写入的图关系汇总，payload 仅作为兼容回退。

## 投影契约

行为投影保留现有顶层结构，并增加以下字段：

- `use_cases[*].requirement_ids`: 该 Use Case 的入边中，来源实体为 Requirement 且谓词为 `derivedFrom` 的 ID，按稳定顺序去重。
- `scenarios[*].requirement_ids`: 该 Operational Scenario 的同类需求来源 ID。
- `sequence_diagrams[*].requirement_ids`: 对应 Scenario 的同一组需求 ID。
- `relations[*]`: 允许 Requirement 与行为实体作为端点；每条记录继续返回 `id/source/target/predicate/evidence_count`，不改变已有字段。

若历史模型缺少显式关系，则从对应行为实体的 `requirement_ids` payload 读取兼容回退；回退结果只用于展示，不写回图。这样旧交付物仍可读，新生成结果则由显式关系证明。

## 数据流

```text
ModelGraph relations + behavior payload fallback
        |
        v
build_behavior_view
        |
        +--> /projects/{id}/behavior
        +--> behavior.html
        +--> deliverables.build(...)["artifacts"]["behavior"]
```

页面只展示 ID 和名称等已有投影字段，不复制一份可变行为模型。编辑仍通过通用 Model Workbench 的实体编辑接口完成；下一次读取行为投影时，新的实体 payload 和关系会自动反映出来。

## 验收标准

给定一份离线生成的多需求输入：

1. ModelGraph 中已有的 Requirement→UseCase/Activity 关系出现在行为 API 的 `relations` 中。
2. 每个返回的 Use Case 至少能反查一个来源需求；对应 Scenario 和 Sequence Diagram 返回相同的需求 ID 集合。
3. UI 页面包含关联需求 ID，且仍包含可编辑实体 ID 和 Mermaid sequence diagram。
4. 工程交付包中的 `behavior` artifact 与实时 `build_behavior_view` 一致，并保留这些关系。
5. 删除/缺失行为关系时，投影不会伪造新图关系；兼容 payload 回退只影响读取结果。

