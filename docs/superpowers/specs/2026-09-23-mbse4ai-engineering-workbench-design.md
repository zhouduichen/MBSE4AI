# MBSE4AI 工程工作台重构设计

## 目标

在不改变 ModelGraph、API、CAS Revision、Gate / Repair、Traceability、Controller、V&V、Concept Design、CAD 和 Deliverables 语义的前提下，把 Web UI 从功能页面集合重构为以系统工程生命周期、工程对象状态和验证闭环为核心的统一工作台。

用户在任意核心页面都能回答：当前处于哪个流程阶段、模型缺什么或为什么被阻塞、下一步该执行什么工程动作。

## 方案选择

采用 Web 层的 workflow projection 编排方案。导航、项目总览和工程流程页消费同一份只读生命周期投影；投影从当前 ModelGraph、现有 Gate、Issue、最近 Run、Closure 和 Traceability 计算，不新增第二套持久化事实或领域状态机。

不采用仅改 CSS 的方案，因为阶段状态和下一步动作仍会分散在多个模板；也不改造领域层生命周期模型，因为会扩大到现有核心能力和 API 兼容边界。

## 信息架构

一级导航固定为：

1. 项目总览：当前项目的生命周期位置、模型健康度、追溯覆盖和下一步动作。
2. 工程流程：输入、R/F/L/P、V&V、Closure 的统一执行面。
3. 模型工作台：ModelGraph 分层、需求、RFLP、行为/接口、概念设计和 CAD 的 View 入口。
4. 验证与问题：Traceability、V&V、Gate、Evidence、Repair 和 Controller 的问题闭环。
5. 历史与基线：Revision、Run、Patch、Closure manifest、Deliverables 和 Diff。
6. 设置：模型 Profile 与运行时配置。

原有 URL 和模板保留，作为深度审查和兼容入口；它们不再在侧栏中平铺。聚合页通过上下文卡片进入这些既有能力。

## 生命周期投影

统一顶部生命周期为：

`输入 → R → F → L → P → V&V → Closure`

阶段状态采用用户可理解的稳定词汇：

- 未开始：尚未接入输入或尚未形成该阶段所需对象。
- 可执行：前置条件满足，可以执行阶段动作。
- 执行中：存在当前阶段的活动 Run。
- 已阻塞：Gate、缺失对象、Issue 或前置阶段阻止继续。
- 需复核：已有结果但存在降级、语义失败或审查项。
- 已通过：阶段对象和对应质量门禁满足当前阶段条件。
- 已闭环：Release Closure 完成并冻结当前 revision。

R/F/L/P/V&V 映射到现有的 Requirements、Functional、Logical/Physical 和 Assurance 投影；L 与 P 在 UI 上拆开，但继续复用同一个现有 P-Gate 与 ModelGraph 事实。Closure 使用现有 Release Closure 和 ClosureService 结果，不创建新的封版实现。

每个阶段输出：状态、对象数量、覆盖摘要、阻塞原因、关联 Gate、下一步动作和深度工作台链接。输入阶段链接现有 Analysis intake；执行动作复用现有 Analysis / Engineering Flow API；问题动作复用现有 Controller、Repair、Evidence 和 V&V API。

## 页面设计

### 项目总览

页面顶部展示当前项目、revision、快照 hash、最近运行和全局质量门禁。主区域展示生命周期 rail、当前工作焦点、追溯覆盖、未解决问题和最近审计。空项目明确引导补充输入，未通过项目明确展示阻塞原因和修复入口。

### 工程流程

保留现有统一输入表单和 Concept/CAD 可选编排能力，顶部改为生命周期 rail；下方显示当前阶段详情、工程动作、追溯闭环、问题与 Closure 状态。Analysis 的细粒度运行台账继续保留为“高级诊断”或深度工作台入口。

### 模型工作台

以 ModelGraph 分层和 Requirement → Function → Logical → Physical → V&V 追溯为主视图，提供现有 Requirements、RFLP、Behavior、Concept Design、CAD 和 Deliverables 入口，不复制这些能力。

### 验证与问题

聚合 Global/P/F/O Gate、Traceability gap、V&V 执行证据、Evidence 和 Controller/Repair action；原 Assurance 和 Evidence 页面继续保留为详情入口。

### 历史与基线

聚合当前 revision、Closure 状态、最近 Run、Revision diff 和导出交付物。现有 immutable ledger 语义保持不变。

## 兼容性与错误处理

- 不修改 ModelGraph 写入路径、API schema、CAS、Revision、Gate、Repair 或 Deliverables 生成逻辑。
- 所有聚合视图为只读计算；任何写操作仍通过已有 Application Service/API。
- 图为空、没有输入、没有 Run、Gate 失败、Closure 被阻塞和执行失败都渲染为明确的空态/阻塞态，不假设已有结果。
- 旧页面的 `active` 状态改为归属到新的一级导航，但旧 URL 仍可直接访问。

## 验证

新增 projection 测试覆盖空项目、可执行阶段、Gate 阻塞、运行中、通过、Closure 闭环和下一步动作；页面测试覆盖六项一级导航、生命周期文案、聚合 View 链接和旧能力 URL 保持可访问。运行现有 Web 测试、E2E、Ruff、compileall，并进行一次浏览器级页面渲染检查。
