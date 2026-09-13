# Review 后继续生成设计

## 目标

把“AI 生成 → 用户 Review → 继续向下推理”做成一个真实的产品闭环。用户在 ModelGraph 工作台接受或编辑一个实体后，可以明确点击“继续生成下游”；系统从该实体之后的第一个受影响产品阶段运行至 V&V，并把新结果写回同一个 ModelGraph。

## 用户体验

用户只看到一个面向工程层的动作：

```text
Review 实体
  ↓
接受 / 编辑 / 锁定
  ↓
继续生成下游
  ↓
显示运行状态、受影响阶段、追溯结果和新的 Review 项
```

“继续生成下游”是显式动作，不在 Accept/Lock 请求中自动启动长时间 LLM 调用。按钮只出现在有下游阶段的实体上：Requirements/Functional/Logical/Physical 实体可以继续，V&V 实体没有后续生成阶段，只显示重新分析和质量结果。用户编辑后必须先接受，才能继续；被锁定的实体可以作为只读基准参与下游推理，但不会被修改。

## 服务契约

`ModelGenerationService.continue_generation(project_id, entity_id, expected_revision=None, controller_decision=None)` 是唯一应用入口。

1. 读取当前 ModelGraph 并执行 CAS revision 检查。
2. 要求实体状态为 `accepted` 或 `locked`；`candidate`、`rejected` 和 `deprecated` 返回可读的契约错误。
3. 用 `MethodologyEngine.analyze(graph, changed_entity_ids=(entity_id,))` 计算影响路径和阶段。
4. 从实体所属阶段的下一个 `VerticalStage` 开始执行，直至 V&V；不会重复生成已被用户确认的实体所属阶段。
5. 仍通过现有 `TaskExecutor → validators → Patch → Repository CAS` 链写入，LLM/规则 Runtime 只能新增实体、关系或更新未锁定实体；锁定实体的更新由 identity validator 和 ModelGraph 双重拒绝。
6. 返回 `execution_status`、`selected_stages`、`trigger_entity_id`、`trigger_revision`、阶段结果、Methodology、Controller 和 Traceability。没有下游阶段时返回 `no_downstream_work`，不创建空 Patch。

继续生成使用独立的 `vertical_continuation` Run，并记录 `model_generation.continuation.started`、阶段完成/失败和 `model_generation.continuation.completed` 审计事件。原有 `reanalyze` 请求/执行入口保持兼容，用于需要重跑当前阶段的诊断场景。

## 阶段路由

| 已确认实体层 | 继续运行 |
|---|---|
| System Definition / Requirement | Functional → Logical → Physical → V&V |
| Functional | Logical → Physical → V&V |
| Logical | Physical → V&V |
| Physical | V&V |
| V&V | 无下游阶段，返回 `no_downstream_work` |

同一层中不同 EntityKind 的路由由 `EntityKind` 的产品阶段映射统一定义；不根据实体名称猜测阶段。

## Web 入口

ModelGraph 分层工作台在每个可继续实体卡片上显示“继续生成下游”。按钮携带当前页面 revision 和实体 ID，调用：

```http
POST /projects/{project_id}/entities/{entity_id}/continue
{
  "expected_revision": 12
}
```

成功后刷新页面，显示最新阶段状态和 Review 项；409/422 错误在工作台反馈区显示，页面不做乐观更新。锁定实体仍允许继续按钮，但页面明确标示“基于锁定实体生成下游”。

## 不变量与错误处理

- 继续生成不会改变触发实体的 ID、状态、payload 或 `updated_revision`。
- 任一阶段结构、引用、写权限或 CAS 失败，Run 标记失败；已成功提交的前序阶段保留，后续阶段不运行。
- semantic-invalid 输出仍保存为 candidate 并进入 Review，不计入完整追溯。
- 下游生成不能更新 `locked` 或 `user_modified` 实体；发生此类提案时整阶段拒绝并保留诊断。
- 每次继续生成都是新的 Run/Revision/审计记录，历史生成结果不被覆盖。

## 验收

1. 离线完整模型中接受 Function 后，继续生成只运行 Logical、Physical、V&V，触发 Function 的状态和 ID 不变。
2. 锁定 Function 后继续生成仍能产生下游结果，但任何更新该 Function 的提案均被拒绝。
3. candidate Function 不能直接继续，接受后才可以继续。
4. Web 页面展示继续按钮，API 返回 selected stages 和 continuation Run 信息。
5. V&V 实体返回 `no_downstream_work` 且不新增 Revision。
6. 完整测试、compileall、Ruff、架构预算和 import-linter 通过。

## 范围边界

本切片不改 ModelGraph 元模型、不新增数据库表、不替换现有五阶段 Runtime、不自动选择 Trade Study 方案，也不把内部 TaskSpec/Patch/CAS 暴露给用户。多实体批量继续、后台异步队列和真实仿真工具接入留给后续产品迭代。
