# 概念布局到 CAD 上下文实施计划

## 目标

让 2.1 生成的概念 `PhysicalBlock` 成为 3.1 CAD 意图和执行计划的真实输入上下文。

## 步骤

1. 扩展结构化设计意图契约，持久化 `context_model_ids`。
2. 从当前 ModelGraph 按来源 Requirement 选择相关非弃用 PhysicalBlock。
3. 将上下文 ID 传入 CAD 计划、执行模型和 ModelGraph 回写。
4. 增加概念候选到 CAD 的离线端到端验收，并保持原有 clarification/审批门。
5. 运行全量门禁，更新文档，提交并推送。

## 非目标

本次不调用真实 CAD 后端、不自动批准布局、不改变远程 FreeCAD 配置，也不把开发证据提升为正式工程结论。
