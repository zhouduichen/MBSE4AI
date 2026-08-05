# RFLP-Lite 本地 Web UI 验证记录

> 历史验证记录：本文反映 2026-08-04 的状态。需求工作台已于 2026-08-05 完成，最新状态见 `docs/DEVELOPMENT_STATUS.md`。

**日期：** 2026-08-04

## 环境

- macOS arm64
- Python 3.12.13
- rflp-lite 0.1.0
- FastAPI 0.141.1
- Uvicorn 0.52.1
- Jinja2 3.1.6
- python-multipart 0.0.32
- httpx 0.28.1
- OR-Tools 9.15.6755
- HTMX 2.0.10，本地静态文件 SHA-256：`71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de`

## 自动化门禁

执行：

```bash
.venv/bin/python -m pytest -v
.venv/bin/lint-imports
.venv/bin/check-jsonschema --schemafile schemas/profile.schema.json examples/profile.json
.venv/bin/python -m build
```

结果：

- pytest：46 passed；另有 1 条 FastAPI TestClient 关于未来 `httpx2` 的第三方弃用提示，不影响当前功能。
- Import Linter：3 contracts kept，0 broken。
- Profile JSON Schema：通过。
- sdist 与 wheel：构建通过。
- wheel 内容：已确认包含 14 个 Web 模板、`app.css`、`htmx.min.js` 和 HTMX 许可证。

## Solver 真实复核

固定 Seed `42`，候选上限 `3`，超时 `5s`：

| Solver | 状态 | Candidate | Claim | TaskContract | Evidence | Baseline hash | Result hash |
|---|---:|---:|---:|---:|---:|---|---|
| Heuristic | passed | 3 | 3 | 3 | 9 | `a5f3f51e6e63d90041acb89bdfdb752f6b41a19dc396d8fa49584e80029aed51` | `8f74626cd873219a95a7f874051bbe31ac2bbe919ab8a0088cc447a3a302cfab` |
| CP-SAT | passed | 3 | 3 | 3 | 9 | `a5f3f51e6e63d90041acb89bdfdb752f6b41a19dc396d8fa49584e80029aed51` | `0be6ec9548f8b537837a0697b9573dbbb613fbfba01ac4a1405b5276e482d2c7` |

两种 Solver 固化了相同的 Baseline，结果哈希因 Solver/Profile 不同而不同，符合设计预期。

## 浏览器验收

使用 Codex 内置浏览器访问 `http://127.0.0.1:8000`，完成以下真实操作：

1. 空状态正确显示，不包含伪造指标。
2. 创建 `local-web-demo` 工作区。
3. 从运行中心提交 Heuristic、Seed 42，并由 HTMX 重定向至真实运行详情。
4. 运行详情显示 `passed`、选中候选、4 个仿真事件、12 个已登记 JSON 文件及完整链路导航。
5. Artifact/TextSpan/Claim、RFLP、Candidate/Decision、Simulation、Baseline/Delta、TaskContract、Evidence/Audit 页面均由 TestClient 和真实浏览器入口验证。
6. 能力中心显示 9 张规划卡和 9 个禁用按钮；页面没有外部脚本、样式或字体请求。
7. 700 × 900 窄屏检查：主壳和能力卡均切为单列，没有水平溢出。
8. 浏览器控制台：0 error，0 warning。
9. 浏览器最终停留在 `local-web-demo` 驾驶舱并展示给用户。

## 安全与错误验证

- 工作区名拒绝绝对路径、`..`、正反斜杠和空名称。
- Web 工作区只能位于仓库 `workspaces/` 下。
- 下载端点只允许 12 个已登记运行 JSON；路径穿越返回 400/404。
- 负 Seed 返回中文 422 错误，不启动运行。
- Adapter 失败测试确认事务回滚，已有 Baseline 哈希不变。
- FastAPI 的 OpenAPI、Swagger 和 ReDoc 入口默认关闭。
- 服务默认监听 `127.0.0.1`，没有登录或公网暴露。

## 已知限制（截至 2026-08-04）

- 当前运行同步执行；长耗时 LLM、Docling 和远程 Solver 需要未来的持久化任务队列。
- 当时的运行结果页面只读展示模型和 Baseline；需求工作台的候选编辑与审核功能于 2026-08-05 增加。
- 当前自动浏览器验收使用 Codex 内置浏览器；Safari/WebKit 需要在本机手工打开相同地址复核基础布局。
- FastAPI 0.141.1 的 TestClient 会发出一条关于未来 `httpx2` 的弃用提示；测试行为正常，待上游迁移成熟后再调整测试依赖。
- 本次没有配置 Git remote，也没有向 `https://github.com/zhouduichen/MBSE4AI` 推送。
