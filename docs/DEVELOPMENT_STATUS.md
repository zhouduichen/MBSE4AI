# RFLP-Lite 开发状态

**最后更新：** 2026-08-17
**当前版本：** 0.1.0  
**状态：** 本地最小链路已跑通，需求工作台、Python 项目接入、任务契约执行与测试执行沙箱均已完成首版；CLI 已可无 Web 全自动跑通

## 当前完成度

| 模块 | 状态 | 可验证结果 |
|---|---|---|
| 本地 RFLP 垂直链路 | 已完成 | Artifact → Claim → R/F/L/P → Candidate → Simulation → Baseline → Delta → TaskContract → Evidence |
| 本地 Web UI | 已完成 | 工作区、运行中心、模型、决策、仿真、治理和能力占位页面可用 |
| 项目管理与需求删除 | 已完成首版 | `/` 管理多个 workspace 项目；项目卡片可展开查看需求；删除当前需求会清理派生模型并保留 `deleted` 台账状态和 `requirements.deleted` 审计事件 |
| 项目隔离与需求串联 | 已完成首版 | 每个 workspace 绑定独立项目作用域；同项目内需求可通过 Stakeholder、Scenario、R/F/L/P、Interface 和 trace link 串联；跨项目引用会被拒绝 |
| 真实需求输入 | 已完成 | 支持文本粘贴及 TXT、Markdown、DOCX、数字/扫描 PDF、Python、JSON、YAML、TOML 上传；PDF 页区域和 OCR 诊断保留在 v2 工作台 |
| 客户需求结构化（验收 1.1） | 已完成首版 | 客户语言实体、能力谓词、数量范围、指标约束、验证方式和来源区域；结构化需求候选默认不批准 |
| 需求追溯与验收指标 | 已完成首版 | `derivedFrom / representedBy / satisfiedBy / refines` 矩阵、覆盖率、precision/recall/F1 与 provenance 指标；SQLite 持久化 |
| MBSE 用例辅助（验收 1.2） | 已完成首版 | 生成 Use Case、活动图、时序图语义集合；人工逐条编辑、修订版本和 JSON/SysML/SVG 导出 |
| MBSE 顺序图设计模块 | 已完成首版 | UML Interaction 契约、场景确认门禁、横向生命线/纵向时间轴、同步/异步/返回箭头、SVG 与 Web/API 入口；旧 MBSE 消息模型保持兼容 |
| 需求/MBSE/场景确认闭环 | 已完成首版 | 候选逐条审核、编辑后回退、MBSE 草稿确认、场景确认门禁、审核历史和导出/执行状态门禁 |
| 利益相关方前置链路 | 已完成首版 | StakeholderCandidate → Stakeholder/Concern/Need → Requirement |
| 人工审核 | 已完成首版 | 候选可编辑、接受、驳回；可批量接受来源完整的明确候选 |
| 动态 RFLP | 已完成首版 | 不再要求固定三条需求；按审核结果生成 R/F/L/P 和正式关系 |
| RFLP 图形 | 已完成首版 | 领域中立 LLM 架构可生成多个 F/L/P 节点、接口和关系；节点携带需求来源，缺失架构时显示待分析占位节点；服务端 SVG 支持 JSON/SVG 下载 |
| 项目场景与执行 | 已完成首版 | 一次项目分析生成当前输入相关的正常/边界/故障/恢复/误操作场景；场景页以折叠卡片展示完整详情，默认接受，保留手动场景，并生成安全的声明性轨迹、Job 和 Evidence |
| Profile / Pack | 已完成 MVP | Profile schema 校验、CLI/Web JSON 保存读取和运行记录导出 |
| SysML v2 交换 | 已完成 MVP | RFLP 模型 JSON 与 SysML v2 常用子集文本导入、导出和往返校验；完整语义仍未配置 |
| MLflow Tracking | 已完成 MVP | 安装可选 SDK 后将 Profile、指标、Tag 和运行 Artifact 写入本地/远程 MLflow；缺失时返回 `not_configured` |
| 本地 Job / API / Plugin | 已完成 MVP | 持久化同步 Job 状态、`/api/v1` JSON API、进程内插件注册与结构化调用 |
| 项目级 LLM 分析 | 代码已完成，待真实模型实测 | 一次 OpenAI-compatible 请求读取当前项目输入，自动填充 Stakeholder、Concern、Need、Requirement、Scenario、R/F/L/P 和 MBSE；不注入固定领域包 |
| 领域中立分析配置 | 已完成首版 | 默认关闭领域包；可通过项目级 API 显式启用常见 `common-v1` 配置，保留 provenance；窄领域包不进入普通分析路径 |
| 版本化 MBSE 语义模型 | 已完成首版 | `operational / functional / logical / physical / technical_requirements` 五类语义区段、稳定实体/关系、来源与版本校验，并保留旧 MBSE projection |
| 专业 MBSE 多视图 | 已完成首版 | 环境、利益相关方、需求、生命周期、用例、场景、功能、逻辑、分配、物理、技术需求、追踪矩阵和 RFLP 总览按视图选择布局 |
| 可选专业绘图引擎 | 已完成首版 | Graphviz、PlantUML 通过受控适配器接入；无外部引擎或执行失败时自动回退内置 SVG/矩阵渲染 |
| Python ActualModel / Delta / Evidence 接入 | 已完成首版 | 工作台 RFLP 生成后自动建立基线，扫描本地 Python 项目（AST/OpenAPI/JUnit）生成 ActualModel 与 Evidence，计算 MISSING/EXTRA Delta，派生 TaskContract；Web 页面与 CLI 均可操作 |
| 任务契约执行 | 已完成首版 | 重扫描项目目录，逐条判定 TaskContract 是否已满足（RESOLVED/UNRESOLVED），确定性、只读、不执行用户代码 |
| 测试执行沙箱 | 已完成首版 | 支持 pytest/unittest、超时、输出、POSIX 内存/文件句柄限制、确定性缓存和受控并行；统一回填 Evidence 并如实报告每个 runner |
| 拖拽图编辑、复杂文档版面、多人权限 | 延后 | 首版提供语义编辑 API；CAD/多学科仿真和组织级权限仍在后续 M3-M8 |
| 总体概念布局与 MDO（验收 2.1/2.2） | 已完成首版 | 版本化领域包、JSON/CSV/SQLite 方案导入、3–5 套可行 SVG 布局、气动/结构/重量重心批量评估、缓存/失败隔离/代理门禁/Pareto、CLI/API/Web 与可执行验收报告 |
| 旧版智能 MBSE 发现 | 已完成兼容入口 | 保留显式 `--pack` 的发现页、CLI/API 和领域包能力；默认需求提交不再调用固定领域包 |

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

智能发现支线：

```text
Sparse Input
→ Seed Model
→ 8 Lens Candidate Sets
→ Normalization / Coverage
→ Human Review
→ Accepted Semantic Graph
→ DiagramSpec
→ Deterministic SVG
```
```

关键门禁：

- 原文明确角色可由规则产生候选；隐含角色只能由 LLM 提议或人工补充。
- 普通流程的常规生成输出（规则需求、起始场景、动态 RFLP、MBSE 草稿、快速流程基线）自动接受；AI 生成的 inferred 候选和发现流水线候选不会被“批量接受”自动批准，必须逐条人工审核。
- Need 必须关联已接受的 Stakeholder、Concern 和来源 TextSpan。
- Requirement 必须来自已接受 Need，或明确标记为法规/系统约束。
- 智能发现流水线中 AI 不得批准 Stakeholder、Requirement、RFLP 或 Baseline；普通快速流程基线自动建立，正式交付前标注人工复核提示。

## 需求工作台

入口：`/w/{workspace}/requirements`

项目入口：`/`。开始项目页面列出所有项目卡片；展开项目可查看当前需求，点击项目进入该项目的需求工作台。删除需求只删除当前内容和自动生成结果，保留项目、原始输入和审计历史。

操作流程：

1. 粘贴需求或上传工程资料（含 DOCX/PDF）；勾选“并入现有工作台”可把多份文档追加到同一工作台并保留已审核项。
2. 点击“提交并分析”。系统对当前项目只发起一次领域中立的 LLM 分析，并自动写入 Stakeholder、Concern、Need、Requirement、多个场景、RFLP 和 MBSE 模块；没有可用 LLM 时会显示等待状态，不补造行业结果。
3. 在场景生成模块点击折叠卡片查看完整详情；当前项目内的场景默认接受，编辑或手动新增的场景也会保留。
4. 检查 R→F、F→L、L→P、接口关系、待分析节点和需求来源链。
5. 下载规范化 JSON 或确定性 SVG。
6. 在“MBSE 设计图”入口查看/下载 Use Case、活动图和顺序图。

主要路由：

| 方法 | 路由 | 用途 |
|---|---|---|
| GET | `/w/{workspace}/requirements` | 打开工作台 |
| POST | `/w/{workspace}/requirements/analyze` | 提交需求并自动完成规则分析、AI 补全及模块写入 |
| POST | `/w/{workspace}/requirements/delete` | 删除当前 Requirement 及其自动生成结果，保留审计历史 |
| POST | `/w/{workspace}/requirements/review` | 编辑并接受/驳回单项 |
| POST | `/w/{workspace}/requirements/accept-traceable` | 批量接受明确且来源完整的候选 |
| POST | `/w/{workspace}/requirements/ai` | 兼容旧版的手动请求 LLM 候选 |
| POST | `/w/{workspace}/requirements/generate` | 生成动态 RFLP |
| GET | `/w/{workspace}/requirements/model.json` | 下载 RFLP JSON |
| GET | `/w/{workspace}/requirements/model.svg` | 下载 RFLP SVG |
| POST | `/w/{workspace}/requirements/implicit-constraints` | 生成待逐条审核的隐含约束候选 |
| POST | `/w/{workspace}/requirements/mbse` | 生成语义 MBSE 模型 |
| GET | `/w/{workspace}/requirements/mbse` | 打开 MBSE 设计图模块，切换总览/用例图/活动图/顺序图 |
| GET | `/w/{workspace}/requirements/mbse/sequence?scenario_id=...` | 查看指定已确认场景的 UML 顺序图 |
| GET | `/w/{workspace}/requirements/mbse/sequence.svg?scenario_id=...` | 下载指定场景顺序图 SVG |
| GET | `/w/{workspace}/requirements/mbse.json` | 下载 MBSE JSON |
| GET | `/w/{workspace}/requirements/mbse.sysml` | 下载 MBSE SysML 子集 |
| GET | `/w/{workspace}/requirements/mbse.svg?view=all` | 下载 Use Case/活动/时序 SVG |
| GET | `/api/v1/workspaces/{workspace}/requirements/analysis-config` | 查看当前项目领域中立分析配置和可选常见领域包 |
| PUT | `/api/v1/workspaces/{workspace}/requirements/analysis-config` | 显式保存项目级分析配置 |
| GET | `/api/v1/workspaces/{workspace}/requirements/mbse/views` | 查看 MBSE 专业视图目录 |
| GET | `/api/v1/workspaces/{workspace}/requirements/mbse/views/{view_id}` | 渲染指定视图并返回引擎/fallback 元数据 |

## 项目接入

入口：`/w/{workspace}/project`（Web）或 `rflp project approve/analyze`（CLI）。

操作流程：

1. 在需求建模中生成 RFLP 规划图。
2. 基线随正式 RFLP 自动生成（原“人工批准基线”改为“已自动生成”状态；`approve-baseline` 路由保留用于补齐历史工作区）。
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
| POST | `/w/{workspace}/project/approve-baseline` | 手动补齐基线（新流程随 RFLP 自动生成） |
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
rflp acceptance --requirements <file> [--gold <requirements-gold.json>]
rflp mbse generate --workspace <path>
rflp mbse confirm --workspace <path>
rflp mbse export --workspace <path> --format json|sysml|svg
rflp concept import --workspace <path> --pack <pack.json> --data <schemes.json|csv|db> [--table <table>]
rflp concept run --workspace <path> --pack <pack.json> --evaluator-profile <profile.json> --envelope <envelope.json>
rflp concept acceptance --pack <pack.json> --schemes <schemes.json> --envelope <envelope.json> --evaluator-profile <profile.json>
rflp discover draft --workspace <path> --pack urban-medical-aam-v1
rflp discover review --workspace <path> --candidate-id <id> --decision accepted --revision <n> --pack urban-medical-aam-v1
rflp discover finalize --workspace <path> --pack urban-medical-aam-v1
rflp discover export --workspace <path> --pack urban-medical-aam-v1 --diagram environment
rflp assess --workspace <path> --requirements <file> --source <dir> [--timeout 60]
```

`assess` 一步完成 需求工作台 → 批准基线 → 分析项目 → 运行测试 并输出汇总，适合脚本/CI 断言。测试命令还支持 `--memory-mib`、`--max-open-files`、`--output-mib` 和 `--no-cache`。

场景描述入口：`/w/{workspace}/requirements`。提交并分析会依据当前项目输入和 LLM 的通用语义结果自动生成相关的正常、边界、故障和恢复场景，不要求用户额外填写场景，也不固定套用某个行业的场景矩阵；场景页默认折叠，点击后可查看和编辑完整详情。场景支持步骤/预期结果逐行录入、Requirement ID 关联、删除、执行轨迹和 `/w/{workspace}/requirements/scenarios.json`、`scenario-runs.json` 下载。执行是安全的声明性轨迹，不触发仿真、测试或任意用户代码。

本地 MVP JSON API 入口为 `/api/v1`：提供工作区、需求、场景创建/查询/执行、Job 状态、Profile、RFLP SysML-lite/SysML v2 子集交换、MLflow Tracking 和本地插件发现/调用。Profile 可通过 `rflp profile show|validate|save` 管理；运行记录可通过 `rflp run export` 导出，SysML 文本可通过 `rflp sysml export|import` 处理。

匹配边界：基线 R/F 层的义务句与实际的 class/function/api-operation 按分词交集匹配；中英文之间无法用关键词对齐时，明确义务如实标为 `MISSING`，不猜测。

“执行验证”是确定性重扫描循环：只读重扫项目目录并重算与已批准基线的差异，判定每条任务契约 RESOLVED/UNRESOLVED，不运行任何用户代码或子进程。

“运行项目测试”是唯一的子进程边界：allowlist runner 使用固定 argv，强制超时（默认 60s）并 kill，产物写入临时目录后清理；pytest 归一化 JUnit，unittest 解析 verbose 输出；结果可按项目指纹缓存并受 jobs 限制并行执行。测试结果以独立客观 Evidence 呈现，不改变 R/F 匹配与契约状态。

## 代码位置

| 文件 | 职责 |
|---|---|
| `src/rflp_lite/adapters/readers.py` | 文本、DOCX、Python AST 和中英文义务句读取 |
| `src/rflp_lite/application/requirements_workbench.py` | 候选发现、审核门禁、LLM 建议、需求生命周期和 RFLP 生成 |
| `src/rflp_lite/application/scenarios.py` | 结构化场景创建、矩阵生成、校验、删除和确定性 ID |
| `src/rflp_lite/application/mbse_semantics.py` | 版本化 MBSE 语义模型、实体/关系校验和旧模型投影 |
| `src/rflp_lite/application/mbse_views.py` | MBSE 视图目录、语义过滤和视图编译入口 |
| `src/rflp_lite/application/mbse_graphviz.py` | 按视图生成 DOT、分组、方向、节点形状和关系样式 |
| `src/rflp_lite/application/mbse_plantuml.py` | 场景时序图和功能活动图的 PlantUML 源码编译 |
| `src/rflp_lite/application/mbse_matrix.py` | 分配矩阵、追踪矩阵和确定性 SVG 表格渲染 |
| `src/rflp_lite/ports/diagram_engine.py` | 可选专业绘图引擎协议和渲染结果契约 |
| `src/rflp_lite/adapters/graphviz_engine.py` | Graphviz DOT 外部引擎适配器和超时/失败诊断 |
| `src/rflp_lite/adapters/plantuml_engine.py` | PlantUML 外部引擎适配器和超时/失败诊断 |
| `src/rflp_lite/adapters/matrix_engine.py` | 内置矩阵渲染引擎 |
| `src/rflp_lite/application/scenario_execution.py` | 安全声明性场景执行轨迹和 Evidence |
| `src/rflp_lite/domain/sequence.py` | UML Interaction、Lifeline、Message、Occurrence、Execution 和 Combined Fragment 契约 |
| `src/rflp_lite/application/sequence_modeling.py` | 已确认场景到顺序图交互模型的适配、结构化步骤解析和旧 MBSE 模型兼容适配 |
| `src/rflp_lite/application/sequence_layout.py` | 确定性生命线、箭头消息、执行条和组合片段布局 |
| `src/rflp_lite/application/sequence_render.py` | 与业务建模解耦的 UML 风格 SVG 渲染 |
| `src/rflp_lite/application/jobs.py` | 本地原子 JSON Job 状态记录 |
| `src/rflp_lite/application/profile_packs.py` | Profile 校验、保存和运行记录导出 |
| `src/rflp_lite/application/interchange.py` | SysML-lite RFLP 交换格式与 round-trip 校验 |
| `src/rflp_lite/application/sysml_v2.py` | SysML v2 常用子集文本桥接与 round-trip 校验 |
| `src/rflp_lite/adapters/mlflow_tracking.py` | 可选 MLflow SDK Tracking 和 Artifact 记录 |
| `src/rflp_lite/application/plugins.py` | 进程内插件注册、发现和结构化调用 |
| `src/rflp_lite/interface/web/api_v1.py` | `/api/v1` 本地版本化 JSON API |
| `src/rflp_lite/application/synthesize.py` | 动态 R/F/L/P 节点和关系合成 |
| `src/rflp_lite/adapters/sqlite_repository.py` | SQLite 工作台、模型和审计持久化 |
| `src/rflp_lite/application/web_facade.py` | Web 用例编排与事务边界 |
| `src/rflp_lite/interface/web/routes.py` | HTTP 路由、上传和下载 |
| `src/rflp_lite/interface/web/templates/project-management.html` | 多项目卡片和项目下需求管理页面 |
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
| `src/rflp_lite/interface/web/templates/mbse-diagrams.html` | MBSE 设计图模块与顺序图场景选择页面 |

## 数据与安全

- 工作台状态保存于 `<workspace>/.rflp/model.db` 的 `workbench` 表。
- 上传文件按内容哈希保存到 `<workspace>/inputs/`，避免同名文件静默覆盖。
- 普通文本单文件限制 5 MiB；工程文档/PDF 限制 50 MiB、最多 500 页，只接受白名单后缀。
- API Key 只从环境变量读取，不进入页面、SQLite 或审计日志。
- SVG 文本经过 XML/HTML 转义。
- Web 默认只监听 `127.0.0.1`，未实现登录和公网部署。

## LLM 配置

```bash
export RFLP_LLM_BASE_URL=http://127.0.0.1:11434/v1
export RFLP_LLM_MODEL=your-model
export RFLP_LLM_API_KEY=local-key
```

未配置或供应商不可用时，自动流程会保留规则分析和原始输入，并在需求页显示“等待 LLM 分析”；不会使用固定领域模板生成利益相关方、场景或 RFLP。配置有效后，当前项目的 LLM 分析会在同一次“提交并分析”中自动写入各模块。

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

2026-08-10（MBSE 顺序图设计模块）：

- `pytest`：全量通过（仅有 FastAPI TestClient 的第三方弃用提示）。
- 新增 `ai4mbse/sequence-interaction` v1 契约，拆分领域校验、场景建模、几何布局和 SVG 渲染，降低模块耦合。
- 顺序图遵循 UML Interaction 语义：生命线横向排列、时间纵向推进；同步调用使用实线实心箭头，异步消息使用实线开放箭头，返回消息使用虚线开放箭头。
- 场景必须先人工确认；结构化消息可进入 `ready`，自由文本步骤保留为 `candidate` 并在页面提示补充语义。
- 新增 `/w/{workspace}/requirements/mbse/sequence`、顺序图 SVG 下载和 `/api/v1/workspaces/{workspace}/scenarios/{scenario_id}/sequence`；旧 `mbse.svg?view=sequence` 通过适配器接入新渲染器。

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

2026-08-13（确认流程简化 + 智能发现合并）：

- `pytest`：359 passed；Import Linter：4 contracts kept（新增 intelligence/diagrams 边界）；schema 校验与 `python -m build` 成功。
- 确认流程简化：常规生成输出（场景、MBSE、快速流程基线）自动接受；新增增量审核队列、变更集影响分析、历史需求台账回灌（`restore_legacy_requirements`）和工作台修订版本；页面文案与路由同步更新。
- 智能发现垂直切片（`codex/intelligent-mbse-discovery` 分支）合并回 main：稀疏输入 → seed → 8 视角候选 → 规范化/覆盖审计 → 逐项审核 → accepted graph → DiagramSpec → 确定性 SVG；`rflp discover draft/review/finalize/export` 可用；Web `/w/{workspace}/requirements/discovery` 与 `/api/v1/.../discovery/*` 入口。
- 合并无冲突：`workbench_schema.py`（v3 + 修订/审计字段）、`web_facade.py`（发现编排方法）、`base.html`（导航链接）三处重叠文件自动合并。

2026-08-13（发现功能完善 + CLI 稀疏输入）：

- `pytest`：365 passed；Import Linter：4 contracts kept。
- Web 发现页补全：逐项接受/驳回/编辑（携带修订版本）控件、finalize 纳入统一工作台、15 种图形卡片（同源 accepted graph、40 节点自动拆分）、覆盖审计只列出未覆盖/候选中单元格、完整诊断；新增 `/discovery/review`、`/discovery/edit`、`/discovery/finalize` HTML 路由。
- CLI：`rflp discover draft --input <file>` 从一句话/资料文件直接建立发现工作台（全中文输入可生成 seed 与覆盖审计），无需先建立已接受需求。
- 新增 Web 表单流程 6 个测试与 CLI 2 个测试；README 同步补 `--input` 用法并修正“人工批准基线”等过时描述。

2026-08-13（Web UI 重构为浅色精密仪表风 + 发现页完善收尾）：

- `pytest`：365 passed；Import Linter：4 contracts kept；`python -m build` 成功。
- 全站样式重构：dark-teal 控制台 → 纸白画布/发丝分隔/墨色文字/单一深蓝强调（B1 方向）；26 个模板迁移到新 token 词汇（`--bg/--acc/--ok` 等）；`meta color-scheme` 改为 `light`；测试中 `--color-accent` 断言迁移到 `--acc`。
- DESIGN.md 记录方向、token 表与布局叙事（兑现接口注释中的完成承诺）。

## 关键提交

| 提交 | 内容 |
|---|---|
| `614532d` | 利益相关方审核、动态 RFLP、LLM 候选和确定性 SVG 核心 |
| `dbadac2` | 本地需求建模 Web 工作流 |
| `6d4c9be` | README 使用说明 |
| `8dd7f98` | 解耦的 MBSE UML 顺序图契约、渲染器、Web/API 入口与回归测试 |

## 已知限制与下一步

- 当前 DOCX 读取基础段落与表格行（行内单元格以 “|” 连接），不恢复图形与复杂版面；真实样本需要时再接入 Docling。
- 角色、Concern、Need 和 L/P 分组使用轻量启发式规则，需要用更多工程样本校准。
- SVG 是稳定只读图，不支持拖拽和自由连线。
- LLM 尚无模型管理、流式交互、重试队列和本地模型生命周期管理。
- 匹配只在基线 R/F 与 actual class/function/api-operation 之间按分词交集进行；中英文、缩写与长句义务的匹配需要更多工程样本校准。
- 项目扫描只读 `.py` / OpenAPI JSON / JUnit XML；测试执行沙箱只运行固定的 `pytest` / `unittest` allowlist 命令（默认 60s 超时）。
- 测试结果作为独立客观 Evidence 呈现，不改变实现符号层面的 R/F 匹配与契约 RESOLVED/UNRESOLVED。
- 场景和 MBSE 常规输出自动接受后可直接生成 `declarative-only` 轨迹和顺序图；删除、驳回仍保留确认历史；轨迹不连接真实运行时，不自动驱动仿真、测试或契约验收。
- API 默认只用于本地受控客户端；登录、角色权限、限流、公网部署和远程插件隔离仍未配置。
- 测试运行器仅支持固定的 pytest/unittest allowlist；POSIX 资源限制在其他平台以不支持状态报告。
