# RFLP-Lite 开发状态

**最后更新：** 2026-08-08
**当前版本：** 0.1.0  
**状态：** 本地最小链路已跑通，需求工作台、Python 项目接入、任务契约执行与测试执行沙箱均已完成首版；CLI 已可无 Web 全自动跑通

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
| 场景描述 | 已完成首版 | 工作台支持结构化记录参与者、前置条件、步骤、预期结果、故障/异常和关联 Requirement，并可删除与导出 JSON；暂不执行场景 |
| LLM API | 代码已完成，待真实模型实测 | 手动调用 OpenAI-compatible API，只生成待审核 inferred 候选 |
| Python ActualModel / Delta / Evidence 接入 | 已完成首版 | 工作台 RFLP 人工批准为基线，扫描本地 Python 项目（AST/OpenAPI/JUnit）生成 ActualModel 与 Evidence，计算 MISSING/EXTRA Delta，派生 TaskContract；Web 页面与 CLI 均可操作 |
| 任务契约执行 | 已完成首版 | 重扫描项目目录，逐条判定 TaskContract 是否已满足（RESOLVED/UNRESOLVED），确定性、只读、不执行用户代码 |
| 测试执行沙箱 | 已完成首版 | 支持 pytest/unittest、超时、输出、POSIX 内存/文件句柄限制、确定性缓存和受控并行；统一回填 Evidence 并如实报告每个 runner |
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

1. 粘贴需求或上传工程资料；勾选“并入现有工作台”可把多份文档追加到同一工作台并保留已审核项。
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

## 项目接入

入口：`/w/{workspace}/project`（Web）或 `rflp project approve/analyze`（CLI）。

操作流程：

1. 在需求建模中生成 RFLP 规划图。
2. 在“项目接入”页面点击“人工批准基线”（基线只能由人批准，规范：`approve_baseline` 要求元素全部 `approved`）。
3. 填写本地 Python 项目目录的绝对路径，点击“分析项目”。
4. 查看 ActualModel 元素、基线→实际匹配、MISSING/EXTRA 差异、任务契约与证据。
5. 对项目作出修改后，点击“执行验证”重扫描判定每条任务契约是否已满足（RESOLVED/UNRESOLVED）。
6. 点击“运行项目测试”，选择 pytest/unittest、资源上限、并行度和缓存策略，在超时与隔离沙箱中运行并查看每个 runner 的结果。
7. 下载规范化 JSON：baseline、actual-model、matches、delta、task-contracts、evidence、project 汇总。

扫描规则：只读 `.py`（AST）、OpenAPI JSON、JUnit XML；跳过隐藏目录、依赖目录、符号链接与超大文件（单文件 1 MiB、最多 400 文件、深度 6）；不复制、不写入、不上传项目。

主要路由：

| 方法 | 路由 | 用途 |
|---|---|---|
| GET | `/w/{workspace}/project` | 项目接入页面 |
| POST | `/w/{workspace}/project/approve-baseline` | 人工批准基线 |
| POST | `/w/{workspace}/project/analyze` | 扫描项目并生成 Delta/TaskContract/Evidence |
| POST | `/w/{workspace}/project/verify` | 重扫描并判定任务契约是否已满足 |
| POST | `/w/{workspace}/project/test` | 运行 allowlist runner 并回填测试 Evidence（默认 pytest、60s 超时） |
| GET | `/w/{workspace}/project/download/{filename}` | 白名单下载规范化 JSON |

CLI：

```bash
rflp project approve --workspace <path>
rflp project analyze --workspace <path> --source <dir>
rflp project verify --workspace <path> --source <dir>
rflp project test --workspace <path> --source <dir> [--timeout 60] [--runner pytest|unittest] [--jobs 2]
rflp workbench build --workspace <path> --requirements <file> [<file> ...]
rflp assess --workspace <path> --requirements <file> --source <dir> [--timeout 60]
```

`assess` 一步完成 需求工作台 → 批准基线 → 分析项目 → 运行测试 并输出汇总，适合脚本/CI 断言。测试命令还支持 `--memory-mib`、`--max-open-files`、`--output-mib` 和 `--no-cache`。

场景描述入口：`/w/{workspace}/requirements`。场景保存在现有 workbench JSON 中，支持步骤/预期结果逐行录入、Requirement ID 关联、删除和 `/w/{workspace}/requirements/scenarios.json` 下载。场景目前不自动触发仿真或测试执行。

匹配边界：基线 R/F 层的义务句与实际的 class/function/api-operation 按分词交集匹配；中英文之间无法用关键词对齐时，明确义务如实标为 `MISSING`，不猜测。

“执行验证”是确定性重扫描循环：只读重扫项目目录并重算与已批准基线的差异，判定每条任务契约 RESOLVED/UNRESOLVED，不运行任何用户代码或子进程。

“运行项目测试”是唯一的子进程边界：allowlist runner 使用固定 argv，强制超时（默认 60s）并 kill，产物写入临时目录后清理；pytest 归一化 JUnit，unittest 解析 verbose 输出；结果可按项目指纹缓存并受 jobs 限制并行执行。测试结果以独立客观 Evidence 呈现，不改变 R/F 匹配与契约状态。

## 代码位置

| 文件 | 职责 |
|---|---|
| `src/rflp_lite/adapters/readers.py` | 文本、DOCX、Python AST 和中英文义务句读取 |
| `src/rflp_lite/application/requirements_workbench.py` | 候选发现、审核门禁、LLM 建议、RFLP 生成与 SVG |
| `src/rflp_lite/application/scenarios.py` | 结构化场景创建、校验、删除和确定性 ID |
| `src/rflp_lite/application/synthesize.py` | 动态 R/F/L/P 节点和关系合成 |
| `src/rflp_lite/adapters/sqlite_repository.py` | SQLite 工作台、模型和审计持久化 |
| `src/rflp_lite/application/web_facade.py` | Web 用例编排与事务边界 |
| `src/rflp_lite/interface/web/routes.py` | HTTP 路由、上传和下载 |
| `src/rflp_lite/interface/web/templates/requirements-workbench.html` | 单页需求建模界面 |
| `src/rflp_lite/adapters/project_scanner.py` | 本地项目目录扫描（Python AST / OpenAPI / JUnit） |
| `src/rflp_lite/adapters/test_execution_config.py` | runner、超时、输出和资源参数的纯校验 |
| `src/rflp_lite/adapters/test_runners.py` | pytest/unittest allowlist 命令和结果解析选择 |
| `src/rflp_lite/adapters/test_limits.py` | POSIX 资源限制策略与能力报告 |
| `src/rflp_lite/adapters/test_cache.py` | 项目指纹、缓存键和原子 JSON 缓存 |
| `src/rflp_lite/adapters/test_executor.py` | 有界子进程执行、JUnit 归一化和 runner 矩阵 |
| `src/rflp_lite/application/project_bridge.py` | 基线批准、ActualModel→Evidence→Delta→TaskContract 编排 |
| `src/rflp_lite/application/diff.py` | `compare_baseline_with_actual` 分词匹配与 MISSING/EXTRA |
| `src/rflp_lite/interface/web/templates/project-bridge.html` | 项目接入页面 |

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

2026-08-05（Python 项目接入）：

- `pytest`：76 passed（新增 27）；Import Linter：3 contracts kept。
- `python -m build`：sdist 和 wheel 构建成功。
- 端到端：连接 `examples/versioned-content-service`，扫描 3 文件、matched=4、MISSING=4、EXTRA=5，派生 3 条链式任务契约；二次分析字节级确定。
- 扫描边界：跳过隐藏/依赖/符号链接/超大文件，坏文件记入 parse_errors 不中断。
- 失效语义：编辑、批量接受、重新生成 RFLP 均清空已批准基线与差异结果。

2026-08-05（任务契约执行）：

- `pytest`：85 passed（新增 9）；Import Linter：3 contracts kept；`python -m build` 成功。
- 端到端：单条英文义务未实现 → 2 条 MISSING 契约全 `UNRESOLVED`；补上符号后重扫 → 全 `RESOLVED`、`missing=0`、`extra=0`；重复验证字节级确定。
- 门禁：未批准基线 / 无任务契约时“执行验证”明确报错；重新生成 RFLP 后执行结果随项目一并失效。

2026-08-06（测试执行沙箱 + 落地收尾）：

- `pytest`：112 passed；Import Linter：3 contracts kept；`python -m build` 成功。
- 端到端：需求 + 含一过一败测试的项目，`project test` 如实报告 `returncode=1`、`tests_passed=1`、`tests_failed=1`、`timed_out=false`。
- 沙箱：固定 pytest 命令、60s 超时 kill、临时目录隔离、归一化 JUnit 字节级确定；stdout/stderr 写入上限（默认 5 MiB）；失败/超时透出失败用例与输出尾部诊断。
- CLI 无 Web 全自动：`workbench build`（需求文件建工作台，支持多文件合并）与 `assess`（一步汇总报告）。
- DOCX 表格行按 “ID | 义务句” 合并为一条 span；verify/test 后同步刷新 delta/matches。
- 审计事件新增 `project.tested`、`requirements.merged`。

复现命令：

```bash
.venv/bin/pytest -q
.venv/bin/lint-imports
.venv/bin/python -m build
.venv/bin/rflp web --host 127.0.0.1 --port 8000 --workspace-root workspaces
.venv/bin/rflp project approve --workspace <path>
.venv/bin/rflp project analyze --workspace <path> --source <dir>
.venv/bin/rflp project verify --workspace <path> --source <dir>
.venv/bin/rflp project test --workspace <path> --source <dir> [--timeout 60]
.venv/bin/rflp assess --workspace <path> --requirements <file> --source <dir> [--timeout 60]
```

## 关键提交

| 提交 | 内容 |
|---|---|
| `614532d` | 利益相关方审核、动态 RFLP、LLM 候选和确定性 SVG 核心 |
| `dbadac2` | 本地需求建模 Web 工作流 |
| `6d4c9be` | README 使用说明 |

## 已知限制与下一步

- 当前 DOCX 读取基础段落与表格行（行内单元格以 “|” 连接），不恢复图形与复杂版面；真实样本需要时再接入 Docling。
- 角色、Concern、Need 和 L/P 分组使用轻量启发式规则，需要用更多工程样本校准。
- SVG 是稳定只读图，不支持拖拽和自由连线。
- LLM 尚无模型管理、流式交互、重试队列和本地模型生命周期管理。
- 匹配只在基线 R/F 与 actual class/function/api-operation 之间按分词交集进行；中英文、缩写与长句义务的匹配需要更多工程样本校准。
- 项目扫描只读 `.py` / OpenAPI JSON / JUnit XML；测试执行沙箱只运行固定 `pytest` 命令（60s 超时），不覆盖 pytest 以外的运行器。
- 测试结果作为独立客观 Evidence 呈现，不改变实现符号层面的 R/F 匹配与契约 RESOLVED/UNRESOLVED。
- 场景描述目前只负责结构化记录、Requirement 关联和 JSON 导出，不自动驱动仿真、测试或契约验收。
- 测试运行器仅支持固定的 pytest/unittest allowlist；POSIX 资源限制在其他平台以不支持状态报告。
