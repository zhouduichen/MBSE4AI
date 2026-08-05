# RFLP-Lite 开发状态

**最后更新：** 2026-08-05  
**当前版本：** 0.1.0  
**状态：** 本地最小链路已跑通，需求工作台已完成首版

## 当前完成度

| 模块 | 状态 | 可验证结果 |
|---|---|---|
| 本地 RFLP 垂直链路 | 已完成 | Artifact → Claim → R/F/L/P → Candidate → Simulation → Baseline → Delta → TaskContract → Evidence |
| 本地 Web UI | 已完成 | 工作区、运行中心、模型、决策、仿真、治理和能力占位页面可用 |
| 真实需求输入 | 已完成 | 支持文本粘贴及 TXT、Markdown、DOCX、Python、JSON、YAML、TOML 上传 |
| 利益相关方前置链路 | 已完成首版 | StakeholderCandidate → Stakeholder/Concern/Need → Requirement |
| 人工审核 | 已完成首版 | 候选可编辑、接受、驳回；可批量接受来源完整的明确候选 |
| 动态 RFLP | 已完成首版 | 不再要求固定三条需求；按审核结果生成 R/F/L/P 和正式关系 |
| RFLP 图形 | 已完成首版 | 服务端确定性 SVG，支持 JSON/SVG 下载和需求来源链查看 |
| LLM API | 代码已完成，待真实模型实测 | 手动调用 OpenAI-compatible API，只生成待审核 inferred 候选 |
| Python ActualModel / Delta / Evidence 接入 | 未开始 | 当前 Python 只用于文本/AST 角色线索和已有 Evidence 示例 |
| 拖拽图编辑、复杂文档版面、多人权限 | 延后 | 首版不实现 |

## 已实现链路

```text
Artifact
→ TextSpan
→ StakeholderCandidate
→ Stakeholder / Concern / Need
→ Claim / Requirement
→ R → F → L → P
→ Candidate / Simulation
→ Baseline / Delta / TaskContract / Evidence
```

关键门禁：

- 原文明确角色可由规则产生候选；隐含角色只能由 LLM 提议或人工补充。
- inferred 候选不会被“批量接受”自动批准。
- Need 必须关联已接受的 Stakeholder、Concern 和来源 TextSpan。
- Requirement 必须来自已接受 Need，或明确标记为法规/系统约束。
- AI 不得批准 Stakeholder、Requirement、RFLP 或 Baseline。

## 需求工作台

入口：`/w/{workspace}/requirements`

操作流程：

1. 粘贴需求或上传工程资料。
2. 点击“规则分析”。
3. 审核 Stakeholder、Concern、Need 和 Requirement 候选。
4. 点击“接受全部可追溯候选”，或逐条编辑、接受、驳回。
5. 点击“生成 RFLP 规划图”。
6. 检查 R→F、F→L、L→P 覆盖率和需求来源链。
7. 下载规范化 JSON 或确定性 SVG。

主要路由：

| 方法 | 路由 | 用途 |
|---|---|---|
| GET | `/w/{workspace}/requirements` | 打开工作台 |
| POST | `/w/{workspace}/requirements/analyze` | 规则分析文本或文件 |
| POST | `/w/{workspace}/requirements/review` | 编辑并接受/驳回单项 |
| POST | `/w/{workspace}/requirements/accept-traceable` | 批量接受明确且来源完整的候选 |
| POST | `/w/{workspace}/requirements/ai` | 手动请求 LLM 候选 |
| POST | `/w/{workspace}/requirements/generate` | 生成动态 RFLP |
| GET | `/w/{workspace}/requirements/model.json` | 下载 RFLP JSON |
| GET | `/w/{workspace}/requirements/model.svg` | 下载 RFLP SVG |

## 代码位置

| 文件 | 职责 |
|---|---|
| `src/rflp_lite/adapters/readers.py` | 文本、DOCX、Python AST 和中英文义务句读取 |
| `src/rflp_lite/application/requirements_workbench.py` | 候选发现、审核门禁、LLM 建议、RFLP 生成与 SVG |
| `src/rflp_lite/application/synthesize.py` | 动态 R/F/L/P 节点和关系合成 |
| `src/rflp_lite/adapters/sqlite_repository.py` | SQLite 工作台、模型和审计持久化 |
| `src/rflp_lite/application/web_facade.py` | Web 用例编排与事务边界 |
| `src/rflp_lite/interface/web/routes.py` | HTTP 路由、上传和下载 |
| `src/rflp_lite/interface/web/templates/requirements-workbench.html` | 单页需求建模界面 |

## 数据与安全

- 工作台状态保存于 `<workspace>/.rflp/model.db` 的 `workbench` 表。
- 上传文件按内容哈希保存到 `<workspace>/inputs/`，避免同名文件静默覆盖。
- 单文件限制 5 MiB，只接受白名单后缀。
- API Key 只从环境变量读取，不进入页面、SQLite 或审计日志。
- SVG 文本经过 XML/HTML 转义。
- Web 默认只监听 `127.0.0.1`，未实现登录和公网部署。

## LLM 配置

```bash
export RFLP_LLM_BASE_URL=http://127.0.0.1:11434/v1
export RFLP_LLM_MODEL=your-model
export RFLP_LLM_API_KEY=local-key
```

未配置时，“AI 辅助分析”返回明确错误；规则分析、人工审核和 RFLP 生成仍可独立运行。

## 验证记录

2026-08-05 完成：

- `pytest`：49 passed；仅有 FastAPI TestClient 的第三方弃用提示。
- Import Linter：3 contracts kept，0 broken。
- `python -m build`：sdist 和 wheel 构建成功。
- 真实 DOCX 验证：执行规划 v1.2 解析出 756 个 TextSpan、4 个明确利益相关方候选、62 条 Claim 候选。
- 浏览器验收：粘贴三条需求，完成分析、批量审核、动态 RFLP、100% 三层覆盖、来源链和下载入口验证。
- 浏览器控制台：0 error，0 warning。
- LLM 已验证“未配置时安全失败”和 inferred 隔离；尚未使用真实模型端点完成联调。

复现命令：

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build
.venv/bin/rflp web --host 127.0.0.1 --port 8000 --workspace-root workspaces
```

## 关键提交

| 提交 | 内容 |
|---|---|
| `614532d` | 利益相关方审核、动态 RFLP、LLM 候选和确定性 SVG 核心 |
| `dbadac2` | 本地需求建模 Web 工作流 |
| `6d4c9be` | README 使用说明 |

## 已知限制与下一步

- 当前 DOCX 只读取基础段落，不恢复表格、图形和复杂版面；真实样本需要时再接入 Docling。
- 角色、Concern、Need 和 L/P 分组使用轻量启发式规则，需要用更多工程样本校准。
- SVG 是稳定只读图，不支持拖拽和自由连线。
- LLM 尚无模型管理、流式交互、重试队列和本地模型生命周期管理。
- 下一独立子项目是 Python 项目接入：ActualModel → Delta → TaskContract → Evidence；尚未宣称完成。
