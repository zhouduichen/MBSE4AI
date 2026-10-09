# F 阶段按需求窄批次设计

**日期：** 2026-09-20  
**状态：** 已确认进入实现  
**目标版本：** rflp-lite 0.3.0

## 目标

在已经具备 R 阶段窄切片的基础上，把 `vertical.functional` 变成一条真实、可合并、可追溯的 F 阶段纵向链。每个正式 Requirement 使用一个独立 Provider 请求生成其功能行为，再合并为一个阶段 Patch，供后续 Logical 阶段消费。

本切片必须生成真实的 `Function`，并在有足够上下文时生成 `FunctionalFlow` 与 `FunctionalScenario`。每个 Function 必须通过 `Requirement → satisfiedBy → Function` 回接；Function 的 payload 保留 `source_requirement_ids`，使后续 L/P/V&V 能够按需求继续追踪。

## 范围与非目标

本轮只修改产品级 `vertical.functional` Runtime、Prompt/批次上下文和相关测试。不重写 ModelGraph、Compiler、CAS、SysML 导出或 R 阶段；不启动本机模型，不增加多轮稳定性实验。

## 设计

### 1. 单 Requirement 批次

Functional 阶段不再默认把两个 Requirement 放进同一次请求。Runtime 为每个活动 Requirement 创建一个 `requirement_batch`：

```json
{
  "index": 1,
  "count": 5,
  "is_first": true,
  "requirement_ids": ["requirement-..."]
}
```

请求仍保留当前 System、该 Requirement、其当前功能追踪字段和一跳关系邻居；其它 Requirement 不进入上下文。批次请求可以并行，但只有所有批次返回后才合并和提交阶段 Patch。

### 2. F 输出契约

每个批次最多生成一组当前需求的 Function/Flow/Scenario 对象。允许的实体仅为：

- `function`：必须包含行为性的 `decomposition`，并携带 `source_requirement_ids=[当前 Requirement]`；
- `functional_flow`：必须包含 `source_function_ids` 和 `target_function_ids`，单功能场景使用显式自循环；
- `functional_scenario`：必须包含 `function_ids` 和短步骤；

关系只允许 `satisfiedBy`、`decomposes`、`derivedFrom`、`exchangesWith`。跨批次 Requirement 的实体、更新和关系不允许进入当前 Proposal。已有未锁定派生实体可以通过受限 `updates` 复用；锁定或人工修改实体只能作为只读上下文。

### 3. 合并边界

每个批次先经过现有结构化响应解析、Proposal Compiler 和关系端点校验。Runtime 按确定性 Requirement 顺序合并 Proposal：

1. 相同操作键的关系去重；
2. 不同批次修改同一字段时报确定性冲突；
3. 所有批次成功后才产生一个以原始 revision 为 expected revision 的 Patch；
4. 任一批次失败时不提交部分 F 结果，F 之后的 L/P/V&V 不得被标记为已完成。

### 4. Prompt 与追溯

F Prompt 明确告诉模型当前唯一 Requirement、批次边界和可见 canonical ID。要求先生成可观察系统行为，再补功能流/功能场景；禁止把传感器、芯片、数据库或物理零件直接当作 Function。若无法确定，写入 `open_questions`，而不是生成无来源的占位实体。

## 验收标准

1. 五条 Requirement 产生五个独立 Functional 请求，每个请求只携带一个 Requirement。
2. 本地结构化夹具能够形成 Function、FunctionalFlow、FunctionalScenario 和 `satisfiedBy` 关系。
3. 合并后的 Patch 保持单一 CAS 边界，Requirement 与 Function 的 `source_requirement_ids` 一致。
4. 任一批次失败时没有部分 Patch，诊断包含批次 index/total，后续阶段保持 queued/未完成。
5. 既有 Logical、Physical、V&V 批处理及全量本地测试保持通过。
6. 真实远端 Provider 只在本地门禁通过后运行一次；失败时保留真实证据，不使用 completion bridge 冒充成功。

