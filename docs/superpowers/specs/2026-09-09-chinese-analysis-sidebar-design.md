# AI4MBSE 中文工作台与分析侧栏设计

## 目标

将 AI4MBSE 的产品界面统一为简体中文，并把“利益相关方、生命周期、场景与用例、需求、功能、逻辑/物理、验证、证据与问题、运行记录”整理为分析页左侧可点击卡片。点击卡片后，当前页面主区域切换到对应详情，不跳转页面。

## 范围与边界

- 面向用户的网页标题、导航、按钮、状态、提示、表头、空状态和错误文本使用中文。
- CLI 的人类可读提示使用中文；JSON API 的字段名、枚举值、URL、实体 kind、任务 ID 和内部审计标识保持不变。
- 保留现有生命周期运行、Gate、修复、模型追踪、设置和删除接口，不改变 API 请求/响应结构。
- 侧栏卡片使用当前模型图和运行台账中的真实数据，显示实体数量、问题数量或运行状态。
- 首次打开分析页默认选择“利益相关方”；选择状态通过 `aria-selected` 和视觉样式表达，并支持键盘焦点。

## 页面结构

分析页结构调整为：

1. 页面标题、当前修订、活动模型和 Global Gate 概览。
2. 生命周期阶段轨道及运行操作。
3. `analysis-layout` 两列区域：左侧 `analysis-sidebar` 为模块卡片，右侧 `analysis-detail` 为详情面板。
4. 每个详情面板仅由前端切换显示，不重新请求页面；各模块保留实体、状态、关联和可执行入口。

模块与实体类型映射如下：

| 模块 | 实体类型 |
| --- | --- |
| 利益相关方 | stakeholder、concern |
| 生命周期 | lifecycle_stage、lifecycle_transition |
| 场景与用例 | scenario_hypothesis、use_case、operational_scenario、activity |
| 需求分析 | requirement |
| 功能分析 | function、functional_flow、functional_scenario |
| 逻辑/物理架构 | logical_component、physical_block、interface、state |
| 验证与确认 | verification_case、validation_case、hazard、failure_mode |
| 证据与问题 | evidence、Gate issues |
| 运行与审计 | current task、run ledger、repair、closure |

## 数据流与实现

`build_analysis_view()` 继续负责页面视图组装，并新增稳定的 `analysis_modules` 列表。每个模块包含 `id`、中文 `title`、`description`、`count`、`status` 和经过 `_plain()` 处理的实体摘要。模板用该列表生成侧栏卡片和详情面板，使用模块 `id` 进行配对。

状态、实体类型、Gate、任务和运行状态通过页面层的中文映射显示；原始值仍保留在 API 与视图的机器字段中。前端脚本仅负责切换 `hidden`、`aria-selected` 和当前卡片样式，不复制业务逻辑。

## 错误处理

空模块显示“暂无记录”，不视为错误。分析、修复或连接测试失败时，用户看到中文错误提示，同时保留原始 JSON 结果供诊断；敏感凭据继续不进入页面或 API 响应。

## 验收标准

- 所有主要网页页面不再出现面向用户的英文导航、标题、按钮、状态、表头或错误提示。
- 分析页左侧至少显示上述九个中文模块卡片；点击任意卡片后，右侧只显示对应详情。
- 卡片数量和详情内容来自当前项目真实模型/运行数据；空项目也能正常打开。
- 现有 Web、工作流、CLI 和打包测试继续通过。
