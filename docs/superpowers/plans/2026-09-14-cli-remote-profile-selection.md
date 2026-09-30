# 单次纵向生成选择 LLM Profile

**目标：** 让 `analyze generate` 在不改变全局 active profile 的情况下，显式选择一个已保存的 LLM Profile，便于使用远程 SSH/Tailscale 模型完成真实五阶段验收。

## 最小设计

1. `LLMProfileService` 按 profile ID 解析已保存配置，并复用现有 keyring/session credential 读取逻辑。
2. `ai4mbse analyze generate --profile <id>` 将该配置作为本次服务实例的显式 runtime config；显式配置优先于 active profile，但不写回 active ID。
3. 离线规则 Runtime、Web 配置流程和旧的 23-task `analyze run` 保持兼容；不新增模型探测、重试状态机或 benchmark 逻辑。

## 验收

- CLI 测试证明选择的 profile 写入 run ledger，active profile 保持不变。
- 未提供 `--profile` 的既有离线 CLI 行为不变。
- 运行 compile、focused tests、完整离线质量门禁；不启动或调用本机模型。
