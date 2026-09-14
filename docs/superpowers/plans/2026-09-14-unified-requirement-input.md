# 统一需求输入与多需求追溯实施计划

## 目标

消除 `generate` 与 `pipeline` 的需求输入分叉，让多来源输入在同一份 ModelGraph 中形成稳定、可追溯且可继续编辑的 Requirement 节点。

## 实施步骤

- [x] 审计两套输入实现和现有多需求验收。
- [x] 为 RequirementInputService 增加文本+文档组合入口和 provenance 合并。
- [x] 为 ModelGraph UpdateEntity 增加 source_ids 元数据更新。
- [x] 让 ModelGenerationService 委托共享输入服务。
- [x] 增加混合来源、多需求完整链和幂等回归测试。
- [x] 运行完整质量门禁并提交推送。
