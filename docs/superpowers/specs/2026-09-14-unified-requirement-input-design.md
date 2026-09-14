# 统一需求输入与多需求追溯设计

## 目标

让面向用户的五阶段 `generate` 入口和完整 `pipeline` 入口共享同一套需求输入语义：文本、文档区域和已有需求进入同一份 Typed ModelGraph，重复语句不复制节点，但会合并所有可用的来源/证据 ID；之后每条输入需求都独立参与 R→F→L→P→V&V 追溯。

## 当前问题

`RequirementInputService` 已被 `mode=pipeline` 使用，但 `ModelGenerationService` 仍有一份独立的 `_ensure_input` 实现。两者的分句、文档读取、去重和 patch 原因不一致；同一句需求先由文本输入、后由文档输入时，已有 Requirement 也不会补上文档 Source Region 的 provenance。

这不是新的状态机或模型安全层问题，而是产品主入口的语义分叉：同样的用户输入可能得到不同的 Requirement 图，LLM 后续上下文也会不同。

## 方案

1. 扩展 `RequirementInputService` 一个组合入口，统一收集可选文本和文档区域，再按规范化 statement 去重。
2. `ensure_text_requirements` 和 `ensure_document_requirements` 继续保留，作为组合入口的薄封装，兼容现有调用方。
3. 生成入口 `_ensure_input` 只负责输入门禁，实际创建/复用 Requirement 委托给组合入口；文本与文档同时存在时合并，而不是静默丢弃一类来源。
4. 已存在的 Requirement 只在出现新 source/evidence ID 时生成 `UpdateEntity`，保持 canonical entity ID 不变；不覆盖已有 payload、状态或用户修改。
5. 为 `UpdateEntity` 增加 `source_ids` 的受限元数据更新能力，使 provenance 合并仍通过普通 CAS Revision 完成。

## 不变约束

- 不调用本地模型，不启动 Ollama，也不改变远程 Provider 选择。
- ModelGraph 仍是唯一真源；输入服务不直接修改数据库表，只提交 Patch。
- 文本需求不伪造文档来源；文档区域 ID 同时进入 Requirement 的 `source_ids`/`evidence_ids`。
- 语义相同的需求保持一个稳定节点；不同句子保持独立节点。
- 现有五阶段、23-task、SysML 和交付包行为保持兼容。

## 验收

1. 文本入口与文档入口对同一 statement 复用同一个 Requirement ID。
2. 同一 statement 的文本来源和多个 document region 来源合并到同一节点，且重复调用不新增 Revision 或重复 ID。
3. 五阶段离线产品路径对三条自然语言需求创建三条独立 Function/Logical/Physical/V&V 追溯，端到端完整数等于三。
4. 文本+文档组合输入同时保留两类来源，后续上下文可读取统一后的 Requirement。

