# 概念布局到 CAD 详细设计上下文设计

## 背景

概念布局候选应用后会形成带来源 Requirement 的 `PhysicalBlock`，但 CAD 意图解析只保存 `source_requirement_ids`，`DesignIntent.context_model_ids` 和 `CadExecutionPlan.model_context_ids` 一直为空。这样 2.1 产生的布局事实无法进入 3.1 的结构设计计划和最终回写模型。

## 设计

创建 CAD 意图时，应用层从当前 ModelGraph 选择与来源根 Requirement 相交的非弃用 `PhysicalBlock`，将其稳定 ID 写入 `context_model_ids`。没有显式来源时仍使用根 Requirement；只有存在来源交集的物理模型才会作为上下文，不把无关候选注入设计意图。

该字段沿以下边界保持不变：

`PhysicalBlock` → `DesignIntent.context_model_ids` → `CadExecutionPlan.model_context_ids` → 执行模型 payload → 回写 `PhysicalBlock` 的 `design_intent`/`context_model_ids`。

上下文只提供已存在的工程事实，不自动批准概念候选，也不改变“预览 → 审批 → 执行”门；CAD 结构选型、标注和 DFM/DFA 审查仍需人工复核。

## 验收边界

离线验收先生成并应用 2.1 候选，再创建自然语言 CAD 意图，确认上下文 ID 出现在意图、计划和最终 ModelGraph 实体中，并继续验证参数化模型、标注和 DFM/DFA 审查。测试不启动 LLM、服务器、SSH 或 FreeCAD。
