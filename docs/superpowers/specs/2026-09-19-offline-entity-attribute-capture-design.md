# 离线需求实体与属性捕获设计

## 背景

需求摄取的结构化 LLM Schema 已允许 `entities[].attributes`，但默认离线 fallback 只生成一个“操作员”实体，`system_context` 也只有名称和任务文字，系统类型、运行环境和关注点没有进入 ModelGraph。这使文档输入虽然能形成 Requirement 和行为框架，却不能证明实体/属性捕获闭环。

## 目标

1. 从有限词典中识别常见系统平台、利益相关方和工程关注点。
2. 将系统类型、任务域、运行环境和捕获方式保存为 `system_context.attributes`，并编译进 System payload。
3. 为 stakeholder/concern 实体保留稳定 local_ref、属性、来源区域和低置信度。
4. 扩展结构化 LLM Schema，使远程模型输出的 system attributes 不被拒绝或丢弃。
5. 不进行开放域实体猜测；未命中的信息继续保留在原文和 clarification 中。

## 方案

使用版本化、可审计的词典规则：平台词典识别 `无人配送机器人`、`机器人`、`无人机`、`飞行器`、`车辆`、`传感器系统`；利益相关方词典识别操作员、指挥员、维护人员、管理员、用户和安全监管方；关注点词典识别安全、可靠性、可维护性、性能和互操作性。规则输出使用 `source=derived`、低置信度和 `rule:*` diagnostics，LLM 输出继续按自身 confidence/source 进入候选 Review。

## 验收

- 离线输入“校园无人配送机器人由操作员使用，维护人员负责维护，系统应故障安全并支持持续运行”能生成系统属性、至少两个 stakeholder 和安全/可靠性关注点。
- 每个派生实体保留 source_refs、attributes 和低置信度，且应用后可在 ModelGraph 中读取。
- 结构化 LLM payload 的 `system_context.attributes` 通过 schema、compiler 和 SysML/交付包往返。
- 原有 Requirement、Use Case、Scenario、RFLP、CAD 审查和全量离线验证不回归。
