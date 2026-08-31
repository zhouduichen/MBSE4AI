# Windows 5080 Ollama 远程推理设计

## 目标

让 macOS 上运行的 AI4MBSE 通过现有 Tailscale 私有网络调用 Windows 工作站上的 Ollama，把 LLM 推理交给 RTX 5080。连接应在配置一次后长期可用，不要求用户每次手动建立 SSH 隧道，也不把 Ollama 暴露到普通局域网或公网。

远端已确认状态：

- SSH 别名：`autoresearch-5080`
- Tailscale 主机名：`autoresearch-5080.tail2530b8.ts.net`
- Ollama 地址：Windows 本机 `127.0.0.1:11434`
- 模型：`qwen3.5:9b-q8_0`
- Tailscale Serve 已运行，当前仅向 tailnet 提供既有服务

## 方案选择

采用 Tailscale Serve 把 tailnet 内的 TCP 端口 `11434` 转发到 Windows 本机 Ollama。初始 HTTPS/HTTP 代理在该 tailnet 的 11434 端口返回 403，因此最终使用原始 TCP 转发；Tailscale 链路仍由 WireGuard 加密，Ollama 继续只监听回环地址：

```text
AI4MBSE
  -> http://100.88.143.10:11434
  -> Tailscale Serve
  -> http://127.0.0.1:11434
  -> Ollama / qwen3.5:9b-q8_0 / RTX 5080
```

不采用以下方案：

- 手动 SSH 本地端口转发：安全且改动少，但每次重启或连接中断后需要维护隧道。
- 将 Ollama 绑定到 `0.0.0.0`：调用路径短，但会扩大普通局域网暴露面。
- 在 AI4MBSE 内实现 SSH 生命周期管理：会引入密钥、进程和重连状态管理，超出本次需求。

## 组件与配置

### Windows Tailscale Serve

在不修改 Ollama 监听地址的前提下，新增一个后台 TCP 转发：

```powershell
tailscale serve --bg --tcp=11434 127.0.0.1:11434
```

该转发只在 tailnet 内可见。使用 Tailscale IP 而不是 MagicDNS 主机名，因为当前 tailnet 对带主机名的 11434 请求返回 403。现有 `22`、`443`、`8443` 和 `8765` Serve 配置必须保留，不执行全局 `serve reset`。

### AI4MBSE LLM 档案

复用已有 Ollama/OpenAI-compatible 适配器，不修改应用推理代码。新增并启用一个档案：

| 字段 | 值 |
| --- | --- |
| ID | `windows-5080-ollama` |
| 名称 | `Windows 5080 Ollama` |
| 类型 | `local` |
| 协议 | `openai-chat` |
| Base URL | `http://100.88.143.10:11434/v1` |
| 模型 | `qwen3.5:9b-q8_0` |
| API Key | 空 |
| 超时 | `300` 秒 |

端口和 `local` 类型会使现有适配器走 Ollama 原生 `/api/chat`，沿用关闭思考输出、结构化 JSON、上下文预算和输出预算等现有行为。

## 数据流与状态

1. 用户在 AI4MBSE 发起需求分析。
2. 应用读取已启用的 `windows-5080-ollama` 档案。
3. 请求经 Tailscale 加密 TCP 到达 Windows Tailscale Serve。
4. Serve 转发给仅监听回环地址的 Ollama。
5. Ollama 在 RTX 5080 上运行 `qwen3.5:9b-q8_0`，响应沿原路径返回。
6. AI4MBSE 继续使用现有结构校验、分块合并、Job 状态和持久化逻辑。

本次不迁移 AI4MBSE Web 服务、SQLite 数据库、工作区文件或确定性计算；只有 LLM 推理远程化。

## 错误处理与安全边界

- Tailscale 或 Windows 不可达时，现有适配器返回明确的 LLM 请求失败；规则基线和人工审核流程继续可用。
- Ollama 未运行或模型不存在时，连接测试必须失败，不保存伪成功状态。
- 不在仓库、配置文件或命令中新增 API Key；此 tailnet 内连接不需要 API Key。
- 不开放公网 Funnel，不修改 Windows Ollama 为 `0.0.0.0`，不放宽 Tailscale ACL；应用层使用 HTTP 仅因为传输已在 Tailscale WireGuard 内加密。
- 不覆盖既有 Tailscale Serve 端口配置。

## 验证

按以下顺序验收：

1. 在 Windows 上检查 Serve 状态，确认新增 TCP `11434`，且既有 Serve 条目仍在。
2. 从 Mac 请求 `http://100.88.143.10:11434/api/tags`，确认返回 `qwen3.5:9b-q8_0`。
3. 从 Mac 向 `/api/chat` 发送最小非流式请求，确认内容由远端 Ollama 返回。
4. 保存并启用 AI4MBSE 档案，执行“测试连接”，确认模型名和 Base URL 正确。
5. 发起一次最小项目分析，确认 Job 完成，并在 Windows 上通过 `ollama ps` 观察模型实际运行。

## 回滚

若代理不可用，执行 `tailscale serve --tcp=11434 off` 删除 11434 单项配置，并恢复原 AI4MBSE 活跃档案。回滚不得使用 `tailscale serve reset`，以免删除远端已有服务。仓库代码和项目数据无需回滚。
