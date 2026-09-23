# Web 纵向模型生成工作流设计

## 状态

本设计用于把现有五阶段 ModelGraph 生成能力收敛为用户可观察、可继续的 Web 主流程。它是完整 AI4MBSE 目标的第一条产品切片，不替代后续 F/L/P 推理深度、SysML 互操作和真实 Provider 质量建设。

## 目标

用户在 Web 工作台输入需求、上传工程资料或导入已有模型后，点击一次“生成完整 MBSE 模型”，即可立即得到一个可跟踪的生成运行，并看到 Requirements → Functional → Logical → Physical → V&V 的阶段进度。生成完成后，工作台从同一份 ModelGraph revision 展示追溯、质量检查、V&V 和可编辑模型；用户可以继续 Review、Edit、Lock 或触发下游生成。

现有同步 API 和 CLI 保持兼容。新的异步入口只服务 Web 的完整五阶段主按钮，避免一次改动破坏已有脚本和测试。

## 用户体验

1. 用户在 Analysis 页面提交需求、目标、文档或已有 SysML 模型。
2. 用户选择本次 Profile 后点击“生成完整 MBSE 模型”。页面立即进入“正在生成”状态，按钮被禁用，并显示当前阶段、已完成阶段数和远端模型标识。
3. 页面以固定间隔读取该 Run 的高层进度：Requirements、Functional、Logical、Physical、V&V。任务键、Patch、CAS 和原始诊断不出现在首屏进度中。
4. 运行完成后页面重新加载同一项目的 ModelGraph 工作台，显示逐阶段结果、RFLP/V&V/端到端追溯、Methodology findings、Controller 下一动作和 SysML/交付包入口。
5. 运行失败或被阻断时，页面保留已写入的安全模型 revision，显示可读的失败阶段和下一步提示；不把部分结果宣称为完整模型，也不自动切换到本机模型。

## API 契约

新增：

```text
POST /projects/{project_id}/analysis/runs
```

请求体复用完整生成所需的字段：`mode`（仅允许 `generate` 或 `vertical`）、`requirement_text`、`goal`、`document_ids`、`profile_id` 和 `force_run`。服务在返回前完成输入边界检查、写入目标/需求输入并创建唯一 Run；响应为 HTTP 202：

```json
{
  "status": "accepted",
  "run": {
    "run_id": "web-run-...",
    "project_id": "p1",
    "status": "running",
    "progress_url": "/projects/p1/runs/web-run-..."
  }
}
```

生成在进程内受限线程池中执行，仍调用现有 `ModelGenerationService.generate(...)`，不绕过 Runtime → Compiler → Validator → CAS 边界。

已有：

```text
GET /projects/{project_id}/runs/{run_id}
```

在保留现有完整 Run/Step JSON 的基础上增加只读 `progress`：

```json
{
  "progress": {
    "status": "running",
    "current_stage": "functional",
    "current_stage_label": "功能分析",
    "completed_stages": 1,
    "total_stages": 5,
    "stages": [
      {"stage": "requirements", "label": "需求分析", "status": "completed"},
      {"stage": "functional", "label": "功能分析", "status": "running"}
    ]
  }
}
```

`progress` 从已持久化的五个 vertical Step 推导，不另建状态表。终态包括 `completed`、`failed`、`blocked`、`degraded` 和 `cancelled`。

## 运行与并发

- `ModelGenerationService.prepare_generation(...)` 负责同步校验输入并创建 Run；worker 使用同一 `run_id` 调用既有 `generate(...)`，因此状态、Patch、Revision 和审计仍由原有应用服务负责。
- FastAPI 应用创建一个小型 `ThreadPoolExecutor`，默认最多两个生成任务；SQLite repository 已有进程内 RLock，可安全串行化同一连接的读写。
- worker 捕获未被生成服务转成结果的异常，写入 `failed` Run 和有界诊断。已完成阶段不回滚，不伪造后续阶段。
- 进程重启恢复不是本切片的隐式承诺；持久化 Run 仍可被查询，后续可单独加入恢复策略。
- Profile 的 Base URL、模型和超时原样交给现有 Runtime。远程 SSH/Tailscale 模型是唯一真实 LLM 验收来源；绝不回退到 `127.0.0.1` 本机模型。

## Web 行为

Analysis 页面完整生成按钮调用 `/analysis/runs` 并轮询 `/runs/{run_id}`；单阶段调试按钮继续使用旧同步入口。进度文案只显示工程阶段和“正在等待远程模型/已完成/需要处理”等用户语言。轮询在 1 秒间隔下限时 15 分钟，网络错误允许继续重试；终态或超时会停止轮询并留下可复查的 Run URL。

## 错误边界

- 输入缺失、Profile 不存在或模式非法：创建异步 Run 前返回现有 4xx 错误，不产生运行记录。
- 远程 Provider 失败：worker 保留现有 Run 的失败诊断，页面显示失败阶段；不转换为成功，不调用本机模型。
- 浏览器轮询失败：不提交新 Patch；页面仅提示重新打开工作台查看持久化 Run。
- 两次提交：每次使用独立 Run ID；CAS/现有并发保护仍是 ModelGraph 写入权威。

## 验收

- 使用慢速测试 Runtime，`POST /analysis/runs` 在完整生成结束前返回 202 和 Run ID。
- 轮询能观察五个阶段从 queued/running 到 completed，完成后同一 Run 的 ModelGraph 含 Requirement、Function、Logical、Physical、Verification 和 Validation，并有完整追溯摘要。
- 测试 Runtime 抛出异常时 Run 进入 failed，诊断有界，页面不显示“生成完成”。
- 既有同步 API、CLI、完整 pytest、compile、ruff、架构指标和 import-linter 保持通过。
- 真实 Provider 验收通过 SSH 端口转发访问 `Jiayu-intern` 上的 vLLM；服务未就绪时只记录事实，不启动本机模型。

## 非目标

- 不改变 ModelGraph schema、SysML v2 子集、Controller 决策语义或现有五阶段生成算法。
- 不把 23-task 台账暴露为用户主流程，也不新增稳定性重复实验。
- 不建设跨进程任务队列、登录权限、分布式锁或自动恢复；这些是独立后续切片。
