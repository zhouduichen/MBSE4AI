# Web 单次生成 LLM Profile 选择设计

## 目标

让 AI4MBSE Web Analysis 工作台在一次生成请求中选择已保存的 LLM Profile，而不改变全局 active Profile。这样用户可以明确把一次纵向 R→F→L→P→V&V 生成指向远程 SSH/Tailscale 模型，同时保留全局配置的稳定性。

## 范围

- Analysis 页面显示已保存 Profile 的非敏感摘要，并默认选择 active Profile。
- `/projects/{project_id}/analysis` 接受可选 `profile_id`，生成、单阶段调试和 pipeline 均使用该 Profile。
- Profile 不存在、无效或已停用时沿现有 API 错误边界返回失败，不执行模型调用。
- 实际使用的 Profile/provider/model 继续写入 Run 和响应元数据。

## 设计

`V2Services.generation()` 和 `V2Services.analysis()` 增加可选 `profile_id`。当请求提供该值时，通过 `SettingsService` 的 Profile 服务读取已保存配置和系统/会话凭据；否则保留现有显式 runtime config、active Profile、离线 RuleRuntime 的优先级。该选择只存在于本次服务对象，不写回 `active_id`。

Resource API 从 JSON 读取 `profile_id`，将它传入对应服务，并保持 deliverable、traceability 和 runtime metadata 的现有绑定。页面从 Profile snapshot 构造无密钥的选择项，JavaScript 在生成/phase 请求中发送选中的 ID；不选择时发送空值，让后端使用 active Profile。

## 错误与安全

- 页面和 API 响应只使用 Profile 的 `id`、`label`、`kind`、`provider`、`model`、enabled 状态；不序列化 API Key。
- 选择已停用或不存在的 Profile 在 runtime selection 前失败，不能静默回退到 active Profile。
- 默认行为完全兼容：无 `profile_id` 的调用仍使用原有运行时选择逻辑。

## 验证

- 应用服务测试证明单次 Profile 优先于 active Profile，且 active ID 不变。
- Web API 测试证明请求 Profile 出现在 run metadata，页面包含选择器和发送参数。
- 运行 Web/CLI focused tests、完整 pytest、compileall、Ruff、架构指标和 import-linter；测试使用 `VerticalRuleRuntime`，不启动或调用本机模型。
