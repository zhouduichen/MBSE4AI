# LLM 配置闭环设计

## 目标

让本地工作台的 LLM 配置从“保存档案”变成可验证、可切换、可追踪的运行闭环，同时支持 OpenAI-compatible 服务和 Ollama 本地/远程服务。

## 范围

- 配置档案明确声明 provider：openai-compatible 或 ollama。
- 设置页提供常用服务预设、完整编辑表单、保存、激活、删除和真实连接测试。
- OpenAI-compatible 使用 /chat/completions；Ollama 使用原生 /api/chat。
- 连接测试使用最小真实对话请求，验证地址、认证、模型和响应结构。
- 分析开始时按当前 active profile 选择运行时；运行台账继续记录 profile、provider、model。
- 配置错误、网络错误、认证错误和模型响应错误以脱敏的结构化信息返回页面。
- API Key 继续只保存到系统 Keyring 或进程会话，不进入配置 JSON、HTML 或 API 响应。

不在本轮范围内：流式输出、模型列表自动同步、多个模型并行路由、云端配置同步、完整 SysML 建模器。

## 现状问题

LLMProfileService 已具备档案原子写入、激活和 Keyring/会话密钥隔离；RuntimeFactory 也会在每次分析开始时读取 active config。但 Web 表单没有 provider/预设选择，连接测试只探测模型列表，页面缺少编辑/删除和明确的真实运行反馈，导致用户无法确认配置是否真的能完成一次结构化分析。

## 方案

### 配置模型

保留现有字段并增加稳定的 provider：

    id, label, provider, kind, protocol, base_url, model,
    timeout_seconds, enabled, api_key

provider 的允许值只有 openai-compatible 和 ollama。旧档案没有 provider 时按现有 kind 与 Base URL 兼容推断，并在读取时返回规范化值，避免破坏已有配置。

预设只填充表单默认值，不会自动保存或发送 Key：

- OpenAI：https://api.openai.com/v1
- DeepSeek：https://api.deepseek.com
- 通义：DashScope compatible endpoint
- Ollama 本地：http://127.0.0.1:11434
- Ollama 远程：用户填写地址
- 自定义：用户填写 provider、地址和模型

### 服务端流程

1. normalize_profile 校验 provider、URL、模型和超时；旧配置补齐 provider。
2. save 原子更新 JSON；非空 Key 写入 Keyring/会话，空 Key 对已有档案保持不变。
3. activate 只改变 active_id，不重启 Web 进程。
4. test 根据 provider 发送最小结构化对话：
   - OpenAI-compatible：POST {base_url}/chat/completions，Bearer Key 可选但远程服务无 Key 时先返回 not_configured。
   - Ollama：POST {host}/api/chat，stream=false、think=false，不要求 Key。
5. 测试响应只返回连接状态、HTTP 状态、provider、model 和脱敏错误，不返回响应全文或 Key。
6. RuntimeFactory.select 使用 active config 产生实际运行时；运行前把 selection 元数据写入 Run/Step，运行失败保留可读诊断。

### Web 入口

设置页包含：

- provider 选择和预设按钮；
- ID、名称、Base URL、模型、超时、Key、启用状态；
- 保存配置、激活、删除、测试连接；
- 当前活动配置和最近测试结果。

编辑已有档案时 Key 留空表示保留旧 Key；删除需要页面确认，服务端只删除指定档案并在删除活动档案时选择剩余档案或清空 active_id。

### 错误处理

- 参数错误：422，指出具体字段。
- 远程档案无 Key：测试返回 not_configured，不发网络请求。
- HTTP 401/403：返回 authentication_failed，不暴露响应体。
- 连接超时/DNS/拒绝：返回 unreachable。
- 非 JSON 或不符合最小响应结构：返回 invalid_response。
- 分析过程中 LLM 失败：Run 为 degraded，Step diagnostics 记录 provider、model 和脱敏原因；不伪装为成功。

## 测试与验收

- 单元测试覆盖旧配置兼容、provider 规范化、Key 保留、删除活动配置。
- HTTP mock 测试覆盖 OpenAI-compatible 和 Ollama 的 URL、认证、请求体、超时、错误映射。
- Web API 测试覆盖预设、保存、激活、删除、测试响应不泄露 Key。
- 运行时测试覆盖激活配置被下一次分析读取，并在 Run/Step 元数据中出现。
- 浏览器验收覆盖：选择预设、保存、激活、测试、错误提示和当前活动配置展示。
- 保留现有全量测试、Ruff、compileall、import-linter 和架构预算检查。

## 安全与兼容性

- 默认服务仍只监听本机；不新增外部服务。
- 不读取或展示 Keyring 内容；任何错误信息都经过脱敏。
- 不迁移、不删除既有工作区；旧 profile JSON 可继续读取。
