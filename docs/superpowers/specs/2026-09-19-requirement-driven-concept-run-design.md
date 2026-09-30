# 需求驱动概念布局运行入口设计

## 背景

总体设计页已经能够从 ModelGraph 生成指标包络建议，但页面初始值仍是固定翼示例。用户可能在需求缺少工程输入时直接运行，系统因此把示例值误当成当前项目输入，破坏“缺失即需确认”的工程语义。

## 设计

保留已有的显式 `envelope` 运行契约，同时为 `POST /projects/{project_id}/concept-design/run` 增加 `from_requirements: true` 路径：

1. 服务从当前根 Requirement 调用 `suggest_input()`；
2. `status=ready` 时使用建议 envelope 运行 2.1/2.2；
3. `status=needs_input` 时返回完整的输入建议、缺失参数、边界和证据，不启动布局或评估；
4. 页面不再预填固定翼数值，需求驱动按钮只能使用当前 ModelGraph 的事实；设计师仍可编辑 envelope 后显式运行。

显式 envelope 与需求驱动路径都保留 `source_requirement_ids`，概念候选、学科评估和应用到 ModelGraph 的 PhysicalBlock 继续沿同一来源链追溯。

## 验收边界

API 和产品验收覆盖：完整固定翼需求文档 → R→F→L→P→V&V → 需求驱动指标 envelope → 3–5 套候选 → 三学科评估；缺少参数的需求只能返回 `needs_input`。测试使用 `VerticalRuleRuntime` 和 preview 路径，不启动 LLM、服务器、SSH 或 FreeCAD。
